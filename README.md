# Ambient Smart Bulb Sync 🎨💡

This project turns your **Philips WiZ smart bulb** into an **ambient light source** that syncs in real-time with your screen. It captures your display’s colors and brightness, processes them for natural and vivid lighting, and sends them to your bulb via UDP.  

Currently supports **Philips WiZ bulbs**, tested on **Windows** and **macOS (M1)**. Linux support will be added soon.

---

## 🚀 Installation & Setup

### 1. Clone the repo
`git clone https://github.com/one-adnan/ambient-setup`  
`cd ambient-setup`

### 2. Install dependencies
Make sure you have Python **3.9+** installed.  
`pip install -r requirements.txt`

### 3. Find your bulb’s IP
- Open your router’s admin panel or use a network scanner.  
- Look for your **Philips WiZ bulb’s IP address**.  
- Replace it in the script:  
`BULB_IP = "192.168.X.X"   # <-- set your smart bulb's IP`

---

## 🎮 Modes

Choose the mode by editing:  
`MODE = Modes.GAMING   # or Modes.AMBIENT / Modes.MOVIE`  

- **Ambient** → Full-screen average color, smooth transitions. Best for casual desktop use and relaxed mood lighting.  
- **Gaming** → Focuses on the **center of the screen** for more reactive colors. High FPS (~30 fps) and lower smoothing for faster response.  
- **Movie** → Weighted average, center pixels contribute more. Keeps the mood natural with slight gamma correction.  

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

## ▶️ Running

Simply run:  
`python ambient.py`  
Or on Mac/Linux:  
`python3 ambient.py`  

Stop anytime with `Ctrl+C`.

---

## ✅ Current Support

- ✔️ Philips WiZ bulbs (tested with multiple models)  
- ✔️ Windows 10/11  
- ✔️ macOS (M1, Intel not tested but should work)  
- ❌ Linux (coming soon)  

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

