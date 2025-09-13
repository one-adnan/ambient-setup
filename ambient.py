"""
Ambilight (mss + numpy) - optimized, mode-aware, cross-platform (windows,mac & linux supported).
Usage:
    python ambient.py            # uses MODE default in file
    python ambient.py --mode movie
"""

import socket
import json
import time
import argparse
import os
import colorsys
import asyncio
import sounddevice as sd

import mss
import numpy as np

try:
    from pywizlight import wizlight, PilotBuilder
    _wizlight_available = True
except ImportError:
    _wizlight_available = False

# -------------------
# Networking / bulb
# -------------------
BULB_IP = "192.168.X.X"   # <-- set your smart bulb's IP
PORT = 38899

def send_wiz_color(r, g, b, brightness=255):
    msg = {"method":"setState","id":1,
           "params":{"state":True,"r":int(r),"g":int(g),"b":int(b),"dimming":int(brightness)}}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(json.dumps(msg).encode("utf-8"), (BULB_IP, PORT))
    finally:
        sock.close()

# -------------------
# Modes & tunables
# -------------------
class Modes:
    AMBIENT = "ambient"
    GAMING = "gaming"
    MOVIE = "movie"
    SOUND = "sound"

# Global defaults
CAPTURE_W, CAPTURE_H = 60, 34     # base downscale for ambient/movie
FRAME_DELAY_SEC = 0.08            # ~12.5 fps default
SAT_BOOST = 1.2
EMA_ALPHA = 0.65

HUE_BOOST_RANGE = (0.12, 0.45)
HUE_RANGE_SAT_MULT = 1.12

GAIN_R, GAIN_G, GAIN_B = 1.1, 1.0, 1.05

# Per-mode overrides
TWEAKS = {
    Modes.AMBIENT: {
        "FRAME_DELAY_SEC": 0.08,
        "EMA_ALPHA": 0.65,
        "CAPTURE_W": 60,
        "CAPTURE_H": 34,
    },
    Modes.GAMING: {
        "FRAME_DELAY_SEC": 0.03, # faster updates
        "EMA_ALPHA": 0.30,       # final smoothing on 0-255
        "CAPTURE_W": 16,        # coarse grid -> more reactive
        "CAPTURE_H": 16,
        # additional internal tuning applied in code: coarse sampling + temporal boost
    },
    Modes.MOVIE: {
        "FRAME_DELAY_SEC": 0.08,
        "EMA_ALPHA": 0.65,
        "CAPTURE_W": 48,
        "CAPTURE_H": 28,
        "SAT_BOOST": 1.1,
    },
}

# -------------------
# Helpers
# -------------------
def get_tunable(name, mode):
    return TWEAKS.get(mode, {}).get(name, globals()[name])

# Vectorized sRGB <-> linear conversion (works on scalars & arrays)
def srgb_to_linear(c):
    c = np.asarray(c)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def linear_to_srgb(c):
    c = np.asarray(c)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * (c ** (1/2.4)) - 0.055)

# Postprocess linear averages -> final 0..255 rgb and brightness v
def postprocess_from_linear(r_lin, g_lin, b_lin, mode):
    # r_lin/g_lin/b_lin are scalars in [0..1] linear space
    # Convert to sRGB
    r = float(linear_to_srgb(r_lin)); r = max(0.0, min(1.0, r))
    g = float(linear_to_srgb(g_lin)); g = max(0.0, min(1.0, g))
    b = float(linear_to_srgb(b_lin)); b = max(0.0, min(1.0, b))

    # HSV tweak
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s *= get_tunable("SAT_BOOST", mode)
    hue_boost_range = get_tunable("HUE_BOOST_RANGE", mode)
    hue_range_sat_mult = get_tunable("HUE_RANGE_SAT_MULT", mode)
    if hue_boost_range[0] <= h <= hue_boost_range[1]:
        s *= hue_range_sat_mult
    s = max(0.0, min(1.0, s))

    if mode == Modes.MOVIE:
        v = v ** 0.9

    r, g, b = colorsys.hsv_to_rgb(h, s, v)

    # Per-channel gain
    r *= get_tunable("GAIN_R", mode)
    g *= get_tunable("GAIN_G", mode)
    b *= get_tunable("GAIN_B", mode)

    # Clip and convert to 0..255
    r = max(0.0, min(1.0, r)); g = max(0.0, min(1.0, g)); b = max(0.0, min(1.0, b))
    return int(r * 255), int(g * 255), int(b * 255), v

