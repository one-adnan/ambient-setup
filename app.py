"""
Ambient Light Sync - a simple desktop app for syncing WiZ bulbs with your screen.

Run:   python app.py        (or double-click "Ambient Light.pyw" on Windows for no console window)
"""

import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import mss

import ambient
import discover

APP_TITLE = "Ambient Light Sync"
WRAP = 470

POSITION_LABELS = {
    "full": "Whole screen",
    "left": "Left half",
    "right": "Right half",
    "top": "Top half",
    "bottom": "Bottom half",
    "top-left": "Top-left quarter",
    "top-right": "Top-right quarter",
    "bottom-left": "Bottom-left quarter",
    "bottom-right": "Bottom-right quarter",
    "center": "Centre",
    "off": "Off (don't use)",
}
LABEL_TO_POSITION = {v: k for k, v in POSITION_LABELS.items()}

# (setting, label, min, max, value formatter, short help)
FINE_TUNE = [
    ("MAX_BRIGHTNESS", "Max brightness", 10, 100, lambda v: f"{v:.0f}%",
     "Upper limit for how bright the bulbs get."),
    ("SAT_BOOST", "Colour intensity", 0.6, 2.0, lambda v: f"{v:.2f}x",
     "Higher = more saturated colours."),
    ("EMA_ALPHA", "Smoothness", 0.0, 0.95, lambda v: f"{v:.2f}",
     "Higher = slower, softer changes. Lower = snappier."),
    ("FOCUS", "Screen area used", 0.15, 1.0, lambda v: f"{v * 100:.0f}%",
     "How much of the screen, measured from the centre, is sampled."),
    ("DARK_LEVEL", "Dark-scene cutoff", 0.0, 0.3, lambda v: "off" if v < 0.005 else f"{v:.2f}",
     "Below this, bulbs fade to a dim warm glow instead of a murky tint."),
    ("GAIN_R", "Red correction", 1.0, 1.8, lambda v: f"{v:.2f}x",
     "Boosts red in vivid colours if your bulbs look too cool."),
]

HOW_IT_WORKS = [
    "Several times a second, the app takes a tiny, low-resolution snapshot of your screen. "
    "Nothing is saved or uploaded.",
    "It works out the main colour and brightness for each bulb's part of the screen.",
    "The colour goes straight to your WiZ bulbs over your local Wi-Fi. No cloud or account needed.",
    "Your bulbs, positions and settings are remembered for next time.",
]


class Collapsible(ttk.Frame):
    """A clickable '▸ Title' header that shows/hides a body frame."""

    def __init__(self, parent, title, expanded=False, on_toggle=None):
        super().__init__(parent)
        self.title = title
        self.expanded = expanded
        self.on_toggle = on_toggle
        self.header = ttk.Label(self, style="Link.TLabel", cursor="hand2")
        self.header.pack(anchor="w")
        self.header.bind("<Button-1>", lambda _e: self.toggle())
        self.body = ttk.Frame(self, padding=(16, 2, 0, 6))
        self._sync()

    def toggle(self):
        self.expanded = not self.expanded
        self._sync()
        if self.on_toggle:
            self.on_toggle()

    def _sync(self):
        self.header.configure(text=("▾  " if self.expanded else "▸  ") + self.title)
        if self.expanded:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()


