# this is older script with only windows and mac support.
# run the new mss one for better results on all platforms
import socket, json, time
from PIL import ImageGrab, Image
import colorsys

BULB_IP = "192.168.1.4"   # <-- set your smart bulb's IP
PORT = 38899 

# -------------------
# Modes
# -------------------
class Modes:
    AMBIENT = "ambient"
    GAMING = "gaming"
    MOVIE = "movie"

# -------------------
# Global Tunables (defaults), for tweaking its better to modify below in Overrides
# -------------------
CAPTURE_W, CAPTURE_H = 60, 34     # downscale for speed
FRAME_DELAY_SEC = 0.08            # ~12.5 fps
SAT_BOOST = 1.2                  # gentle saturation lift
EMA_ALPHA = 0.65                  # 0..1 ; higher = smoother/slower

# Optional extra lift for yellow/green where bulbs often look dull
HUE_BOOST_RANGE = (0.12, 0.45)    # ~43°..162°
HUE_RANGE_SAT_MULT = 1.12

# Per-channel gain to fix color casts (e.g. red → pink correction)
GAIN_R, GAIN_G, GAIN_B = 1.1, 1.0, 1.05

# -------------------
# Overrides (tweak here)
# -------------------
TWEAKS = {
    Modes.AMBIENT: {
        "FRAME_DELAY_SEC": 0.08,
        "EMA_ALPHA": 0.65,
    },
    Modes.GAMING: {
        "FRAME_DELAY_SEC": 0.03, # ~30 fps
        "EMA_ALPHA": 0.30,   # more reactive
        "CAPTURE_W": 40,     # focus smaller area for responsiveness
        "CAPTURE_H": 22,
    },
    Modes.MOVIE: {
        "FRAME_DELAY_SEC": 0.08,
        "EMA_ALPHA": 0.65,   # smoother like ambient
        "SAT_BOOST": 1.1,    # slightly toned down for natural colors
    },
}

# -------------------
# Active mode selection
# -------------------
MODE = Modes.MOVIE

def get_tunable(name):
    """Get effective value for current mode, falling back to global."""
    return TWEAKS.get(MODE, {}).get(name, globals()[name])


def send_wiz_color(r, g, b, brightness=255):
    msg = {"method":"setState","id":1,
           "params":{"state":True,"r":int(r),"g":int(g),"b":int(b),"dimming":int(brightness)}}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(json.dumps(msg).encode("utf-8"), (BULB_IP, PORT))
    finally:
        sock.close()

# sRGB <-> linear helpers (0..1)
def srgb_to_linear(c):
    return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055) ** 2.4

def linear_to_srgb(c):
    return 12.92*c if c <= 0.0031308 else 1.055*(c ** (1/2.4)) - 0.055

