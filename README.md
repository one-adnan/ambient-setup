# Ambient Smart Bulb Sync 🎨💡

This project turns your **Philips WiZ smart bulbs** (one or several) into an **ambient light source** that syncs in real-time with your screen. It captures your display’s colors and brightness, processes them for natural and vivid lighting, and sends them to your bulbs via UDP. Everything stays on your local network.

Currently supports **Philips WiZ bulbs**, tested on **Windows**, **macOS** and **Linux**.

---

## ⬇️ Download (no Python needed)

Grab the latest version from the **[Releases page](https://github.com/one-adnan/ambient-setup/releases/latest)**:

- **Windows**: `AmbientLightSync-Windows.exe`, just double-click it
- **macOS**: `AmbientLightSync-macOS.zip`, unzip and right-click → Open the first time
- **Linux**: `AmbientLightSync-Linux.tar.gz`, extract and run `./AmbientLightSync`
- **Have Python?** `AmbientLightSync-Python.zip` contains the source and the double-click `Ambient Light.pyw` launcher

The app is unsigned, so Windows may show "Windows protected your PC". Click **More info → Run anyway**.

---

## 🚀 Installation & Setup (from source)

### 1. Clone the repo

`git clone https://github.com/one-adnan/ambient-setup`  
`cd ambient-setup`

### 2. Install dependencies

Make sure you have Python **3.9+** installed. [Download Python](https://www.python.org/downloads/)  
`pip install -r requirements.txt`

### 3. Open the app (easiest)

`python app.py` (or `python3 app.py` on Mac/Linux)

On Windows you can also just double-click **`Ambient Light.pyw`** (no console window).

The app walks you through three steps:

1. **Your bulbs**: bulbs are found automatically. Click **Identify** to flash a bulb green, then pick which part of the screen it should follow (whole screen, left half, right half, a corner...).
2. **Choose a preset**: each preset has a short description, hidden **tips**, and optional **fine-tune** sliders (brightness, colour intensity, smoothness, screen area, dark-scene cutoff, red correction, which screen).
3. **Start**: the dots next to each bulb show the colour it's getting live. Everything you choose is remembered.

> Linux: if the app doesn't open, install Tk: `sudo apt install python3-tk`

### 4. Or use the command line

`python ambient.py --mode movie`

Stop anytime with `ctrl + c`. On the first run with several bulbs, a short wizard lights each bulb **green** and asks where it sits.

- Redo the bulb setup: `python ambient.py --setup`
- Skip discovery: `python ambient.py --bulb 192.168.1.20:left --bulb 192.168.1.21:right`
- List bulbs on your network: `python discover.py`
- Capture a different monitor: `python ambient.py --monitor 2`

Positions: `full`, `left`, `right`, `top`, `bottom`, `top-left`, `top-right`, `bottom-left`, `bottom-right`, `center`, `off`.  
Custom areas: in `bulbs.json`, replace `"position"` with `"region": [x0, y0, x1, y1]` (fractions of the screen, e.g. `[0, 0, 0.33, 1]` for the left third).

Bulbs are saved in `bulbs.json` by MAC address, so your setup survives the router giving a bulb a new IP. If no bulb is found, check the computer and bulbs are on the same network, or pass the IP from your router's admin page with `--bulb`.

### 5. Publishing a release / building the app yourself

Releases are built automatically: push a version tag and GitHub Actions builds Windows, macOS and Linux apps plus a Python zip, and attaches them to a new release.

```
git tag v1.0.0
git push origin v1.0.0
```

To build locally instead:

```
pip install pyinstaller
pyinstaller --onefile --windowed --name AmbientLightSync app.py
```

The app appears in `dist/` (`AmbientLightSync.exe` on Windows). It stores `bulbs.json`/`settings.json` next to itself. Build on each OS you want to support.

---

## 🎮 Presets

| Preset | Best for | What it does |
|---|---|---|
| `ambient` | Desktop, browsing | Whole-screen average, soft transitions |
| `movie` | Movies & TV | Ignores black bars, favours the centre, dark scenes fade to a dim warm glow |
| `gaming` | Most games | ~30 updates/s from the centre 25% of the screen, very reactive |
| `gaming-wide` | Open-world, racing, left/right bulbs | Fast like gaming, but samples 70% of the screen |
| `vivid` | Music videos, anime, parties | Punchy saturated colours from the most colourful parts of the screen |
| `relax` | Reading, late night | Dim (max 50%), slow and gentle |

Command line: `python ambient.py --mode <preset>`.

---

## ⚙️ Tweaks

The easiest way is the **Fine-tune** section in the app (saved per preset in `settings.json`).  
For full control, edit `DEFAULTS` and `PRESETS` at the top of `ambient.py`:

- `CAPTURE_W`, `CAPTURE_H` → downscale resolution for speed.
- `FRAME_DELAY_SEC` → lower = faster updates.
- `EMA_ALPHA` → smoothing (0 = instant, 0.95 = very slow fades).
- `SAT_BOOST` → colour vibrancy.
- `FOCUS` → centered fraction of the screen to sample (gaming uses `0.25`; raise it for better colour accuracy or more left/right difference).
- `CENTER_WEIGHT` → how much more the middle of the area counts (0 = flat average).
- `COLOR_WEIGHTING` → 0 = plain average, 1 = colour taken from bright/vivid pixels (a red lamp in a dark room stays red instead of turning murky).
- `DARK_LEVEL` / `DARK_COLOR` → below this colour brightness, bulbs fade to a warm neutral glow instead of a dark tint.
- `MIN_BRIGHTNESS` / `MAX_BRIGHTNESS` / `BRIGHTNESS_CURVE` → maps screen brightness to WiZ dimming (10–100).
- `GAIN_R/G/B` → correct colour casts. Applied to saturated colours only, so greys and whites stay neutral.
- `HUE_BOOST_RANGE` & `HUE_RANGE_SAT_MULT` → extra boost for green/yellow hues where bulbs often look dull.
- `LETTERBOX_CROP` → ignore black bars around movies.

---

## ✅ Supported Platforms

- ✔️ Windows
- ✔️ macOS (allow Screen Recording permission for Terminal/Python when asked)
- ✔️ Linux

---

## 📖 How it works

- Grabs a small, low-resolution snapshot of your screen many times per second (nothing is saved).
- Optionally crops black bars, then works in **linear RGB** for correct colour averaging.
- For each bulb, takes its part of the screen and computes:
  - a **colour** weighted toward vivid, bright pixels (and the centre, depending on preset),
  - a **brightness** from the area's real luminance.
- Applies saturation boost and per-channel gain, and fades very dark scenes to a dim warm glow.
- Uses **EMA smoothing** to reduce flicker while staying responsive.
- Sends **UDP packets** directly to each WiZ bulb. WiZ treats r/g/b as a colour mix and `dimming` (10–100) as brightness.

Discovery broadcasts from every network adapter, keeps retrying, and falls back to scanning the subnet directly, so bulbs are found reliably even on PCs with VPN/WSL/Hyper-V adapters.

---

💡 Enjoy immersive lighting that reacts to your screen in real-time!
