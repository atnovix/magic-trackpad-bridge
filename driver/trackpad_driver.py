"""MagicTrackpadBridge-driver: leest de ESP32-brug op de seriële poort en maakt er muis, gestures en numpad van.

Start:   pythonw trackpad_driver.py          (tray-icoon, geen venster)
         python  trackpad_driver.py --console (log ook in de console)
Config:  config.json in de projectmap (tray-menu > Config openen; daarna Config herladen)
Log:     driver.log in de projectmap
"""
import logging
import logging.handlers
import os
import queue
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config                      # noqa: E402
from actions import Output         # noqa: E402
from bridge import BridgeReader    # noqa: E402
from gestures import Frame, GestureEngine  # noqa: E402

log = logging.getLogger("driver")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "MagicTrackpadBridge"


def setup_logging(console):
    os.makedirs(config.APP_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(config.LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


# ---------------------------------------------------------------------- autostart (HKCU\...\Run)
def _pythonw():
    """pythonw zonder console. Bij de Store-Python de vaste alias in WindowsApps gebruiken: het pad van
    sys.executable bevat het versienummer en breekt bij elke update."""
    alias = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "pythonw.exe")
    if "WindowsApps" in sys.executable and os.path.exists(alias):
        return alias
    w = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return w if os.path.exists(w) else sys.executable


def autostart_command():
    return f'"{_pythonw()}" "{os.path.abspath(__file__)}"'


def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, RUN_NAME)
            return bool(val)
    except OSError:
        return False


