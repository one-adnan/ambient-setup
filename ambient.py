"""
Ambilight for WiZ bulbs (mss + numpy) - preset-based, multi-bulb, cross-platform (windows, mac & linux).

Usage:
    python app.py                         # simple desktop app (recommended)
    python ambient.py                     # command line: saved setup -> discovery -> setup wizard
    python ambient.py --mode movie        # pick a preset (see PRESETS below)
    python ambient.py --setup             # re-discover bulbs and choose their screen positions
    python ambient.py --bulb 192.168.1.20:left --bulb 192.168.1.21:right   # skip discovery
"""

import argparse
import colorsys
import json
import os
import socket
import sys
import threading
import time
from functools import lru_cache

import mss
import numpy as np
import discover

# -------------------
# Files
# -------------------
if getattr(sys, "frozen", False):          # packaged app (PyInstaller): keep files next to the .exe
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "bulbs.json")       # bulbs + their positions
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")  # last preset, monitor, your fine-tuning

# Optional manual override for the command line (skips discovery), e.g.
# MANUAL_BULBS = [("192.168.1.20", "left"), ("192.168.1.21", "right")]
MANUAL_BULBS = []

# -------------------
# Networking / bulbs
# -------------------
PORT = 38899
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def _send(ip, params):
    msg = {"method": "setState", "id": 1, "params": params}
    try:
        _sock.sendto(json.dumps(msg).encode("utf-8"), (ip, PORT))
    except OSError:
        pass

def send_wiz_color(ip, r, g, b, dimming=100):
    """WiZ uses r/g/b as a colour *mix*; brightness comes only from dimming (10..100)."""
    dimming = max(10, min(100, int(round(dimming))))
    _send(ip, {"state": True, "r": int(r), "g": int(g), "b": int(b), "dimming": dimming})

def send_wiz_off(ip):
    _send(ip, {"state": False})

def identify_bulb(ip, all_ips=()):
    """Light one bulb green and switch the others off, so the user can tell which is which."""
    for _ in range(3):  # UDP can drop packets; repeat
        for other in all_ips:
            if other != ip:
                send_wiz_off(other)
        send_wiz_color(ip, 0, 255, 0, 100)
        time.sleep(0.05)

# Screen regions as fractions of the screen: (x0, y0, x1, y1). "off" = don't use the bulb.
POSITIONS = {
    "full":         (0.0, 0.0, 1.0, 1.0),
    "left":         (0.0, 0.0, 0.5, 1.0),
    "right":        (0.5, 0.0, 1.0, 1.0),
    "top":          (0.0, 0.0, 1.0, 0.5),
    "bottom":       (0.0, 0.5, 1.0, 1.0),
    "top-left":     (0.0, 0.0, 0.5, 0.5),
    "top-right":    (0.5, 0.0, 1.0, 0.5),
    "bottom-left":  (0.0, 0.5, 0.5, 1.0),
    "bottom-right": (0.5, 0.5, 1.0, 1.0),
    "center":       (0.25, 0.25, 0.75, 0.75),
    "off":          None,
}

# -------------------
# Tunables & presets
# -------------------
# Defaults for every preset. Presets below override some of these.
DEFAULTS = {
    "CAPTURE_W": 60, "CAPTURE_H": 34,  # downscale grid (smaller = faster, coarser)
    "FRAME_DELAY_SEC": 0.08,           # time per update (0.08 = ~12 fps)
    "EMA_ALPHA": 0.65,                 # smoothing: 0 = instant, 0.95 = very slow fades
    "SAT_BOOST": 1.2,                  # colour intensity
    "HUE_BOOST_RANGE": (0.12, 0.45),   # green/yellow hues look dull on bulbs...
    "HUE_RANGE_SAT_MULT": 1.12,        # ...so they get this extra saturation
    "GAIN_R": 1.2, "GAIN_G": 1.0, "GAIN_B": 1.05,  # per-channel correction, applied to
                                                    # saturated colours only (greys stay neutral)
    "FOCUS": 1.0,                      # centered fraction of the screen to sample (1 = whole screen)
    "CENTER_WEIGHT": 0.0,              # 0 = flat average; higher = middle of the area counts more
    "COLOR_WEIGHTING": 0.6,            # 0 = plain average; 1 = colour comes from bright/vivid pixels
    "REACTIVE_ALPHA": 1.0,             # <1 blends with the previous frame before smoothing (gaming)
    "MIN_BRIGHTNESS": 10,              # WiZ dimming range is 10..100
    "MAX_BRIGHTNESS": 100,
    "BRIGHTNESS_CURVE": 0.8,           # <1 = brighter mid-tones, >1 = darker
    "DARK_LEVEL": 0.08,                # below this colour brightness, fade to DARK_COLOR (0 = off)
    "DARK_COLOR": (255, 150, 80),      # neutral warm glow used for dark scenes
    "LETTERBOX_CROP": False,           # ignore black bars around movies
}

