import socket, json, time
from PIL import ImageGrab, Image
import colorsys

BULB_IP = "192.168.X.X"   # <-- set your smart bulbs ip
PORT = 38899 # philips hue bulb

# Tunables
CAPTURE_W, CAPTURE_H = 60, 34     # downscale for speed
FRAME_DELAY_SEC = 0.08            # ~12.5 fps
SAT_BOOST = 1.2                  # gentle saturation lift
EMA_ALPHA = 0.65                  # 0..1 ; higher = smoother/slower

# Optional extra lift for yellow/green where bulbs often look dull
HUE_BOOST_RANGE = (0.12, 0.45)    # ~43°..162°
HUE_RANGE_SAT_MULT = 1.12

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

def get_screen_avg_rgb():
    img = ImageGrab.grab().resize((CAPTURE_W, CAPTURE_H), Image.BILINEAR).convert("RGB")
    pixels = img.getdata()

    # Average in linear-light
    r_lin = g_lin = b_lin = 0.0
    n = 0
    for r, g, b in pixels:
        r_lin += srgb_to_linear(r/255.0)
        g_lin += srgb_to_linear(g/255.0)
        b_lin += srgb_to_linear(b/255.0)
        n += 1

    r_lin /= n; g_lin /= n; b_lin /= n

    # Back to sRGB (0..1)
    r = max(0.0, min(1.0, linear_to_srgb(r_lin)))
    g = max(0.0, min(1.0, linear_to_srgb(g_lin)))
    b = max(0.0, min(1.0, min(1.0, linear_to_srgb(b_lin))))

    # HSV tweak: saturation boost (global + extra for yellow/green)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s *= SAT_BOOST
    if HUE_BOOST_RANGE[0] <= h <= HUE_BOOST_RANGE[1]:
        s *= HUE_RANGE_SAT_MULT
    s = max(0.0, min(1.0, s))

    r, g, b = colorsys.hsv_to_rgb(h, s, v)

    # Scale to 0..255 ints
    return int(r*255), int(g*255), int(b*255), v

def ema(prev, cur, alpha):
    return int(prev*alpha + cur*(1-alpha))

print("Starting Ambilight (gamma-correct + sat boost). Ctrl+C to stop.")
last_r = last_g = last_b = 0
try:
    while True:
        r, g, b, v = get_screen_avg_rgb()

        # Smooth to reduce flicker
        if last_r == last_g == last_b == 0:
            sr, sg, sb = r, g, b
        else:
            sr = ema(last_r, r, EMA_ALPHA)
            sg = ema(last_g, g, EMA_ALPHA)
            sb = ema(last_b, b, EMA_ALPHA)

        # Map brightness from screen value; keep some floor so colors stay visible
        brightness = int(60 + 195 * v)  # 60..255

        send_wiz_color(sr, sg, sb, brightness=brightness)
        last_r, last_g, last_b = sr, sg, sb
        time.sleep(FRAME_DELAY_SEC)
except KeyboardInterrupt:
    pass
