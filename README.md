# Ambient Smart Bulb Sync 🎨💡

This project turns your **Philips WiZ smart bulb** into an **ambient light source** that syncs in real-time with your screen. It captures your display’s colors and brightness, processes them for natural and vivid lighting, and sends them to your bulb via UDP.

Currently supports **Philips WiZ bulbs**, tested on **Windows**, **macOS** and **Linux**.

---

## 🚀 Installation & Setup

### 1. Clone the repo

`git clone https://github.com/one-adnan/ambient-setup`  
`cd ambient-setup`

### 2. Install dependencies

Make sure you have Python **3.9+** installed. [Download Python](https://www.python.org/downloads/)  
`pip install -r requirements.txt`

### 3. Run the script

Simply run:  
`python ambient.py --mode gaming`  
Or on Mac/Linux:  
`python3 ambient.py --mode gaming`

Stop anytime with `ctrl + c`.

### 4. If script not able to discover bulb ip

- first just try running again, its hit and miss at the moment. will make this stable in future. If that does not work then follow below steps
- Open your router’s admin panel or use a network scanner.
- Look for your **Philips WiZ bulb’s IP address**.
- Replace it in the script:  
  `BULB_IP = "192.168.X.X"   # <-- set your smart bulb's IP`

---

## 🎮 Modes

- **Ambient** → Full-screen average color, smooth transitions. Best for casual desktop use and relaxed mood lighting.  
  `python ambient.py --mode ambient`
- **Gaming** → Focuses on the **center of the screen** for more reactive colors. High FPS (~30 fps) and lower smoothing for faster response.  
  `python ambient.py --mode gaming`
- **Movie** → Weighted average, center pixels contribute more. Keeps the mood natural with slight gamma correction.  
  `python ambient.py --mode movie`

---

## ⚙️ Tweaks

All tunables are defined at the top of the script. You can adjust them for your setup:

- `CAPTURE_W`, `CAPTURE_H` → downscale resolution for speed.
- `FRAME_DELAY_SEC` → lower = faster updates, higher = smoother.
- `SAT_BOOST` → increases color vibrancy.
- `EMA_ALPHA` → smoothing factor (0 = instant, 1 = slow fade).
- `GAIN_R/G/B` → correct color casts if your bulb looks off.
- `HUE_BOOST_RANGE` & `HUE_RANGE_SAT_MULT` → extra boost for green/yellow hues where bulbs often look dull.

Each **mode** can override defaults in the `TWEAKS` section and better to tweak in this section rather than global.

---

## ✅ Supported Platforms

- ✔️ Windows
- ✔️ macOS
- ✔️ Linux

---

## 📖 Detailed Description

- Captures a screenshot of your display at high frequency.
- Downscales and averages pixel colors for efficiency.
- Converts colors into **linear RGB → HSV tweaks → sRGB**.
- Applies **saturation boost, gamma correction, and per-channel gain**.
- Uses **EMA smoothing** to reduce flicker while staying responsive.
- Sends optimized **UDP packets** directly to your WiZ bulb with the updated color and brightness.

Effectively, your bulb **mimics the mood of your screen**, whether you’re browsing, gaming, or watching movies.

---

💡 Enjoy immersive lighting that reacts to your screen in real-time!

