"""Flyout bij het tray-icoon in Windows 11-stijl (zoals het wifi-/volumepaneel).

Randloos venster met afgeronde hoeken (DWM), licht of donker volgens het Windows-thema, accentkleur uit Windows,
schakelaars en schuifregelaars op Canvas. Sluit zodra het venster de focus verliest of bij Esc.
"""
import ctypes
import ctypes.wintypes as wt
import logging
import os
import tkinter as tk
import tkinter.font as tkfont

import config

log = logging.getLogger("flyout")


# ---------------------------------------------------------------------- Windows-thema en accentkleur
def _reg_dword(path, name):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return int(v)
    except OSError:
        return None


def windows_theme():
    light = _reg_dword(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme")
    dark = light == 0
    acc = _reg_dword(r"Software\Microsoft\Windows\DWM", "AccentColor")   # ABGR
    if acc is None:
        accent = "#0067C0" if not dark else "#4CC2FF"
    else:
        r, g, b = acc & 0xFF, (acc >> 8) & 0xFF, (acc >> 16) & 0xFF
        if dark:   # in donker thema gebruikt Windows een lichtere tint van het accent
            r, g, b = (min(255, int(c + (255 - c) * 0.35)) for c in (r, g, b))
        accent = f"#{r:02X}{g:02X}{b:02X}"
    if dark:
        return {"dark": True, "bg": "#202020", "card": "#2B2B2B", "card2": "#333333", "line": "#3A3A3A",
                "fg": "#FFFFFF", "fg2": "#C8C8C8", "fg3": "#8A8A8A", "accent": accent, "knob": "#FFFFFF",
                "off": "#9A9A9A", "track": "#4A4A4A", "hover": "#383838"}
    return {"dark": False, "bg": "#F3F3F3", "card": "#FFFFFF", "card2": "#F9F9F9", "line": "#E5E5E5",
            "fg": "#1B1B1B", "fg2": "#5C5C5C", "fg3": "#8C8C8C", "accent": accent, "knob": "#FFFFFF",
            "off": "#5C5C5C", "track": "#8A8A8A", "hover": "#EAEAEA"}


def _work_area():
    r = wt.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
    return r.left, r.top, r.right, r.bottom


def _round_corners(win):
    """Afgeronde hoeken en een subtiele rand via DWM (Windows 11)."""
    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        dwm = ctypes.windll.dwmapi
        pref = ctypes.c_int(2)                                    # DWMWCP_ROUND
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
    except Exception:
        pass


def _load_logo(th, size):
    """Atnovix-beeldmerk (assets/atnovix-light.png of -dark.png, passend bij het thema); None als het ontbreekt."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets",
                        "atnovix-dark.png" if th["dark"] else "atnovix-light.png")
    try:
        from PIL import Image, ImageTk
        img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        log.exception("logo laden")
        return None


# ---------------------------------------------------------------------- widgets
class Toggle(tk.Canvas):
    """Windows 11-schakelaar."""

    def __init__(self, master, th, var, command=None, s=1.0):
        self.w, self.h = int(40 * s), int(20 * s)
        super().__init__(master, width=self.w, height=self.h, bg=th["card"], highlightthickness=0, cursor="hand2")
        self.th, self.var, self.command, self.s = th, var, command, s
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def _click(self, e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def draw(self):
        self.delete("all")
        on = bool(self.var.get())
        w, h, r = self.w, self.h, self.h / 2
        fill = self.th["accent"] if on else self.th["card"]
        outline = self.th["accent"] if on else self.th["off"]
        self.create_oval(0, 0, h, h, fill=fill, outline=outline)
        self.create_oval(w - h, 0, w, h, fill=fill, outline=outline)
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill)
        self.create_line(r, 0, w - r, 0, fill=outline)
        self.create_line(r, h - 1, w - r, h - 1, fill=outline)
        kr = r - 4 * self.s
        cx = w - r if on else r
        self.create_oval(cx - kr, r - kr, cx + kr, r + kr, fill=self.th["knob"] if on else self.th["off"], outline="")


class Slider(tk.Canvas):
    """Windows 11-schuifregelaar met accentkleur en waardelabel via callback."""

    def __init__(self, master, th, var, lo, hi, on_change=None, s=1.0, width=200):
        self.w, self.h = int(width * s), int(24 * s)
        super().__init__(master, width=self.w, height=self.h, bg=th["card"], highlightthickness=0, cursor="hand2")
        self.th, self.var, self.lo, self.hi, self.on_change, self.s = th, var, lo, hi, on_change, s
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def _drag(self, e):
        m = 10 * self.s
        f = min(1.0, max(0.0, (e.x - m) / (self.w - 2 * m)))
        self.var.set(round(self.lo + f * (self.hi - self.lo), 1))
        if self.on_change:
            self.on_change()

    def draw(self):
        self.delete("all")
        m, cy = 10 * self.s, self.h / 2
        f = (float(self.var.get()) - self.lo) / (self.hi - self.lo)
        f = min(1.0, max(0.0, f))
        x = m + f * (self.w - 2 * m)
        t = 2 * self.s
        self.create_line(m, cy, self.w - m, cy, fill=self.th["track"], width=t, capstyle="round")
        self.create_line(m, cy, x, cy, fill=self.th["accent"], width=t, capstyle="round")
        r = 8 * self.s
        self.create_oval(x - r, cy - r, x + r, cy + r, fill=self.th["card"], outline=self.th["line"])
        r2 = 5 * self.s
        self.create_oval(x - r2, cy - r2, x + r2, cy + r2, fill=self.th["accent"], outline="")


class Tile(tk.Frame):
    """Snelle-instellingen-tegel (zoals wifi/bluetooth): gevuld met accentkleur als hij actief is."""

    def __init__(self, master, th, text, icon, command, s=1.0):
        super().__init__(master, bg=th["card2"], cursor="hand2")
        self.th, self.command, self.active = th, command, False
        self.icon = tk.Label(self, text=icon, bg=th["card2"], fg=th["fg"], font=("Segoe UI Emoji", int(15 * s)))
        self.icon.pack(pady=(int(10 * s), 0))
        self.text = tk.Label(self, text=text, bg=th["card2"], fg=th["fg"], font=("Segoe UI", int(9 * s)))
        self.text.pack(pady=(0, int(8 * s)))
        for w in (self, self.icon, self.text):
            w.bind("<Button-1>", lambda e: self.command())
        self.set_active(False)

    def set_active(self, on):
        self.active = on
        bg = self.th["accent"] if on else self.th["card2"]
        fg = "#FFFFFF" if on and not self.th["dark"] else ("#000000" if on else self.th["fg"])
        for w in (self, self.icon, self.text):
            w.configure(bg=bg)
        self.icon.configure(fg=fg)
        self.text.configure(fg=fg)


# ---------------------------------------------------------------------- de flyout
class Flyout:
    def __init__(self, root, driver, on_more=None):
        self.root, self.drv, self.on_more = root, driver, on_more
        self.win = None
        self.vars = {}
        self._after = None
        self._poll = None
        self._had_focus = False
        self.autohide = True          # sluiten bij klik buiten het paneel / focusverlies
        self.th = windows_theme()
        self.s = root.winfo_fpixels("1i") / 96.0      # DPI-schaal

    # -- tonen/verbergen
    def show(self):
        th = windows_theme()
        if self.win is None or not self.win.winfo_exists() or th != self.th:
            self.th = th
            if self.win is not None and self.win.winfo_exists():
                self.win.destroy()
            self._build()
        self._load()
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        pt = wt.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        l, t, r, b = _work_area()
        m = int(12 * self.s)
        x = min(max(pt.x - w // 2, l + m), r - w - m)
        y = b - h - m
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.win.deiconify()
        self.win.lift()
        self._had_focus = False
        self.win.focus_force()
        try:
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        _round_corners(self.win)
        self.drv.request_battery()
        self._tick()
        if self.autohide:
            self._poll_outside()

    def hide(self, *_):
        for attr in ("_after", "_poll"):
            if getattr(self, attr):
                self.root.after_cancel(getattr(self, attr))
                setattr(self, attr, None)
        if self.win is not None and self.win.winfo_exists():
            self.win.withdraw()

    def _focus_in(self, e):
        self._had_focus = True

    def _focus_out(self, e):
        # pas sluiten als het paneel eerder echt de focus had en die nu buiten het venster ligt
        if self.autohide and self._had_focus:
            self.root.after(80, self._check_focus)

    def _check_focus(self):
        try:
            if self.win.winfo_exists() and self.win.state() != "withdrawn" and self.win.focus_displayof() is None:
                self.hide()
        except tk.TclError:
            pass

    def _poll_outside(self):
        """Klik (links of rechts) buiten het paneel sluit het, ook als Windows ons geen focus gaf."""
        self._poll = None
        try:
            if not self.win.winfo_exists() or self.win.state() == "withdrawn":
                return
            u = ctypes.windll.user32
            if (u.GetAsyncKeyState(0x01) | u.GetAsyncKeyState(0x02)) & 0x8000:
                pt = wt.POINT()
                u.GetCursorPos(ctypes.byref(pt))
                x, y = self.win.winfo_rootx(), self.win.winfo_rooty()
                if not (x <= pt.x < x + self.win.winfo_width() and y <= pt.y < y + self.win.winfo_height()):
                    self.hide()
                    return
        except tk.TclError:
            return
        self._poll = self.root.after(120, self._poll_outside)

    # -- opbouw
    def _build(self):
        th, s = self.th, self.s
        # Afgeronde hoeken: de vensterkleur KEY is transparant, een Canvas tekent het afgeronde paneel en de inhoud
        # staat er met een rand van `rad` pixels in, zodat de hoeken vrij blijven.
        KEY = "#010203"
        rad = int(10 * s)
        w = self.win = tk.Toplevel(self.root, bg=KEY)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-transparentcolor", KEY)
        w.withdraw()
        self._panel = tk.Canvas(w, bg=KEY, highlightthickness=0, bd=0)
        self._panel.place(x=0, y=0, relwidth=1, relheight=1)
        self._rad = rad

        def redraw(e=None):
            c = self._panel
            c.delete("all")
            W, H, r = w.winfo_width(), w.winfo_height(), rad
            if W < 2 * r or H < 2 * r:
                return
            pts = [r, 0, W - r, 0, W, 0, W, r, W, H - r, W, H, W - r, H, r, H, 0, H, 0, H - r, 0, r, 0, 0]
            c.create_polygon(pts, smooth=True, splinesteps=24, fill=th["bg"], outline=th["line"])
        w.bind("<Configure>", redraw)
        w.bind("<Escape>", self.hide)
        w.bind("<FocusIn>", self._focus_in)
        w.bind("<FocusOut>", self._focus_out)
        f_title = ("Segoe UI Variable Display", int(12 * s), "bold") if "Segoe UI Variable Display" in tkfont.families() else ("Segoe UI", int(12 * s), "bold")
        f_norm = ("Segoe UI", int(10 * s))
        f_small = ("Segoe UI", int(9 * s))
        pad = int(14 * s)
        v = self.vars
        outer = tk.Frame(w, bg=th["bg"])
        outer.pack(fill="both", expand=True, padx=rad, pady=rad)

        # kop: naam, status, accu
        head = tk.Frame(outer, bg=th["bg"])
        head.pack(fill="x", padx=pad, pady=(pad, int(6 * s)))
        v["dot"] = tk.Label(head, text="●", bg=th["bg"], fg=th["fg3"], font=f_norm)
        v["dot"].pack(side="left")
        tk.Label(head, text="Magic Trackpad", bg=th["bg"], fg=th["fg"], font=f_title).pack(side="left", padx=(int(6 * s), 0))
        self._logo = _load_logo(th, int(22 * s))
        if self._logo is not None:
            tk.Label(head, image=self._logo, bg=th["bg"], bd=0).pack(side="right")
        v["battery"] = tk.Label(head, text="", bg=th["bg"], fg=th["fg2"], font=f_norm)
        v["battery"].pack(side="right", padx=(0, int(8 * s)) if self._logo is not None else 0)
        v["status"] = tk.Label(outer, text="", bg=th["bg"], fg=th["fg2"], font=f_small, anchor="w")
        v["status"].pack(fill="x", padx=pad + int(16 * s))

        # tegels: modus
        tiles = tk.Frame(outer, bg=th["bg"])
        tiles.pack(fill="x", padx=pad, pady=(int(10 * s), int(6 * s)))
        tiles.columnconfigure((0, 1, 2), weight=1, uniform="t")
        v["tile_tp"] = Tile(tiles, th, "Trackpad", "🖱", lambda: self._set_mode(False), s)
        v["tile_np"] = Tile(tiles, th, "Numpad", "🔢", lambda: self._set_mode(True), s)
        v["tile_on"] = Tile(tiles, th, "Actief", "⏻", self._toggle_enabled, s)
        for i, t in enumerate((v["tile_tp"], v["tile_np"], v["tile_on"])):
            t.grid(row=0, column=i, sticky="nsew", padx=int(3 * s))

        # kaart met instellingen
        card = tk.Frame(outer, bg=th["card"])
        card.pack(fill="x", padx=pad, pady=(int(6 * s), 0))

        def row(label, widget_fn, value_var=None):
            fr = tk.Frame(card, bg=th["card"])
            fr.pack(fill="x", padx=int(12 * s), pady=int(5 * s))
            tk.Label(fr, text=label, bg=th["card"], fg=th["fg"], font=f_norm, anchor="w").pack(side="left")
            if value_var is not None:
                tk.Label(fr, textvariable=value_var, bg=th["card"], fg=th["fg2"], font=f_small, width=4, anchor="e").pack(side="right")
            widget_fn(fr).pack(side="right", padx=(int(8 * s), 0))

        def sl(key, lo, hi):
            v[key] = tk.DoubleVar()
            v[key + "_txt"] = tk.StringVar()
            v[key].trace_add("write", lambda *a, k=key: v[k + "_txt"].set(f"{v[k].get():.1f}" if hi <= 40 else f"{v[k].get():.0f}"))
            return lambda fr: Slider(fr, th, v[key], lo, hi, self._apply_sliders, s, width=150)

        def tg(key, cb):
            v[key] = tk.BooleanVar()
            return lambda fr: Toggle(fr, th, v[key], cb, s)

        row("Cursorsnelheid", sl("gain", 1.0, 10.0), v["gain_txt"])
        row("Scrollsnelheid", sl("scroll_gain", 10.0, 120.0), v["scroll_gain_txt"])
        tk.Frame(card, bg=th["line"], height=1).pack(fill="x", padx=int(12 * s), pady=int(4 * s))
        row("Natuurlijk scrollen", tg("natural", self._apply_toggles))
        row("Tikken = klikken", tg("tap_click", self._apply_toggles))
        row("Fusion: zoom omkeren", tg("fusion_zoom_inv", self._apply_toggles))
        row("Fusion: draaien omkeren", tg("fusion_rot_inv", self._apply_toggles))
        tk.Frame(card, bg=th["line"], height=1).pack(fill="x", padx=int(12 * s), pady=int(4 * s))
        row("Starten bij aanmelden", tg("autostart", self._apply_autostart))
        tk.Frame(card, bg=th["card"], height=int(4 * s)).pack()

        # voet: links, zoals "Meer wifi-instellingen"
        foot = tk.Frame(outer, bg=th["bg"])
        foot.pack(fill="x", padx=pad, pady=(int(10 * s), pad))
        for text, cmd, side in (("Meer instellingen", self._more, "left"), ("Afsluiten", self.drv.quit, "right"),
                                ("Opnieuw verbinden", self.drv.reader.reconnect, "right")):
            lbl = tk.Label(foot, text=text, bg=th["bg"], fg=th["accent"], font=f_small, cursor="hand2")
            lbl.pack(side=side, padx=(0, int(14 * s)) if side == "right" else 0)
            lbl.bind("<Button-1>", lambda e, c=cmd: (self.hide(), c()))
            lbl.bind("<Enter>", lambda e, l=lbl: l.configure(font=f_small + ("underline",)))
            lbl.bind("<Leave>", lambda e, l=lbl: l.configure(font=f_small))

    # -- gegevens
    def _load(self):
        c, v = self.drv.cfg, self.vars
        d = c["profiles"]["default"]
        f = config.profile_for(c, "fusion360.exe")
        v["gain"].set(c["pointer"]["gain_px_per_mm"])
        v["scroll_gain"].set(d["scroll"].get("gain", 40.0))
        v["natural"].set(d["scroll"].get("natural", True))
        v["tap_click"].set(c["tap"]["actions"].get("1", "none") != "none")
        v["fusion_zoom_inv"].set(bool(f["pinch"].get("invert")))
        v["fusion_rot_inv"].set(bool(f["rotate"].get("invert")))
        v["autostart"].set(self.drv.autostart_enabled())
        self._refresh()

    def _refresh(self):
        d, v, th = self.drv, self.vars, self.th
        v["tile_tp"].set_active(not d.output.numpad_on)
        v["tile_np"].set_active(d.output.numpad_on)
        v["tile_on"].set_active(d.enabled)
        if not d.port_open:
            dot, txt = th["fg3"], f"{d.cfg['serial']['port']} niet gevonden"
        elif not d.trackpad_connected:
            dot, txt = "#E8A317", "wacht op het trackpad, raak het aan"
        else:
            dot = th["accent"]
            txt = ("numpad-modus" if d.output.numpad_on else "trackpad-modus") + (f", {d.frame_rate:.0f} frames/s" if d.frame_rate else "")
            if d.output.exe:
                txt += f", profiel {d.output.exe}"
        v["dot"].configure(fg=dot)
        v["status"].configure(text=txt)
        v["battery"].configure(text=("🔋 " + d.battery) if d.battery != "?" else "")

    def _tick(self):
        if self.win is not None and self.win.winfo_exists() and self.win.state() != "withdrawn":
            self._refresh()
            self._after = self.root.after(1000, self._tick)

    # -- acties
    def _set_mode(self, numpad):
        self.drv.set_numpad(numpad)
        self._refresh()

    def _toggle_enabled(self):
        self.drv.set_enabled(not self.drv.enabled)
        self._refresh()

    def _apply_sliders(self):
        c, v = self.drv.cfg, self.vars
        c["pointer"]["gain_px_per_mm"] = round(v["gain"].get(), 2)
        c["profiles"]["default"]["scroll"]["gain"] = round(v["scroll_gain"].get(), 1)
        self._save()

    def _apply_toggles(self):
        c, v = self.drv.cfg, self.vars
        c["profiles"]["default"]["scroll"]["natural"] = bool(v["natural"].get())
        c["tap"]["actions"]["1"] = "click:left" if v["tap_click"].get() else "none"
        fu = c["profiles"].setdefault("fusion360.exe", {})
        fu.setdefault("pinch", {"type": "wheel", "gain": 50.0, "modifiers": []})["invert"] = bool(v["fusion_zoom_inv"].get())
        fu.setdefault("rotate", {"type": "drag", "button": "middle", "modifiers": ["shift"], "axis": "x", "gain": 4.0})["invert"] = bool(v["fusion_rot_inv"].get())
        self._save()

    def _apply_autostart(self):
        try:
            self.drv.set_autostart(bool(self.vars["autostart"].get()))
        except Exception:
            log.exception("autostart wijzigen")

    def _save(self):
        try:
            config.save(self.drv.cfg)
            self.drv.reload_config()
        except Exception:
            log.exception("instellingen opslaan")

    def _more(self):
        if self.on_more:
            self.on_more()
