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
    exe = sys.executable
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return w if os.path.exists(w) else exe


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


# ---------------------------------------------------------------------- de driver zelf
class Driver:
    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = True
        self.lines = queue.Queue(maxsize=2000)
        self.output = Output(cfg, on_numpad_toggle=self._numpad_changed)
        self.engine = GestureEngine(cfg, self.output.handle)
        self.engine.numpad = self.output.numpad_on
        self.reader = BridgeReader(cfg["serial"]["port"], cfg["serial"]["baud"], self._on_line, self._on_status)
        self.port_open = False
        self.trackpad_connected = False
        self.battery = "?"
        self.frames = 0
        self.icon = None
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

    # -- verwerkingslus (eigen thread)
    def loop(self):
        while not self._stop.is_set():
            try:
                t, s = self.lines.get(timeout=0.005)
            except queue.Empty:
                self.output.tick(time.monotonic())
                continue
            if s.startswith("F "):
                self.frames += 1
                if self.enabled:
                    fr = Frame.parse(s, t)
                    if fr is not None:
                        self.engine.feed(fr)
            elif s.startswith("S "):
                self._status_line(s)
            elif s.startswith("B "):
                self.battery = s[2:].strip() + "%"
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
            log.info("trackpad verbroken")
            self._refresh_icon()
        elif body.startswith(("gap", "acl", "mode", "role", "link", "pkt")):
            log.info("esp32: %s", body)

    # -- besturing
    def start(self):
        self.reader.start()
        threading.Thread(target=self.loop, name="driver-loop", daemon=True).start()

    def stop(self):
        self._stop.set()
        self.reader.stop()

    def reload_config(self):
        try:
            cfg = config.load()
        except Exception as e:
            log.error("config herladen mislukt: %s", e)
            return
        self.cfg = cfg
        self.engine.cfg = cfg
        self.output.reload(cfg)
        log.info("config herladen")

    def set_numpad(self, on):
        self.output.set_numpad(on)
        self.engine.numpad = on
        self._refresh_icon()

    def set_calibrate(self, on):
        self.cfg["numpad"]["calibrate"] = bool(on)
        log.info("numpad-kalibratie %s (tik op de folie en kijk in het log)", "aan" if on else "uit")

    # -- tray
    def _icon_image(self):
        from PIL import Image, ImageDraw
        if not self.port_open:
            color = (140, 140, 140)
        elif not self.trackpad_connected:
            color = (230, 160, 40)
        elif self.output.numpad_on:
            color = (70, 130, 230)
        else:
            color = (60, 180, 90)
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((4, 10, 60, 54), radius=10, fill=color)
        d.rounded_rectangle((12, 18, 52, 46), radius=6, outline=(255, 255, 255), width=3)
        if self.output.numpad_on:
            for x in (22, 32, 42):
                for y in (25, 32, 39):
                    d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(255, 255, 255))
        if not self.enabled:
            d.line((8, 8, 56, 56), fill=(220, 50, 50), width=6)
        return img

    def _refresh_icon(self):
        if self.icon is None:
            return
        try:
            self.icon.icon = self._icon_image()
            state = "geen poort" if not self.port_open else ("wacht op trackpad" if not self.trackpad_connected else "verbonden")
            self.icon.title = f"Magic Trackpad: {state}, accu {self.battery}" + (", numpad" if self.output.numpad_on else "")
        except Exception:
            log.exception("tray-icoon bijwerken")

    def run_tray(self):
        import pystray
        from pystray import MenuItem as Item

        def toggle_enabled(icon, item):
            self.enabled = not self.enabled
            log.info("driver %s", "actief" if self.enabled else "uit")
            self._refresh_icon()

        def toggle_numpad(icon, item):
            self.set_numpad(not self.output.numpad_on)

        def toggle_calibrate(icon, item):
            self.set_calibrate(not self.cfg["numpad"].get("calibrate"))

        def toggle_autostart(icon, item):
            set_autostart(not autostart_enabled())

        def open_config(icon, item):
            if not os.path.exists(config.CONFIG_PATH):
                config.save(self.cfg)
            os.startfile(config.CONFIG_PATH)

        def open_log(icon, item):
            os.startfile(config.LOG_PATH)

        def open_visualizer(icon, item):
            viz = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "visualizer.py")
            self.reader.stop()
            subprocess.Popen([sys.executable, viz, self.cfg["serial"]["port"]])

        def quit_(icon, item):
            self.stop()
            icon.stop()

        menu = pystray.Menu(
            Item("Actief", toggle_enabled, checked=lambda i: self.enabled),
            Item("Numpad-modus", toggle_numpad, checked=lambda i: self.output.numpad_on),
            Item("Numpad-kalibratie (log)", toggle_calibrate, checked=lambda i: bool(self.cfg["numpad"].get("calibrate"))),
            pystray.Menu.SEPARATOR,
            Item("Autostart bij aanmelden", toggle_autostart, checked=lambda i: autostart_enabled()),
            Item("Config openen", open_config),
            Item("Config herladen", lambda i, it: self.reload_config()),
            Item("Log openen", open_log),
            pystray.Menu.SEPARATOR,
            Item("Herverbinden", lambda i, it: self.reader.reconnect()),
            Item("Visualizer starten (stopt de driver)", open_visualizer),
            Item("Afsluiten", quit_),
        )
        self.icon = pystray.Icon("MagicTrackpadBridge", self._icon_image(), "Magic Trackpad", menu)
        self._refresh_icon()
        self.icon.run()


def main():
    console = "--console" in sys.argv
    setup_logging(console)
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
    else:
        drv.run_tray()
    log.info("driver gestopt")


if __name__ == "__main__":
    main()