# -------------------
# Fast capture + average routines (mss + numpy)
# -------------------
sct = mss.mss()
monitor = sct.monitors[1]  # primary full screen

def _subsample(img_np, target_w, target_h):
    """Return coarse subsample roughly target_w x target_h using strides."""
    h, w = img_np.shape[:2]
    step_x = max(1, w // target_w)
    step_y = max(1, h // target_h)
    return img_np[::step_y, ::step_x]

def get_screen_linear_avg(mode, prev_lin=None):
    """
    Returns (r_lin_mean, g_lin_mean, b_lin_mean, brightness_v)
    - r/g/b are in linear space (0..1)
    - prev_lin: tuple of previous linear means (for gaming temporal boost), or None
    """
    cap_w = get_tunable("CAPTURE_W", mode)
    cap_h = get_tunable("CAPTURE_H", mode)

    sw, sh = monitor["width"], monitor["height"]

    if mode == Modes.GAMING:
        # center 25% region
        left = int(sw * 0.375); top = int(sh * 0.375)
        right = int(sw * 0.625); bottom = int(sh * 0.625)
        region = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        img = sct.grab(region)
        img_np = np.array(img)[:, :, :3]   # BGRA -> BGR

        # coarse subsample: CAPTURE_W/H small (e.g. 16) => keeps reactiveness
        img_small = _subsample(img_np, cap_w, cap_h)

        # Normalize to [0..1], convert to linear
        img_norm = img_small.astype(np.float32) / 255.0
        # Note: channels in img_np are B, G, R
        r_lin_map = srgb_to_linear(img_norm[:, :, 2])
        g_lin_map = srgb_to_linear(img_norm[:, :, 1])
        b_lin_map = srgb_to_linear(img_norm[:, :, 0])

        # Mild center weighting to emphasize middle of crop (gaming focus)
        h, w = r_lin_map.shape
        yy, xx = np.ogrid[:h, :w]
        cx, cy = w // 2, h // 2
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        max_dist = np.sqrt(cx ** 2 + cy ** 2) if (cx or cy) else 1.0
        weights = 1.2 - (dist / max_dist)          # center ~1.2, edges lower
        weights = np.clip(weights, 0.0, None)

        # Weighted mean
        sum_w = weights.sum()
        r_lin = (r_lin_map * weights).sum() / sum_w
        g_lin = (g_lin_map * weights).sum() / sum_w
        b_lin = (b_lin_map * weights).sum() / sum_w

        # Temporal boost (make gaming more reactive): blend with prev_lin if provided
        # alpha closer to 1 => more reactive (favor new frame). tune in TWEAKS? we'll use a fixed reactive alpha.
        reactive_alpha = 0.75  # high -> more reactive; lower -> smoother
        if prev_lin is not None:
            pr, pg, pb = prev_lin
            r_lin = reactive_alpha * r_lin + (1 - reactive_alpha) * pr
            g_lin = reactive_alpha * g_lin + (1 - reactive_alpha) * pg
            b_lin = reactive_alpha * b_lin + (1 - reactive_alpha) * pb

    elif mode == Modes.MOVIE:
        # full-screen weighted radial average (center contributes more)
        img = sct.grab({"left": 0, "top": 0, "width": sw, "height": sh})
        img_np = np.array(img)[:, :, :3]
        img_small = _subsample(img_np, cap_w, cap_h)
        img_norm = img_small.astype(np.float32) / 255.0

        r_lin_map = srgb_to_linear(img_norm[:, :, 2])
        g_lin_map = srgb_to_linear(img_norm[:, :, 1])
        b_lin_map = srgb_to_linear(img_norm[:, :, 0])

        h, w = r_lin_map.shape
        yy, xx = np.ogrid[:h, :w]
        cx, cy = w // 2, h // 2
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        max_dist = np.sqrt(cx ** 2 + cy ** 2) if (cx or cy) else 1.0
        # stronger center weight for movie
        weights = 1.6 - (dist / max_dist)           # center ~1.6
        weights = np.clip(weights, 0.0, None)

        sum_w = weights.sum()
        r_lin = (r_lin_map * weights).sum() / sum_w
        g_lin = (g_lin_map * weights).sum() / sum_w
        b_lin = (b_lin_map * weights).sum() / sum_w

    else:  # ambient - flat full-screen average
        img = sct.grab({"left": 0, "top": 0, "width": sw, "height": sh})
        img_np = np.array(img)[:, :, :3]
        img_small = _subsample(img_np, cap_w, cap_h)
        img_norm = img_small.astype(np.float32) / 255.0

        r_lin = srgb_to_linear(img_norm[:, :, 2]).mean()
        g_lin = srgb_to_linear(img_norm[:, :, 1]).mean()
        b_lin = srgb_to_linear(img_norm[:, :, 0]).mean()

    # Return linear-space means and an approximate brightness (from linear->sRGB -> HSV later)
    return r_lin, g_lin, b_lin

# Simple EMA for integer smoothing (0..255)
def ema_int(prev, cur, alpha):
    return int(prev * alpha + cur * (1 - alpha))

def freq_to_color(frequencies, spectrum):
    low = np.mean(spectrum[(frequencies >= 20) & (frequencies < 250)])
    mid = np.mean(spectrum[(frequencies >= 250) & (frequencies < 2000)])
    high = np.mean(spectrum[(frequencies >= 2000) & (frequencies < 8000)])
    total = low + mid + high + 1e-6
    r = int((low / total) * 255)
    g = int((mid / total) * 255)
    b = int((high / total) * 255)
    return (r, g, b)

async def sound_mode_loop():
    if not _wizlight_available:
        print("pywizlight is not installed. Please install it for sound mode.")
        return
    bulb = wizlight(BULB_IP)
    await bulb.turn_on(PilotBuilder(brightness=200))
    loop = asyncio.get_running_loop()

    SAMPLE_RATE = 44100
    BLOCK_SIZE = 1024

    def audio_callback(indata, frames, time_, status):
        if status:
            print(status)
        spectrum = np.abs(np.fft.rfft(indata[:, 0]))
        frequencies = np.fft.rfftfreq(len(indata), 1 / SAMPLE_RATE)
        r, g, b = freq_to_color(frequencies, spectrum)
        loop.call_soon_threadsafe(asyncio.create_task, bulb.turn_on(PilotBuilder(rgb=(r, g, b))))

    with sd.InputStream(callback=audio_callback, channels=1, samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE):
        print("Listening to system audio... Press Ctrl+C to stop.")
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            print("Stopped.")

# -------------------
# Main loop
# -------------------
def main(args):
    mode = args.mode
    if mode == Modes.SOUND:
        print("Starting Ambilight in sound mode. Ctrl+C to stop.")
        try:
            asyncio.run(sound_mode_loop())
        except KeyboardInterrupt:
            print("Stopped.")
        return

    # Shared state for other modes
    last_r = last_g = last_b = 0  # last sent 0..255 values (for EMA smoothing)
    last_lin = None                # last linear triple for gaming temporal boost

    print(f"Starting Ambilight in {mode} mode. Ctrl+C to stop.")
    try:
        while True:
            # Get linear-space averages (may use last_lin for gaming reactivity)
            r_lin, g_lin, b_lin = get_screen_linear_avg(mode, prev_lin=last_lin)

            # Save current linear for next iteration (used only for gaming)
            last_lin = (r_lin, g_lin, b_lin)

            # Convert to final RGB (0..255) and brightness v
            r8, g8, b8, v = postprocess_from_linear(r_lin, g_lin, b_lin, mode)

            # Final EMA smoothing on 0..255 values to reduce flicker
            if last_r == last_g == last_b == 0:
                sr, sg, sb = r8, g8, b8
            else:
                ema_alpha = get_tunable("EMA_ALPHA", mode)
                sr = ema_int(last_r, r8, ema_alpha)
                sg = ema_int(last_g, g8, ema_alpha)
                sb = ema_int(last_b, b8, ema_alpha)

            # Brightness mapping
            brightness = int(60 + 195 * v)
            if mode == Modes.GAMING:
                brightness = int(100 + 155 * v)

            # Send
            send_wiz_color(sr, sg, sb, brightness=brightness)

            # Update last
            last_r, last_g, last_b = sr, sg, sb

            # Sleep per-mode
            time.sleep(get_tunable("FRAME_DELAY_SEC", mode))
    except KeyboardInterrupt:
        print("Stopping Ambilight.")

# -------------------
# CLI and run
# -------------------
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=[Modes.AMBIENT, Modes.GAMING, Modes.MOVIE, Modes.SOUND],
                   default=Modes.GAMING, help="Operating mode")
    args = p.parse_args()
    main(args)