class App:
    def __init__(self, root):
        self.root = root
        self.settings = ambient.load_settings()
        self.bulbs = ambient.load_config() or []
        self.engine = None
        self.engine_thread = None
        self.engine_error = None
        self.latest_frame = None
        self.frame_times = []
        self.busy = False
        self._loading_sliders = False
        self._save_job = None
        self.bulb_rows = {}

        self._setup_style()
        self._build()
        self._load_preset_ui()
        self._refresh_bulb_rows()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(150, self._poll)

        if self.bulbs:
            self._check_saved_bulbs()
        else:
            self._find_bulbs()

    # ---------- look ----------
    def _setup_style(self):
        style = ttk.Style(self.root)
        if sys.platform.startswith("linux") and "clam" in style.theme_names():
            style.theme_use("clam")
        base = tkfont.nametofont("TkDefaultFont")
        family = base.actual("family")
        size = base.actual("size") or 10
        self.fonts = {
            "title": (family, size + 8, "bold"),
            "section": (family, size + 1, "bold"),
            "small": (family, max(size - 1, 8)),
            "button": (family, size + 2, "bold"),
        }
        style.configure("Title.TLabel", font=self.fonts["title"])
        style.configure("Sub.TLabel", foreground="#666666")
        style.configure("Hint.TLabel", foreground="#666666", font=self.fonts["small"])
        style.configure("Link.TLabel", foreground="#1a5fb4")
        style.configure("Section.TLabelframe.Label", font=self.fonts["section"])
        style.configure("Big.TButton", font=self.fonts["button"], padding=(12, 8))
        style.configure("Ok.TLabel", foreground="#2e7d32")
        style.configure("Bad.TLabel", foreground="#c62828")

    # ---------- layout ----------
    def _build(self):
        self.root.title(APP_TITLE)
        self.root.minsize(540, 300)
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Make your WiZ bulbs glow with the colours on your screen.",
                  style="Sub.TLabel").pack(anchor="w", pady=(0, 6))

        how = Collapsible(outer, "How it works", on_toggle=self._fit)
        how.pack(fill="x", pady=(0, 8))
        for line in HOW_IT_WORKS:
            ttk.Label(how.body, text="•  " + line, wraplength=WRAP, justify="left").pack(anchor="w", pady=1)

        # 1. Bulbs
        bulbs = ttk.LabelFrame(outer, text="1.  Your bulbs", padding=10, style="Section.TLabelframe")
        bulbs.pack(fill="x", pady=(0, 10))
        ttk.Label(bulbs, text="Click Identify to flash a bulb green, then choose which part of the screen "
                              "it should follow. For example, pick 'Left half' for a bulb on the left of your screen.",
                  style="Hint.TLabel", wraplength=WRAP, justify="left").pack(anchor="w", pady=(0, 6))
        self.bulb_list = ttk.Frame(bulbs)
        self.bulb_list.pack(fill="x")
        bar = ttk.Frame(bulbs)
        bar.pack(fill="x", pady=(8, 0))
        self.find_btn = ttk.Button(bar, text="Find bulbs", command=self._find_bulbs)
        self.find_btn.pack(side="left")
        self.bulb_status = ttk.Label(bar, text="", style="Hint.TLabel")
        self.bulb_status.pack(side="left", padx=10)

        # 2. Preset
        preset = ttk.LabelFrame(outer, text="2.  Choose a preset", padding=10, style="Section.TLabelframe")
        preset.pack(fill="x", pady=(0, 10))
        self.preset_keys = list(ambient.PRESETS)
        self.preset_var = tk.StringVar()
        self.preset_box = ttk.Combobox(preset, textvariable=self.preset_var, state="readonly", width=42,
                                       values=[ambient.PRESETS[k]["label"] for k in self.preset_keys])
        self.preset_box.pack(anchor="w")
        self.preset_box.bind("<<ComboboxSelected>>", lambda _e: self._on_preset_change())
        self.preset_desc = ttk.Label(preset, wraplength=WRAP, justify="left")
        self.preset_desc.pack(anchor="w", pady=(6, 6))

        self.tips = Collapsible(preset, "Tips for this preset", on_toggle=self._fit)
        self.tips.pack(fill="x")

        self.tune = Collapsible(preset, "Fine-tune (optional)", on_toggle=self._fit)
        self.tune.pack(fill="x")
        self._build_fine_tune(self.tune.body)

        # 3. Run
        run = ttk.LabelFrame(outer, text="3.  Start", padding=10, style="Section.TLabelframe")
        run.pack(fill="x")
        self.start_btn = ttk.Button(run, text="▶  Start", style="Big.TButton", command=self._toggle_run)
        self.start_btn.pack(side="left")
        self.run_status = ttk.Label(run, text="Stopped", style="Hint.TLabel", wraplength=330, justify="left")
        self.run_status.pack(side="left", padx=12)

    def _build_fine_tune(self, parent):
        grid = ttk.Frame(parent)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.sliders = {}
        row = 0
        for key, label, lo, hi, fmt, help_text in FINE_TUNE:
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10))
            value_lbl = ttk.Label(grid, width=6, anchor="e")
            scale = ttk.Scale(grid, from_=lo, to=hi, orient="horizontal",
                              command=lambda v, k=key: self._on_slide(k, float(v)))
            scale.grid(row=row, column=1, sticky="ew")
            value_lbl.grid(row=row, column=2, sticky="e", padx=(8, 0))
            ttk.Label(grid, text=help_text, style="Hint.TLabel").grid(row=row + 1, column=0, columnspan=3,
                                                                      sticky="w", pady=(0, 6))
            self.sliders[key] = (scale, value_lbl, fmt)
            row += 2

        ttk.Label(grid, text="Screen").grid(row=row, column=0, sticky="w", padx=(0, 10))
        self.monitor_var = tk.StringVar()
        self.monitor_box = ttk.Combobox(grid, textvariable=self.monitor_var, state="readonly",
                                        values=self._monitor_labels(), width=30)
        self.monitor_box.grid(row=row, column=1, sticky="w", pady=(2, 6))
        self.monitor_box.bind("<<ComboboxSelected>>", lambda _e: self._on_monitor_change())
        mon = self.settings.get("monitor", 1)
        if 1 <= mon <= len(self.monitor_box["values"]):
            self.monitor_box.current(mon - 1)
        elif self.monitor_box["values"]:
            self.monitor_box.current(0)

        ttk.Button(parent, text="Reset to preset defaults", command=self._reset_overrides).pack(anchor="w",
                                                                                               pady=(4, 0))

    def _monitor_labels(self):
        try:
            with mss.mss() as s:
                mons = s.monitors[1:]
        except Exception:
            return ["1"]
        return [f"Screen {i}: {m['width']}x{m['height']}" + ("  (main)" if i == 1 else "")
                for i, m in enumerate(mons, 1)]

    def _fit(self):
        self.root.update_idletasks()
        self.root.geometry("")   # let the window grow/shrink with collapsible sections

    # ---------- bulbs ----------
    def _refresh_bulb_rows(self):
        for child in self.bulb_list.winfo_children():
            child.destroy()
        self.bulb_rows = {}
        if not self.bulbs:
            ttk.Label(self.bulb_list, text="No bulbs yet. Click 'Find bulbs'.",
                      style="Hint.TLabel").pack(anchor="w")
            self._fit()
            return

        for i, b in enumerate(self.bulbs, 1):
            row = ttk.Frame(self.bulb_list)
            row.pack(fill="x", pady=2)
            swatch = tk.Canvas(row, width=18, height=18, highlightthickness=0)
            dot = swatch.create_oval(2, 2, 16, 16, fill="#cccccc", outline="#999999")
            swatch.pack(side="left", padx=(0, 8))
            ttk.Label(row, text=f"Bulb {i}", width=7).pack(side="left")
            status = b.get("_status", "")
            ttk.Label(row, text=b["ip"] + ("" if status != "offline" else "  (not found)"),
                      width=24, style="Bad.TLabel" if status == "offline" else "TLabel").pack(side="left")

            pos_var = tk.StringVar(value=POSITION_LABELS.get(b.get("position", "full"), "Whole screen"))
            pos_box = ttk.Combobox(row, textvariable=pos_var, state="readonly", width=20,
                                   values=list(POSITION_LABELS.values()))
            if "region" in b:
                pos_box.configure(values=["Custom region (bulbs.json)"] + list(POSITION_LABELS.values()))
                pos_var.set("Custom region (bulbs.json)")
            pos_box.pack(side="left", padx=(0, 6))
            pos_box.bind("<<ComboboxSelected>>", lambda _e, bulb=b, var=pos_var: self._on_position(bulb, var))
            ident = ttk.Button(row, text="Identify", command=lambda bulb=b: self._identify(bulb))
            ident.pack(side="left")
            self.bulb_rows[b["ip"]] = (swatch, dot, ident)
        self._update_controls()
        self._fit()

    def _on_position(self, bulb, var):
        label = var.get()
        if label in LABEL_TO_POSITION:
            bulb.pop("region", None)
            bulb["position"] = LABEL_TO_POSITION[label]
        ambient.save_config(self.bulbs, quiet=True)
        self._push_bulbs_to_engine()

    def _identify(self, bulb):
        all_ips = [b["ip"] for b in self.bulbs]
        threading.Thread(target=ambient.identify_bulb, args=(bulb["ip"], all_ips), daemon=True).start()
        self.bulb_status.configure(text=f"{bulb['ip']} is now green. Others are off for a moment.")
        self.root.after(4000, self._restore_after_identify)

    def _restore_after_identify(self):
        if self.engine:
            return
        for b in self.bulbs:
            if b.get("position") != "off":
                ambient.send_wiz_color(b["ip"], 255, 180, 110, 60)
        self.bulb_status.configure(text="")

    def _find_bulbs(self):
        if self.busy:
            return
        self._set_busy(True, "Searching your network for WiZ bulbs...")

        def work():
            try:
                devices = discover.discover()
            except Exception as e:  # noqa: BLE001 - surface any network error to the user
                devices, err = [], str(e)
            else:
                err = None
            self.root.after(0, lambda: self._on_found(devices, err))

        threading.Thread(target=work, daemon=True).start()

    def _on_found(self, devices, err):
        self._set_busy(False)
        if err:
            self.bulb_status.configure(text=f"Search failed: {err}")
            return
        found_macs = {d["mac"] for d in devices}
        merged = ambient.merge_discovered(self.bulbs, devices)
        for b in merged:
            b["_status"] = "online"
        for b in self.bulbs:   # keep saved bulbs that didn't answer this time
            if b.get("mac", "").lower() not in found_macs and b not in merged:
                b["_status"] = "offline"
                merged.append(b)
        self.bulbs = merged
        if self.bulbs:
            ambient.save_config(self.bulbs, quiet=True)
        self._refresh_bulb_rows()
        self._push_bulbs_to_engine()
        if devices:
            self.bulb_status.configure(text=f"Found {len(devices)} bulb(s).")
        else:
            self.bulb_status.configure(text="No bulbs found. Check they're on the same Wi-Fi, then try again.")

    def _check_saved_bulbs(self):
        """Make sure saved bulbs still answer; follow them by MAC if the router gave them new IPs."""
        self._set_busy(True, "Connecting to your saved bulbs...")
        saved = [dict(b) for b in self.bulbs]

        def work():
            answered = discover.probe([b["ip"] for b in saved])
            if any(b.get("mac", "").lower() not in answered for b in saved):
                for d in discover.discover(expected=len(saved)):
                    answered.setdefault(d["mac"], d)
            for b in saved:
                dev = answered.get(b.get("mac", "").lower())
                if dev:
                    b["ip"] = dev["ip"]
                    b["_status"] = "online"
                else:
                    b["_status"] = "offline"
            self.root.after(0, lambda: self._on_checked(saved))

        threading.Thread(target=work, daemon=True).start()

    def _on_checked(self, checked):
        self._set_busy(False)
        self.bulbs = checked
        ambient.save_config(self.bulbs, quiet=True)
        self._refresh_bulb_rows()
        self._push_bulbs_to_engine()
        offline = sum(b["_status"] == "offline" for b in checked)
        self.bulb_status.configure(text="All bulbs connected." if not offline else
                                   f"{offline} bulb(s) not found. Is it switched on? Try 'Find bulbs'.")

    def _set_busy(self, busy, msg=""):
        self.busy = busy
        self.find_btn.configure(state="disabled" if busy else "normal")
        if msg:
            self.bulb_status.configure(text=msg)

    def _active_bulbs(self):
        return [b for b in self.bulbs if ambient.region_for(b) is not None]

    def _push_bulbs_to_engine(self):
        if self.engine:
            self.engine.bulbs = self._active_bulbs()

    # ---------- presets & fine-tune ----------
    @property
    def preset(self):
        return self.settings["preset"]

    def _overrides(self):
        return self.settings["overrides"].setdefault(self.preset, {})

    def _load_preset_ui(self):
        info = ambient.PRESETS[self.preset]
        self.preset_box.current(self.preset_keys.index(self.preset))
        self.preset_desc.configure(text=info["description"])

        for child in self.tips.body.winfo_children():
            child.destroy()
        for tip in info["tips"]:
            ttk.Label(self.tips.body, text="•  " + tip, wraplength=WRAP - 20, justify="left").pack(anchor="w", pady=1)

        values = ambient.preset_settings(self.preset, self.settings["overrides"].get(self.preset))
        self._loading_sliders = True
        try:
            for key, (scale, value_lbl, fmt) in self.sliders.items():
                scale.set(values[key])
                value_lbl.configure(text=fmt(values[key]))
        finally:
            self._loading_sliders = False
        self._fit()

    def _on_preset_change(self):
        self.settings["preset"] = self.preset_keys[self.preset_box.current()]
        self._load_preset_ui()
        if self.engine:
            self.engine.overrides = dict(self.settings["overrides"].get(self.preset, {}))
            self.engine.preset = self.preset
        self._save_settings_soon()

    def _on_slide(self, key, value):
        scale, value_lbl, fmt = self.sliders[key]
        value_lbl.configure(text=fmt(value))
        if self._loading_sliders:
            return
        self._overrides()[key] = round(value, 3)
        if self.engine:
            self.engine.overrides = dict(self._overrides())
        self._save_settings_soon()

    def _reset_overrides(self):
        self.settings["overrides"].pop(self.preset, None)
        self._load_preset_ui()
        if self.engine:
            self.engine.overrides = {}
        self._save_settings_soon()

    def _on_monitor_change(self):
        self.settings["monitor"] = self.monitor_box.current() + 1
        self._save_settings_soon()
        if self.engine:   # restart capture on the new screen
            self._stop()
            self.root.after(300, self._start)

    def _save_settings_soon(self):
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(600, self._save_settings)

    def _save_settings(self):
        self._save_job = None
        self.settings["overrides"] = {k: v for k, v in self.settings["overrides"].items() if v}
        try:
            ambient.save_settings(self.settings)
        except OSError as e:
            self.run_status.configure(text=f"Could not save settings: {e}")

    # ---------- run ----------
    def _toggle_run(self):
        if self.engine:
            self._stop()
        else:
            self._start()

    def _start(self):
        bulbs = self._active_bulbs()
        if not bulbs:
            messagebox.showinfo(APP_TITLE, "No bulbs to use yet.\n\nClick 'Find bulbs' first, and make sure "
                                           "at least one bulb isn't set to 'Off'.")
            return
        self.engine_error = None
        self.frame_times = []
        self.engine = ambient.Engine(bulbs, self.preset, self.settings["overrides"].get(self.preset),
                                     self.settings.get("monitor", 1), on_frame=self._on_frame)

        def run(engine=self.engine):
            try:
                engine.run()
            except Exception as e:  # noqa: BLE001 - show any capture error in the UI
                self.engine_error = str(e)

        self.engine_thread = threading.Thread(target=run, daemon=True)
        self.engine_thread.start()
        self.start_btn.configure(text="■  Stop")
        self._update_controls()

    def _stop(self):
        if self.engine:
            self.engine.stop()
        self.engine = None
        self.latest_frame = None
        self.start_btn.configure(text="▶  Start")
        self.run_status.configure(text="Stopped", style="Hint.TLabel")
        for swatch, dot, _ in self.bulb_rows.values():
            swatch.itemconfigure(dot, fill="#cccccc")
        self._update_controls()

    def _update_controls(self):
        state = "disabled" if self.engine else "normal"
        for _, _, ident in self.bulb_rows.values():
            ident.configure(state=state)

    def _on_frame(self, frame):   # called from the engine thread
        self.latest_frame = frame
        now = time.monotonic()
        self.frame_times = [t for t in self.frame_times if now - t < 2.0] + [now]

    def _poll(self):
        if self.engine_error:
            err, self.engine_error = self.engine_error, None
            self._stop()
            self.run_status.configure(text=f"Stopped: {err}", style="Bad.TLabel")
        elif self.engine:
            frame = self.latest_frame
            if frame:
                for ip, (r, g, b), dim in frame:
                    row = self.bulb_rows.get(ip)
                    if row:
                        k = 0.35 + 0.65 * dim / 100
                        row[0].itemconfigure(row[1], fill=f"#{int(r * k):02x}{int(g * k):02x}{int(b * k):02x}")
                fps = len(self.frame_times) / 2.0
                self.run_status.configure(
                    text=f"Running · {ambient.PRESETS[self.preset]['label'].split(' (')[0]} · "
                         f"{len(frame)} bulb(s) · {fps:.0f} updates/s",
                    style="Ok.TLabel")
            else:
                self.run_status.configure(text="Starting...", style="Hint.TLabel")
        self.root.after(150, self._poll)

    def _on_close(self):
        if self.engine:
            self.engine.stop()
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_settings()
        self.root.destroy()


def main():
    if sys.platform == "win32":
        try:   # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
