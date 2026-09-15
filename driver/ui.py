"""Statusvenster van de driver: native Windows-widgets (ttk, thema 'vista'), geopend vanuit het tray-icoon.

Draait in de hoofdthread (Tk). Alles wat vanuit andere threads komt gaat via root.after(...).
"""
import os
import tkinter as tk
from tkinter import ttk

import config


class StatusWindow:
    def __init__(self, root, driver):
        self.root = root
        self.drv = driver
        self.win = None
        self.vars = {}
        self._after = None

    # ------------------------------------------------------------------ openen/sluiten
    def show(self):
        if self.win is None or not self.win.winfo_exists():
            self._build()
        self._load_from_config()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        self.drv.request_battery()
        self._tick()

    def hide(self):
        if self._after:
            self.root.after_cancel(self._after)
            self._after = None
        if self.win is not None and self.win.winfo_exists():
            self.win.withdraw()

    # ------------------------------------------------------------------ opbouw
    def _build(self):
        w = self.win = tk.Toplevel(self.root)
        w.title("Magic Trackpad")
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self.hide)
        try:
            from PIL import ImageTk
            self._photo = ImageTk.PhotoImage(self.drv.icon_image().resize((32, 32)))
            w.iconphoto(False, self._photo)
        except Exception:
            pass
        pad = {"padx": 10, "pady": 4}
        v = self.vars

        # --- status
        st = ttk.LabelFrame(w, text="Status")
        st.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 4))
        for i, (key, label) in enumerate([("port", "Seriële poort"), ("conn", "Trackpad"), ("battery", "Accu"),
                                          ("mode", "Modus"), ("rate", "Frames"), ("app", "Actief profiel")]):
            ttk.Label(st, text=label + ":").grid(row=i, column=0, sticky="w", **pad)
            v[key] = tk.StringVar(value="-")
            ttk.Label(st, textvariable=v[key], width=34).grid(row=i, column=1, sticky="w", **pad)

        # --- modus
        md = ttk.LabelFrame(w, text="Modus")
        md.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=4)
        v["numpad"] = tk.BooleanVar()
        ttk.Radiobutton(md, text="Trackpad (muis en gestures)", variable=v["numpad"], value=False,
                        command=self._apply_mode).grid(row=0, column=0, sticky="w", **pad)
        ttk.Radiobutton(md, text="Numpad (NUM20-folie)", variable=v["numpad"], value=True,
                        command=self._apply_mode).grid(row=1, column=0, sticky="w", **pad)
        v["enabled"] = tk.BooleanVar()
        ttk.Checkbutton(md, text="Driver actief", variable=v["enabled"], command=self._apply_mode).grid(row=2, column=0, sticky="w", **pad)
        v["calibrate"] = tk.BooleanVar()
        ttk.Checkbutton(md, text="Numpad-kalibratie (tikken in het log)", variable=v["calibrate"],
                        command=self._apply_mode).grid(row=3, column=0, sticky="w", **pad)

        # --- systeem
        sy = ttk.LabelFrame(w, text="Systeem")
        sy.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=4)
        v["autostart"] = tk.BooleanVar()
        ttk.Checkbutton(sy, text="Automatisch starten bij aanmelden", variable=v["autostart"],
                        command=self._apply_autostart).grid(row=0, column=0, sticky="w", **pad)
        ttk.Button(sy, text="Opnieuw verbinden", command=self.drv.reader.reconnect).grid(row=1, column=0, sticky="ew", **pad)
        ttk.Button(sy, text="Config openen", command=lambda: os.startfile(config.CONFIG_PATH)).grid(row=2, column=0, sticky="ew", **pad)
        ttk.Button(sy, text="Log openen", command=lambda: os.startfile(config.LOG_PATH)).grid(row=3, column=0, sticky="ew", **pad)

        # --- instellingen
        se = ttk.LabelFrame(w, text="Instellingen")
        se.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=4)
        r = 0

        def slider(label, key, lo, hi, fmt="{:.1f}"):
            nonlocal r
            ttk.Label(se, text=label).grid(row=r, column=0, sticky="w", **pad)
            v[key] = tk.DoubleVar()
            lbl = ttk.Label(se, width=6)
            s = ttk.Scale(se, from_=lo, to=hi, variable=v[key], length=220,
                          command=lambda val, l=lbl, f=fmt: l.configure(text=f.format(float(val))))
            s.grid(row=r, column=1, sticky="ew", **pad)
            lbl.grid(row=r, column=2, sticky="w", **pad)
            v[key + "_label"] = lbl
            r += 1

        slider("Cursorsnelheid (px per mm)", "gain", 1.0, 10.0)
        slider("Cursor bij snel bewegen", "max_gain", 4.0, 30.0)
        slider("Scrollsnelheid", "scroll_gain", 10.0, 120.0, "{:.0f}")
        slider("Fusion: pannen", "fusion_pan", 2.0, 40.0)
        slider("Fusion: orbit (px per graad)", "fusion_orbit", 1.0, 12.0)

        def check(label, key, col):
            v[key] = tk.BooleanVar()
            ttk.Checkbutton(se, text=label, variable=v[key]).grid(row=r, column=col, sticky="w", **pad)

        check("Natuurlijk scrollen", "natural", 0); check("Scrollen met traagheid", "inertia", 1); r += 1
        check("Tikken = klikken", "tap_click", 0); check("Tik-tik-vasthouden = slepen", "tap_drag", 1); r += 1
        check("Fusion: zoomrichting omkeren", "fusion_zoom_inv", 0); check("Fusion: draairichting omkeren", "fusion_rot_inv", 1); r += 1

        # --- knoppen
        bt = ttk.Frame(w)
        bt.grid(row=3, column=0, columnspan=2, sticky="e", padx=10, pady=(4, 10))
        ttk.Button(bt, text="Opslaan en toepassen", command=self._save).grid(row=0, column=0, padx=4)
        ttk.Button(bt, text="Sluiten", command=self.hide).grid(row=0, column=1, padx=4)
        ttk.Button(bt, text="Driver afsluiten", command=self.drv.quit).grid(row=0, column=2, padx=4)

    # ------------------------------------------------------------------ gegevens
    def _load_from_config(self):
        c = self.drv.cfg
        v = self.vars
        f = config.profile_for(c, "fusion360.exe")
        d = c["profiles"]["default"]
        v["numpad"].set(self.drv.output.numpad_on)
        v["enabled"].set(self.drv.enabled)
        v["calibrate"].set(bool(c["numpad"].get("calibrate")))
        v["autostart"].set(self.drv.autostart_enabled())
        v["gain"].set(c["pointer"]["gain_px_per_mm"])
        v["max_gain"].set(c["pointer"]["max_gain_px_per_mm"])
        v["scroll_gain"].set(d["scroll"].get("gain", 40.0))
        v["fusion_pan"].set(f["scroll"].get("gain", 12.0))
        v["fusion_orbit"].set(f["rotate"].get("gain", 4.0))
        for key, fmt in (("gain", "{:.1f}"), ("max_gain", "{:.1f}"), ("scroll_gain", "{:.0f}"), ("fusion_pan", "{:.1f}"), ("fusion_orbit", "{:.1f}")):
            v[key + "_label"].configure(text=fmt.format(v[key].get()))
        v["natural"].set(d["scroll"].get("natural", True))
        v["inertia"].set(c["inertia"]["enabled"])
        v["tap_click"].set(c["tap"]["actions"].get("1", "none") != "none")
        v["tap_drag"].set(c["tap"]["double_tap_drag_ms"] > 0)
        v["fusion_zoom_inv"].set(bool(f["pinch"].get("invert")))
        v["fusion_rot_inv"].set(bool(f["rotate"].get("invert")))

    def _save(self):
        c = self.drv.cfg
        v = self.vars
        c["pointer"]["gain_px_per_mm"] = round(v["gain"].get(), 2)
        c["pointer"]["max_gain_px_per_mm"] = round(v["max_gain"].get(), 2)
        c["profiles"]["default"]["scroll"]["gain"] = round(v["scroll_gain"].get(), 1)
        c["profiles"]["default"]["scroll"]["natural"] = bool(v["natural"].get())
        c["inertia"]["enabled"] = bool(v["inertia"].get())
        c["tap"]["actions"]["1"] = "click:left" if v["tap_click"].get() else "none"
        c["tap"]["double_tap_drag_ms"] = 260 if v["tap_drag"].get() else 0
        fu = c["profiles"].setdefault("fusion360.exe", {})
        fu.setdefault("scroll", {"type": "drag", "button": "middle", "natural": False})["gain"] = round(v["fusion_pan"].get(), 2)
        fu.setdefault("rotate", {"type": "drag", "button": "middle", "modifiers": ["shift"], "axis": "x"})["gain"] = round(v["fusion_orbit"].get(), 2)
        fu["rotate"]["invert"] = bool(v["fusion_rot_inv"].get())
        fu.setdefault("pinch", {"type": "wheel", "gain": 50.0, "modifiers": []})["invert"] = bool(v["fusion_zoom_inv"].get())
        c["numpad"]["calibrate"] = bool(v["calibrate"].get())
        config.save(c)
        self.drv.reload_config()

    def _apply_mode(self):
        v = self.vars
        self.drv.enabled = bool(v["enabled"].get())
        self.drv.set_numpad(bool(v["numpad"].get()))
        self.drv.set_calibrate(bool(v["calibrate"].get()))

    def _apply_autostart(self):
        self.drv.set_autostart(bool(self.vars["autostart"].get()))

    def refresh(self):
        """Statusvelden bijwerken (aangeroepen vanuit de Tk-thread)."""
        if self.win is None or not self.win.winfo_exists() or self.win.state() == "withdrawn":
            return
        d = self.drv
        v = self.vars
        v["port"].set(f"{d.cfg['serial']['port']} open" if d.port_open else f"{d.cfg['serial']['port']} niet beschikbaar")
        v["conn"].set("verbonden" if d.trackpad_connected else ("wacht op trackpad (raak het aan)" if d.port_open else "-"))
        v["battery"].set(d.battery)
        v["mode"].set(("numpad" if d.output.numpad_on else "trackpad") + ("" if d.enabled else " (driver uit)"))
        v["rate"].set(f"{d.frame_rate:.0f} per seconde, {d.frames} totaal")
        v["app"].set(d.output.exe or "-")
        v["numpad"].set(d.output.numpad_on)
        v["enabled"].set(d.enabled)

    def _tick(self):
        self.refresh()
        if self.win is not None and self.win.winfo_exists() and self.win.state() != "withdrawn":
            self._after = self.root.after(1000, self._tick)