def get_screen_avg_rgb(mode=Modes.AMBIENT):
    cap_w = get_tunable("CAPTURE_W")
    cap_h = get_tunable("CAPTURE_H")
    if mode == Modes.GAMING:
        # Focus on center 25% patch only, more reactive
        # TODO: works perfect, need to test on cp2077 police siren lights reflection
        sw, sh = ImageGrab.grab().size
        left = int(sw*0.375); top = int(sh*0.375)
        right = int(sw*0.625); bottom = int(sh*0.625)
        region=(left, top, right, bottom)
        img = ImageGrab.grab(bbox=region).resize((cap_w, cap_h), Image.BILINEAR).convert("RGB")
        pixels = img.getdata()
        
        r_lin = g_lin = b_lin = 0.0
        n = 0
        for r, g, b in pixels:
            r_lin += srgb_to_linear(r/255.0)
            g_lin += srgb_to_linear(g/255.0)
            b_lin += srgb_to_linear(b/255.0)
            n += 1

        r_lin /= n; g_lin /= n; b_lin /= n

    elif mode == Modes.MOVIE:
        # Weighted average: center contributes more, edges less
        img = ImageGrab.grab().resize((cap_w, cap_h), Image.BILINEAR).convert("RGB")
        pixels = img.load()

        r_lin = g_lin = b_lin = 0.0
        total_weight = 0.0
        cx, cy = cap_w // 2, cap_h // 2
        max_dist = (cx**2 + cy**2) ** 0.5

        for y in range(cap_h):
            for x in range(cap_w):
                r, g, b = pixels[x, y]
                dx, dy = x - cx, y - cy
                dist = (dx*dx + dy*dy) ** 0.5
                w = 1.5 - (dist / max_dist)  # center ~1.5, edges ~0
                if w < 0: w = 0
                r_lin += srgb_to_linear(r/255.0) * w
                g_lin += srgb_to_linear(g/255.0) * w
                b_lin += srgb_to_linear(b/255.0) * w
                total_weight += w

        r_lin /= total_weight; g_lin /= total_weight; b_lin /= total_weight

    else:  # ambient (full-screen average)
        img = ImageGrab.grab().resize((cap_w, cap_h), Image.BILINEAR).convert("RGB")
        pixels = img.getdata()

        r_lin = g_lin = b_lin = 0.0
        n = 0
        for r, g, b in pixels:
            r_lin += srgb_to_linear(r/255.0)
            g_lin += srgb_to_linear(g/255.0)
            b_lin += srgb_to_linear(b/255.0)
            n += 1
        r_lin /= n; g_lin /= n; b_lin /= n

    # Back to sRGB
    r = max(0.0, min(1.0, linear_to_srgb(r_lin)))
    g = max(0.0, min(1.0, linear_to_srgb(g_lin)))
    b = max(0.0, min(1.0, linear_to_srgb(b_lin)))

    # HSV tweak: saturation + optional hue range boost
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s *= get_tunable("SAT_BOOST")
    hue_boost_range = get_tunable("HUE_BOOST_RANGE")
    hue_range_sat_mult = get_tunable("HUE_RANGE_SAT_MULT")
    if hue_boost_range[0] <= h <= hue_boost_range[1]:
        s *= hue_range_sat_mult
    s = max(0.0, min(1.0, s))

    # For movie mode: slight gamma adjust to preserve color mood
    if mode == Modes.MOVIE:
        v = v ** 0.9

    r, g, b = colorsys.hsv_to_rgb(h, s, v)

    # Apply per-channel gain
    r *= get_tunable("GAIN_R")
    g *= get_tunable("GAIN_G")
    b *= get_tunable("GAIN_B")

    # Clip to [0..1]
    r = max(0.0, min(1.0, r))
    g = max(0.0, min(1.0, g))
    b = max(0.0, min(1.0, b))

    return int(r*255), int(g*255), int(b*255), v

def ema(prev, cur, alpha):
    return int(prev*alpha + cur*(1-alpha))

print(f"Starting Ambilight in {MODE} mode. Ctrl+C to stop.")
last_r = last_g = last_b = 0
try:
    while True:
        r, g, b, v = get_screen_avg_rgb(MODE)

        # Smooth to reduce flicker
        if last_r == last_g == last_b == 0:
            sr, sg, sb = r, g, b
        else:
            ema_alpha = get_tunable("EMA_ALPHA")
            sr = ema(last_r, r, ema_alpha)
            sg = ema(last_g, g, ema_alpha)
            sb = ema(last_b, b, ema_alpha)

        # Map brightness from screen value; keep some floor so colors stay visible
        brightness = int(60 + 195 * v)  # 60..255
        if MODE==Modes.GAMING:
            brightness = int(100 + 155 * v)  # more aggressive brightness


        send_wiz_color(sr, sg, sb, brightness=brightness)
        last_r, last_g, last_b = sr, sg, sb
        time.sleep(get_tunable("FRAME_DELAY_SEC"))
except KeyboardInterrupt:
    pass