PRESETS = {
    "ambient": {
        "label": "Ambient (desktop & browsing)",
        "description": "Whole-screen average with soft transitions. Relaxed mood lighting while you work or browse.",
        "tips": [
            "Lots of white web pages make the bulbs bright white. Lower 'Max brightness' if that's too much.",
            "Increase 'Smoothness' for calmer, slower colour changes.",
        ],
        "settings": {},
    },
    "movie": {
        "label": "Movie & TV",
        "description": "Follows the picture, ignores black bars, and gives the middle of the screen more weight. "
                       "Dark scenes fade to a dim warm glow instead of a coloured tint.",
        "tips": [
            "Use the player in fullscreen so menus and the taskbar don't affect the colour.",
            "Dark scenes too bright or tinted? Raise 'Dark-scene cutoff'. Bulbs dim out too often? Lower it.",
            "Colours too strong? Lower 'Colour intensity' to around 1.0.",
            "With two bulbs on the left and right, wide shots split nicely. Keep 'Screen area used' at 100%.",
        ],
        "settings": {
            "CAPTURE_W": 48, "CAPTURE_H": 28,
            "SAT_BOOST": 1.1,
            "CENTER_WEIGHT": 1.7,
            "COLOR_WEIGHTING": 0.75,
            "BRIGHTNESS_CURVE": 0.9,
            "DARK_LEVEL": 0.12,
            "LETTERBOX_CROP": True,
        },
    },
    "gaming": {
        "label": "Gaming (fast, centre focus)",
        "description": "Fast updates sampled from the centre of the screen, where the action is. "
                       "Ignores HUD elements at the edges.",
        "tips": [
            "Colours not matching the game? Increase 'Screen area used' (e.g. 40-60%) for better colour accuracy.",
            "With left/right bulbs, the split happens inside the centre box. If both bulbs look the same, "
            "increase 'Screen area used' or try the 'Gaming (wide)' preset.",
            "Flickering in fast scenes? Raise 'Smoothness' a little (0.4-0.5).",
            "Use borderless/windowed fullscreen. Some exclusive-fullscreen games block screen capture.",
        ],
        "settings": {
            "CAPTURE_W": 16, "CAPTURE_H": 16,
            "FRAME_DELAY_SEC": 0.03,
            "EMA_ALPHA": 0.30,
            "SAT_BOOST": 1.1,
            "FOCUS": 0.25,
            "CENTER_WEIGHT": 5.0,
            "COLOR_WEIGHTING": 0.5,
            "REACTIVE_ALPHA": 0.75,
            "MIN_BRIGHTNESS": 30,
            "DARK_LEVEL": 0.06,
        },
    },
    "gaming-wide": {
        "label": "Gaming (wide, multi-bulb)",
        "description": "Fast like Gaming, but samples most of the screen. Best for open-world games, "
                       "racing, and setups with left/right bulbs.",
        "tips": [
            "HUD or minimap colours leaking into the light? Lower 'Screen area used' a bit (e.g. 50%).",
            "Pairs well with one bulb on each side of the screen.",
        ],
        "settings": {
            "CAPTURE_W": 32, "CAPTURE_H": 20,
            "FRAME_DELAY_SEC": 0.03,
            "EMA_ALPHA": 0.35,
            "SAT_BOOST": 1.15,
            "FOCUS": 0.7,
            "CENTER_WEIGHT": 1.5,
            "COLOR_WEIGHTING": 0.6,
            "REACTIVE_ALPHA": 0.75,
            "MIN_BRIGHTNESS": 25,
            "DARK_LEVEL": 0.06,
        },
    },
    "vivid": {
        "label": "Vivid (music videos, anime, party)",
        "description": "Punchy, saturated colours taken from the most colourful parts of the screen. "
                       "Quick to react.",
        "tips": [
            "Great with colourful content, but can feel intense for regular TV.",
            "Lower 'Smoothness' even more for a beat-like, snappy effect.",
        ],
        "settings": {
            "FRAME_DELAY_SEC": 0.05,
            "EMA_ALPHA": 0.4,
            "SAT_BOOST": 1.5,
            "COLOR_WEIGHTING": 0.9,
            "BRIGHTNESS_CURVE": 0.7,
            "DARK_LEVEL": 0.1,
        },
    },
    "relax": {
        "label": "Relax (dim & slow)",
        "description": "Dim, gentle and very slow. Background light that follows the screen's mood "
                       "without drawing attention.",
        "tips": [
            "Good for reading, late-night browsing or sleepy shows.",
            "Raise 'Max brightness' if the room feels too dark.",
        ],
        "settings": {
            "FRAME_DELAY_SEC": 0.1,
            "EMA_ALPHA": 0.92,
            "SAT_BOOST": 0.95,
            "COLOR_WEIGHTING": 0.4,
            "MAX_BRIGHTNESS": 50,
            "DARK_LEVEL": 0.1,
        },
    },
}
DEFAULT_PRESET = "gaming"