def set_autostart(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass
    log.info("autostart %s", "aan" if on else "uit")


def single_instance():
    """True als dit de enige draaiende driver is (Windows-mutex); een tweede exemplaar zou om COM3 vechten."""
    import ctypes
    h = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\MagicTrackpadBridgeDriver")
    return h != 0 and ctypes.windll.kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS


# ---------------------------------------------------------------------- de driver zelf
class Driver:
    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = True
        self.lines = queue.Queue(maxsize=2000)
        self.output = Output(cfg, on_numpad_toggle=self._numpad_changed)
        self.engine = GestureEngine(cfg, self.output.handle)
        self.engine.numpad = self.output.numpad_on
        self.engine.lenient_tap = bool(cfg["numpad"].get("calibrate"))
        self.reader = BridgeReader(cfg["serial"]["port"], cfg["serial"]["baud"], self._on_line, self._on_status)
        self.port_open = False
        self.trackpad_connected = False
        self.battery = "?"
        self.frames = 0
        self.frame_rate = 0.0
        self._rate_t = time.monotonic()
        self._rate_n = 0
        self.icon = None
        self.on_open_window = None       # callback vanuit het tray-icoon (linksklik / menu)
        self.on_quit = None
        self._stop = threading.Event()

    # -- callbacks vanuit de seriële thread
    def _on_line(self, s):
        try:
            self.lines.put_nowait((time.monotonic(), s))
        except queue.Full:
            pass

    def _on_status(self, ok, text):
        self.port_open = ok
        if not ok:
            self.trackpad_connected = False
        log.info("poort: %s", text)
        self._refresh_icon()

    def _numpad_changed(self, on):
        self.engine.numpad = on
        self._refresh_icon()

    # -- verwerkingslus (eigen thread); een fout in één frame mag de driver nooit stoppen
    def loop(self):
        while not self._stop.is_set():
            try:
                self._loop_once()
            except Exception:
                log.exception("fout in verwerkingslus")
                time.sleep(0.1)

    def _loop_once(self):
        try:
            t, s = self.lines.get(timeout=0.005)
        except queue.Empty:
            self.output.tick(time.monotonic())
            return
        if s.startswith("F "):
            self.frames += 1
            self._rate_n += 1
            now = time.monotonic()
            if now - self._rate_t >= 1.0:
                self.frame_rate = self._rate_n / (now - self._rate_t)
                self._rate_t, self._rate_n = now, 0
            if self.enabled:
                fr = Frame.parse(s, t)
                if fr is not None:
                    self.engine.feed(fr)
        elif s.startswith("S "):
            self._status_line(s)
        elif s.startswith("B "):
            self.battery = s[2:].strip() + " %"
            self._refresh_icon()
        elif s.startswith(("W (", "E (")):
            log.warning("esp32: %s", s)
        self.output.tick(time.monotonic())

    def _status_line(self, s):
        body = s[2:]
        if body.startswith("connected"):
            self.trackpad_connected = True
            log.info("trackpad verbonden")
            self._refresh_icon()
        elif body.startswith("disconnected"):
            self.trackpad_connected = False
            self.frame_rate = 0.0
            log.info("trackpad verbroken")
            self._refresh_icon()
        elif body.startswith("gap"):
            log.debug("esp32: %s", body)      # stil liggende vinger geeft ook gaten; alleen voor diagnose
        elif body.startswith(("acl", "mode", "role", "link", "pkt")):
            log.info("esp32: %s", body)

    # -- besturing
    def start(self):
        self.reader.start()
        threading.Thread(target=self.loop, name="driver-loop", daemon=True).start()

    def stop(self):
        self._stop.set()
        self.reader.stop()

    def quit(self):
        self.stop()
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self.on_quit:
            self.on_quit()

    def request_battery(self):
        self.reader.send("b")

    def reload_config(self):
        try:
            cfg = config.load()
        except Exception as e:
            log.error("config herladen mislukt: %s", e)
            return
        self.cfg = cfg
        self.engine.cfg = cfg
        self.engine.lenient_tap = bool(cfg["numpad"].get("calibrate"))
        self.output.reload(cfg)
        log.info("config herladen")

    def set_numpad(self, on):
        if on != self.output.numpad_on:
            self.output.set_numpad(on)
        self.engine.numpad = on
        self._refresh_icon()

    def set_calibrate(self, on):
        self.cfg["numpad"]["calibrate"] = bool(on)
        self.engine.lenient_tap = bool(on)

    def set_enabled(self, on):
        self.enabled = bool(on)
        log.info("driver %s", "actief" if self.enabled else "uit")
        self._refresh_icon()

    autostart_enabled = staticmethod(autostart_enabled)
    set_autostart = staticmethod(set_autostart)

    # -- tray-icoon: groen = trackpad, blauw met toetsen = numpad, oranje = wacht op trackpad, grijs = geen poort
    def icon_image(self):
        from PIL import Image, ImageDraw
        numpad = self.output.numpad_on
        if not self.port_open:
            color = (150, 150, 150)
        elif not self.trackpad_connected:
            color = (235, 160, 40)
        elif numpad:
            color = (55, 120, 230)
        else:
            color = (50, 175, 90)
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((2, 6, 62, 58), radius=12, fill=color)
        white = (255, 255, 255)
        if numpad:
            for x in (16, 32, 48):
                for y in (19, 32, 45):
                    d.rounded_rectangle((x - 5, y - 5, x + 5, y + 5), radius=2, fill=white)
        else:
            d.rounded_rectangle((11, 15, 53, 49), radius=6, outline=white, width=3)
            d.ellipse((26, 26, 38, 38), fill=white)
        if not self.enabled:
            d.line((10, 10, 54, 54), fill=(225, 45, 45), width=7)
        return img

    def _refresh_icon(self):
        if self.icon is None:
            return
        try:
            self.icon.icon = self.icon_image()
            state = "geen poort" if not self.port_open else ("wacht op trackpad" if not self.trackpad_connected else "verbonden")
            self.icon.title = f"Magic Trackpad: {state}, accu {self.battery}" + (", numpad" if self.output.numpad_on else "")
        except Exception:
            log.exception("tray-icoon bijwerken")

    def start_tray(self):
        """Tray-icoon in een eigen thread; linksklik of 'Openen' opent het statusvenster."""
        import pystray
        from pystray import MenuItem as Item

        def open_window(icon=None, item=None):
            if self.on_open_window:
                self.on_open_window()

        menu = pystray.Menu(
            Item("Openen", open_window, default=True),
            pystray.Menu.SEPARATOR,
            Item("Trackpad-modus", lambda i, it: self.set_numpad(False), checked=lambda i: not self.output.numpad_on, radio=True),
            Item("Numpad-modus", lambda i, it: self.set_numpad(True), checked=lambda i: self.output.numpad_on, radio=True),
            Item("Driver actief", lambda i, it: self.set_enabled(not self.enabled), checked=lambda i: self.enabled),
            pystray.Menu.SEPARATOR,
            Item("Opnieuw verbinden", lambda i, it: self.reader.reconnect()),
            Item("Afsluiten", lambda i, it: self.quit()),
        )
        self.icon = pystray.Icon("MagicTrackpadBridge", self.icon_image(), "Magic Trackpad", menu)
        self._refresh_icon()
        self.icon.run_detached()


def main():
    console = "--console" in sys.argv
    setup_logging(console)
    if not single_instance():
        log.warning("er draait al een driver; deze stopt")
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)     # scherpe tekst in het venster op hoge-DPI-schermen
    except Exception:
        pass
    cfg = config.load()
    log.info("driver start; config %s", config.CONFIG_PATH)
    drv = Driver(cfg)
    drv.start()
    if "--no-tray" in sys.argv:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            drv.stop()
        return

    import tkinter as tk
    from tkinter import ttk
    from ui import StatusWindow

    root = tk.Tk()
    root.withdraw()
    try:
        ttk.Style(root).theme_use("vista")
    except Exception:
        pass
    win = StatusWindow(root, drv)
    drv.on_open_window = lambda: root.after(0, win.show)     # vanuit de tray-thread naar de Tk-thread
    drv.on_quit = lambda: root.after(0, root.destroy)
    drv.start_tray()
    if "--show" in sys.argv:
        root.after(200, win.show)
    root.mainloop()
    drv.stop()
    log.info("driver gestopt")


if __name__ == "__main__":
    main()