def preset_settings(preset, overrides=None):
    """DEFAULTS <- preset settings <- user overrides."""
    s = dict(DEFAULTS)
    s.update(PRESETS[preset]["settings"])
    if overrides:
        s.update({k: v for k, v in overrides.items() if k in DEFAULTS})
    return s

# -------------------
# Colour helpers
# -------------------
LUMA = np.array([0.2126, 0.7152, 0.0722])

def srgb_to_linear(c):
    c = np.asarray(c)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def linear_to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * (c ** (1 / 2.4)) - 0.055)

def _smoothstep(e0, e1, x):
    if e1 <= e0:
        return 1.0 if x >= e1 else 0.0
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)

def finalize_color(color_lin, lum_lin, p):
    """
    Linear colour + linear luminance -> (r, g, b) bulb colour mix (0..255) and dimming (10..100).
    - Colour is normalised (bulbs take r/g/b as a mix, not as brightness).
    - Brightness is driven separately by the area's real luminance.
    - Dark colours fade to a warm neutral glow, so near-black never turns into a random tint.
    """
    r, g, b = (float(x) for x in np.clip(linear_to_srgb(color_lin), 0.0, 1.0))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    s *= p["SAT_BOOST"]
    lo, hi = p["HUE_BOOST_RANGE"]
    if lo <= h <= hi:
        s *= p["HUE_RANGE_SAT_MULT"]
    s = max(0.0, min(1.0, s))

    r, g, b = colorsys.hsv_to_rgb(h, s, 1.0)
    # Channel gains only for saturated colours, so greys/whites stay neutral
    r *= 1 + (p["GAIN_R"] - 1) * s
    g *= 1 + (p["GAIN_G"] - 1) * s
    b *= 1 + (p["GAIN_B"] - 1) * s
    m = max(r, g, b) or 1.0
    rgb = np.array([r, g, b]) / m * 255.0

    dark = p["DARK_LEVEL"]
    if dark > 0:
        # narrow band: blending warm with e.g. blue gives pink, so keep the crossfade short
        t = _smoothstep(dark * 0.8, dark * 1.2, v)
        rgb = np.array(p["DARK_COLOR"], dtype=np.float64) * (1 - t) + rgb * t

    bright = float(linear_to_srgb(lum_lin)) ** p["BRIGHTNESS_CURVE"]
    lo_b = max(10, p["MIN_BRIGHTNESS"])
    hi_b = max(lo_b, min(100, p["MAX_BRIGHTNESS"]))
    dimming = lo_b + (hi_b - lo_b) * min(1.0, bright)
    return rgb, dimming

# -------------------
# Capture & analysis (mss + numpy)
# -------------------
def _subsample(img_np, target_w, target_h):
    h, w = img_np.shape[:2]
    return img_np[::max(1, h // target_h), ::max(1, w // target_w)]

def capture_linear(sct, monitor, p):
    """Grab the (centered FOCUS part of the) screen; returns an HxWx3 linear-RGB array."""
    sw, sh = monitor["width"], monitor["height"]
    focus = min(1.0, max(0.05, float(p["FOCUS"])))
    w, h = max(1, int(sw * focus)), max(1, int(sh * focus))
    area = {"left": monitor["left"] + (sw - w) // 2, "top": monitor["top"] + (sh - h) // 2,
            "width": w, "height": h}
    img_np = np.asarray(sct.grab(area))[:, :, :3]                 # BGRA -> BGR
    small = _subsample(img_np, int(p["CAPTURE_W"]), int(p["CAPTURE_H"]))
    return srgb_to_linear(small[:, :, ::-1].astype(np.float32) / 255.0)   # -> RGB, linear

def crop_black_bars(lin, max_frac=0.25):
    """Remove letterbox/pillarbox bars: edge rows/cols that are (almost) entirely black."""
    h, w = lin.shape[:2]
    lit = lin.max(axis=2) > 0.006                # brighter than ~sRGB 20/255
    row_dark = lit.mean(axis=1) < 0.05           # tolerate a few lit pixels (logos, noise)
    col_dark = lit.mean(axis=0) < 0.05
    if row_dark.all():
        return lin                               # fully black frame: nothing to crop

    def run(flags, limit):
        n = 0
        while n < limit and flags[n]:
            n += 1
        return n

    top, bottom = run(row_dark, int(h * max_frac)), run(row_dark[::-1], int(h * max_frac))
    left, right = run(col_dark, int(w * max_frac)), run(col_dark[::-1], int(w * max_frac))
    return lin[top:h - bottom, left:w - right]

@lru_cache(maxsize=16)
def _radial_weights(h, w, center_weight):
    """1 at the corners, rising to 1 + center_weight in the middle."""
    yy, xx = np.ogrid[:h, :w]
    cx, cy = (w - 1) / 2, (h - 1) / 2
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    max_dist = np.sqrt(cx ** 2 + cy ** 2) or 1.0
    return 1.0 + center_weight * (1.0 - dist / max_dist)

def _vivid_weights(lin, strength):
    """Weights favouring bright, saturated pixels so the colour comes from what's actually colourful."""
    if strength <= 0:
        return 1.0
    mx = lin.max(axis=2)
    mn = lin.min(axis=2)
    sat = (mx - mn) / (mx + 1e-6)
    vivid = np.sqrt(mx) * (0.2 + sat)
    vivid = vivid / (vivid.mean() + 1e-6)
    return (1 - strength) + strength * vivid

def _region_slices(h, w, region):
    x0, y0, x1, y1 = region
    c0 = min(int(x0 * w), w - 1); c1 = max(c0 + 1, int(round(x1 * w)))
    r0 = min(int(y0 * h), h - 1); r1 = max(r0 + 1, int(round(y1 * h)))
    return slice(r0, r1), slice(c0, c1)

def region_for(bulb):
    if "region" in bulb:
        return tuple(float(v) for v in bulb["region"])
    return POSITIONS.get(bulb.get("position", "full"), POSITIONS["full"])

# -------------------
# Engine (used by both the CLI and the app)
# -------------------
class Engine:
    """
    Runs the capture -> colour -> bulbs loop. Preset, overrides and bulbs can be changed live
    (just assign the attributes) while run() is going in another thread.
    on_frame(list of (ip, (r, g, b), dimming)) is called after every update.
    """

    def __init__(self, bulbs, preset=DEFAULT_PRESET, overrides=None, monitor=1, on_frame=None):
        self.bulbs = list(bulbs)
        self.preset = preset
        self.overrides = dict(overrides or {})
        self.monitor = monitor
        self.on_frame = on_frame
        self._stop = threading.Event()
        self._state = {}   # ip -> per-bulb smoothing state

    def stop(self):
        self._stop.set()

    def run(self):
        with mss.mss() as sct:   # mss must be created in the thread that uses it
            if not 1 <= self.monitor < len(sct.monitors):
                raise ValueError(f"Monitor {self.monitor} not found (available: 1..{len(sct.monitors) - 1}).")
            monitor = sct.monitors[self.monitor]
            while not self._stop.is_set():
                started = time.monotonic()
                p = preset_settings(self.preset, self.overrides)
                frame = self._update(sct, monitor, p)
                if self.on_frame:
                    self.on_frame(frame)
                self._stop.wait(max(0.0, p["FRAME_DELAY_SEC"] - (time.monotonic() - started)))

    def _update(self, sct, monitor, p):
        lin = capture_linear(sct, monitor, p)
        if p["LETTERBOX_CROP"]:
            lin = crop_black_bars(lin)
        h, w = lin.shape[:2]

        cw = float(p["CENTER_WEIGHT"])
        base = _radial_weights(h, w, cw) if cw > 0 else np.ones((h, w))
        lum = lin @ LUMA
        color_w = base * _vivid_weights(lin, float(p["COLOR_WEIGHTING"]))

        results = []
        for bulb in list(self.bulbs):
            region = region_for(bulb)
            if region is None:   # position "off"
                continue
            rows, cols = _region_slices(h, w, region)

            bw = base[rows, cols]
            lum_mean = float((lum[rows, cols] * bw).sum() / bw.sum())
            wts = color_w[rows, cols]
            total = wts.sum()
            patch = lin[rows, cols]
            if total > 0:
                color = (patch * wts[..., None]).sum(axis=(0, 1)) / total
            else:
                color = patch.reshape(-1, 3).mean(axis=0)

            st = self._state.setdefault(bulb["ip"], {"lin": None, "out": None})
            ra = p["REACTIVE_ALPHA"]
            if ra < 1 and st["lin"] is not None:
                color = ra * color + (1 - ra) * st["lin"]
            st["lin"] = color

            rgb, dimming = finalize_color(color, lum_mean, p)
            target = np.array([rgb[0], rgb[1], rgb[2], dimming])
            a = p["EMA_ALPHA"]
            st["out"] = target if st["out"] is None else a * st["out"] + (1 - a) * target

            r, g, b, d = st["out"]
            send_wiz_color(bulb["ip"], round(r), round(g), round(b), d)
            results.append((bulb["ip"], (int(r), int(g), int(b)), int(round(d))))
        return results

# -------------------
# Config files
# -------------------
def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as e:
        print(f"Could not read {path} ({e}); ignoring it.")
        return None

def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_config():
    data = _read_json(CONFIG_PATH)
    return data.get("bulbs", []) if isinstance(data, dict) else None

def save_config(bulbs, quiet=False):
    clean = [{k: v for k, v in b.items() if not k.startswith("_")} for b in bulbs]
    _write_json(CONFIG_PATH, {"bulbs": clean})
    if not quiet:
        print(f"Saved bulb setup to {CONFIG_PATH}")

def load_settings():
    data = _read_json(SETTINGS_PATH)
    data = data if isinstance(data, dict) else {}
    data.setdefault("preset", DEFAULT_PRESET)
    if data["preset"] not in PRESETS:
        data["preset"] = DEFAULT_PRESET
    data.setdefault("monitor", 1)
    data.setdefault("overrides", {})
    return data

def save_settings(settings):
    _write_json(SETTINGS_PATH, settings)

# -------------------
# Bulb discovery & CLI setup wizard
# -------------------
def resolve_saved(saved, log=print):
    """Check saved bulbs still answer at their IP; re-discover by MAC if any moved."""
    answered = discover.probe([b["ip"] for b in saved])
    missing = [b for b in saved if b.get("mac", "").lower() not in answered]
    if missing:
        log(f"{len(missing)} saved bulb(s) did not answer at their last IP, re-discovering...")
        for d in discover.discover(expected=len(saved)):
            answered.setdefault(d["mac"], d)

    resolved, changed = [], False
    for b in saved:
        dev = answered.get(b.get("mac", "").lower())
        if dev:
            if dev["ip"] != b["ip"]:
                log(f"  bulb {b['mac']} moved {b['ip']} -> {dev['ip']}")
                b["ip"] = dev["ip"]
                changed = True
            resolved.append(b)
        else:
            log(f"  WARNING: bulb {b.get('mac')} ({b.get('position', 'full')}) not found, skipping it.")
    if changed:
        save_config(saved, quiet=True)
    return resolved

def merge_discovered(saved, devices):
    """Combine saved bulbs (keeping positions) with freshly discovered ones."""
    saved = saved or []
    by_mac = {b.get("mac", "").lower(): b for b in saved}
    defaults = {1: ["full"], 2: ["left", "right"]}.get(len(devices), ["full"] * len(devices))
    merged = []
    for i, d in enumerate(devices):
        b = by_mac.get(d["mac"])
        if b:
            b.update(ip=d["ip"], name=d.get("name", b.get("name", "")))
        else:
            b = {"mac": d["mac"], "ip": d["ip"], "name": d.get("name", ""), "position": defaults[i]}
        merged.append(b)
    return merged

def _parse_position(ans, default):
    names = list(POSITIONS)
    if ans == "":
        return default
    if ans in ("s", "skip"):
        return "off"
    if ans.isdigit() and 1 <= int(ans) <= len(names):
        return names[int(ans) - 1]
    return ans if ans in POSITIONS else None

def setup_wizard(devices):
    """Light up each bulb in turn and ask where it sits relative to the screen."""
    names = list(POSITIONS)
    bulbs = merge_discovered(load_config(), devices)
    print(f"\nPosition setup: {len(bulbs)} bulb(s). Each bulb will light up GREEN in turn.")
    print("Positions: " + "  ".join(f"{i}={n}" for i, n in enumerate(names, 1)) + "  s=skip")

    all_ips = [b["ip"] for b in bulbs]
    for i, b in enumerate(bulbs):
        identify_bulb(b["ip"], all_ips)
        default = b.get("position", "full")
        while True:
            prompt = f"[{i + 1}/{len(bulbs)}] Bulb {b['ip']} is GREEN. Where is it? [Enter={default}]: "
            try:
                choice = _parse_position(input(prompt).strip().lower(), default)
            except EOFError:
                choice = default
            if choice:
                break
            print("  Unknown position, enter a number or name from the list.")
        b["position"] = choice
        if choice == "off":
            send_wiz_off(b["ip"])

    save_config(bulbs)
    return bulbs

def parse_bulb_arg(s):
    ip, _, pos = s.partition(":")
    pos = pos or "full"
    if pos not in POSITIONS:
        raise argparse.ArgumentTypeError(f"unknown position '{pos}', choose from: {', '.join(POSITIONS)}")
    return {"ip": ip, "position": pos}

def get_bulbs(args):
    if args.bulb:
        return args.bulb
    if MANUAL_BULBS:
        return [{"ip": ip, "position": pos} for ip, pos in MANUAL_BULBS]

    saved = None if args.setup else load_config()
    if saved:
        return resolve_saved(saved)

    print("Searching for WiZ bulbs on the network...")
    devices = discover.discover(verbose=True)
    for d in devices:
        print(f"  found {d['ip']:<15} mac={d['mac']} {d['name']}")
    if not devices:
        return []
    if args.setup or (len(devices) > 1 and sys.stdin.isatty()):
        return setup_wizard(devices)
    bulbs = merge_discovered(None, devices)
    if len(devices) > 1:
        print("Multiple bulbs found; using left/right/full defaults. Run with --setup to change positions.")
    save_config(bulbs)
    return bulbs

# -------------------
# CLI
# -------------------
def main(args):
    settings = load_settings()
    preset = args.mode or settings["preset"]
    monitor = args.monitor or settings["monitor"]

    bulbs = [b for b in get_bulbs(args) if region_for(b) is not None]
    if not bulbs:
        print("No WiZ bulbs found. Make sure this computer and the bulbs are on the same network/Wi-Fi,\n"
              "then try again, or pass the IP directly: python ambient.py --bulb 192.168.X.X:full")
        sys.exit(1)

    print(f"Starting Ambilight with preset '{preset}' and {len(bulbs)} bulb(s):")
    for b in bulbs:
        print(f"  {b['ip']:<15} -> {'custom region' if 'region' in b else b.get('position', 'full')}")
    print("ctrl + c to stop.")

    engine = Engine(bulbs, preset, settings["overrides"].get(preset), monitor)
    try:
        engine.run()
    except KeyboardInterrupt:
        print("Stopping Ambilight.")
    except ValueError as e:
        print(e)
        sys.exit(1)

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Sync WiZ bulbs with your screen.")
    p.add_argument("--mode", choices=list(PRESETS), help="Preset to use (default: last used, or gaming)")
    p.add_argument("--setup", action="store_true",
                   help="Re-discover bulbs and choose each bulb's position relative to the screen")
    p.add_argument("--bulb", action="append", type=parse_bulb_arg, metavar="IP[:POSITION]",
                   help=f"Use this bulb (repeatable), skipping discovery. Positions: {', '.join(POSITIONS)}")
    p.add_argument("--monitor", type=int, help="Monitor number to capture (1 = primary)")
    main(p.parse_args())
