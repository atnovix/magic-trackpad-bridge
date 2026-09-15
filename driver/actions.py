"""Gebeurtenissen van de gesture-engine omzetten in Windows-invoer, volgens het profiel van het actieve programma."""
import logging
import math
import time

import config
import winput
from numpad import NumpadGrid

log = logging.getLogger("actions")


class Output:
    def __init__(self, cfg, on_numpad_toggle=None):
        self.cfg = cfg
        self.on_numpad_toggle = on_numpad_toggle
        self.numpad = NumpadGrid(cfg)
        self.numpad_on = bool(cfg["numpad"].get("enabled_at_start"))
        self.mods = winput.HeldModifiers()
        self.profile = config.profile_for(cfg, "")
        self.exe = ""
        self.rem = [0.0, 0.0]          # restjes pixels bij cursorbeweging
        self.acc = [0.0, 0.0]          # restjes wieleenheden
        self.held_button = None        # knop die een drag-gesture vasthoudt
        self.rot_acc = 0.0
        self.inertia = None            # {"vx","vy","t","spec"}

    def reload(self, cfg):
        self.cfg = cfg
        self.numpad.reload(cfg)

    # ------------------------------------------------------------------ dispatch
    def handle(self, ev, **kw):
        fn = getattr(self, "ev_" + ev, None)
        if fn is None:
            return
        try:
            fn(**kw)
        except Exception:
            log.exception("fout bij gebeurtenis %s %s", ev, kw)

    def ev_session_begin(self, fingers):
        self.inertia = None
        self.exe = winput.foreground_exe()
        self.profile = config.profile_for(self.cfg, self.exe)

    def ev_session_end(self, fingers=0, duration_ms=0.0, moved_mm=0.0, tap=False):
        self._release_gesture()
        if fingers == 1 and not tap and self.cfg["numpad"].get("calibrate"):
            log.info("KALIBRATIE geen tik: duur %.0f ms, verplaatsing %.1f mm (max %d ms / %.1f mm)", duration_ms, moved_mm,
                     self.cfg["numpad"]["tap_time_ms"], self.cfg["numpad"]["tap_move_mm"])

    # ------------------------------------------------------------------ cursor en klikken
    def ev_pointer_move(self, dx_mm, dy_mm, dt):
        p = self.cfg["pointer"]
        speed = math.hypot(dx_mm, dy_mm) / dt
        f = min(1.0, max(0.0, (speed - p["accel_start_mm_s"]) / p["accel_span_mm_s"]))
        gain = p["gain_px_per_mm"] + (p["max_gain_px_per_mm"] - p["gain_px_per_mm"]) * f
        self.rem[0] += dx_mm * gain
        self.rem[1] += dy_mm * gain
        px, py = int(self.rem[0]), int(self.rem[1])
        self.rem[0] -= px
        self.rem[1] -= py
        winput.mouse_move(px, py)

    def ev_button(self, name, down):
        (winput.mouse_down if down else winput.mouse_up)(name)

    def ev_drag(self, down):
        (winput.mouse_down if down else winput.mouse_up)("left")

    def ev_tap(self, fingers, x_mm, y_mm):
        if fingers == 1 and self.cfg["numpad"].get("calibrate"):
            log.info("KALIBRATIE tik op x=%.1f mm y=%.1f mm -> cel %s toets %s", x_mm, y_mm,
                     self.numpad.cell(x_mm, y_mm), self.numpad.key_at(x_mm, y_mm))
        if self.numpad_on and fingers == 1:
            key = self.numpad.key_at(x_mm, y_mm)
            if key == "numpad_toggle":
                self._run_action(key)
            elif key:
                winput.send_chord(key)
            return
        action = self.cfg["tap"]["actions"].get(str(fingers), "none")
        self._run_action(action)

    def ev_hold(self, x_mm, y_mm):
        # lang indrukken op de numpad-schakelaar van de folie zet de numpad-modus aan (of uit)
        if self.numpad.key_at(x_mm, y_mm) == "numpad_toggle":
            self._run_action("numpad_toggle")

    def _run_action(self, action):
        if not action or action == "none":
            return
        if action.startswith("click:"):
            winput.mouse_click(action.split(":", 1)[1])
        elif action.startswith("key:"):
            winput.send_chord(action.split(":", 1)[1])
        elif action == "numpad_toggle":
            self.set_numpad(not self.numpad_on)
            if self.on_numpad_toggle:
                self.on_numpad_toggle(self.numpad_on)
        else:
            log.warning("onbekende actie %r", action)

    def set_numpad(self, on):
        self.numpad_on = bool(on)
        log.info("numpad-modus %s", "aan" if self.numpad_on else "uit")

    # ------------------------------------------------------------------ twee vingers
    def _begin(self, spec):
        self.mods.hold(spec.get("modifiers"))
        if spec["type"] == "drag":
            self.held_button = spec.get("button", "middle")
            winput.mouse_down(self.held_button)
        self.acc = [0.0, 0.0]
        self.rot_acc = 0.0

    def _release_gesture(self):
        if self.held_button:
            winput.mouse_up(self.held_button)
            self.held_button = None
        self.mods.release()

    def _wheel_units(self, idx, mm):
        """mm omzetten in gehele wieleenheden, met rest-accumulatie per as."""
        self.acc[idx] += mm
        units = int(self.acc[idx])
        self.acc[idx] -= units
        return units

    def ev_scroll_begin(self):
        self._begin(self.profile["scroll"])

    def ev_scroll(self, dx_mm, dy_mm, dt):
        spec = self.profile["scroll"]
        sign = 1 if spec.get("natural", True) else -1
        if spec["type"] == "wheel":
            g = spec.get("gain", 40.0)
            # standaard: vinger omlaag = wiel omlaag (negatief); natural keert dat om
            v = self._wheel_units(1, sign * dy_mm * g)
            winput.wheel(v)
            if spec.get("horizontal", True):
                h = self._wheel_units(0, -sign * dx_mm * g)
                winput.wheel(h, horizontal=True)
        elif spec["type"] == "drag":
            g = spec.get("gain", 12.0)
            s = -1 if spec.get("natural", False) else 1
            self.rem[0] += s * dx_mm * g
            self.rem[1] += s * dy_mm * g
            px, py = int(self.rem[0]), int(self.rem[1])
            self.rem[0] -= px
            self.rem[1] -= py
            winput.mouse_move(px, py)

    def ev_scroll_end(self, vx_mm_s, vy_mm_s):
        spec = self.profile["scroll"]
        self._release_gesture()
        ine = self.cfg["inertia"]
        if spec["type"] == "wheel" and ine["enabled"] and math.hypot(vx_mm_s, vy_mm_s) >= ine["min_speed_mm_s"]:
            self.inertia = {"vx": vx_mm_s, "vy": vy_mm_s, "t": time.monotonic(), "spec": spec}

    def ev_pinch_begin(self):
        self._begin(self.profile["pinch"])

    def ev_pinch(self, d_mm):
        spec = self.profile["pinch"]
        s = -1 if spec.get("invert") else 1
        if spec["type"] == "wheel":
            winput.wheel(self._wheel_units(1, s * d_mm * spec.get("gain", 50.0)))
        elif spec["type"] == "drag":
            self._axis_move(spec, s * d_mm * spec.get("gain", 10.0))
        elif spec["type"] == "keys":
            self._step_keys(spec, d_mm, spec.get("step_mm", 4.0), "in", "out")

    def ev_pinch_end(self):
        self._release_gesture()

    def ev_rotate_begin(self):
        self._begin(self.profile["rotate"])

    def ev_rotate(self, d_deg):
        spec = self.profile["rotate"]
        s = -1 if spec.get("invert") else 1
        if spec["type"] == "drag":
            self._axis_move(spec, s * d_deg * spec.get("gain", 4.0))
        elif spec["type"] == "keys":
            self._step_keys(spec, d_deg, spec.get("step_deg", 15.0), "cw", "ccw")

    def ev_rotate_end(self):
        self._release_gesture()

    def _axis_move(self, spec, px_float):
        idx = 1 if spec.get("axis", "x") == "y" else 0
        self.rem[idx] += px_float
        px = int(self.rem[idx])
        self.rem[idx] -= px
        winput.mouse_move(px if idx == 0 else 0, px if idx == 1 else 0)

    def _step_keys(self, spec, delta, step, pos_name, neg_name):
        self.rot_acc += delta
        while self.rot_acc >= step:
            self.rot_acc -= step
            winput.send_chord(spec.get(pos_name, "none"))
        while self.rot_acc <= -step:
            self.rot_acc += step
            winput.send_chord(spec.get(neg_name, "none"))

    # ------------------------------------------------------------------ vegen
    def ev_swipe(self, fingers, direction):
        table = self.profile.get(f"swipe{fingers}", {})
        chord = table.get(direction, "none")
        log.info("veeg %d vingers %s -> %s (%s)", fingers, direction, chord, self.exe)
        if chord == "numpad_toggle":
            self._run_action(chord)
        else:
            winput.send_chord(chord)

    # ------------------------------------------------------------------ traagheid
    def tick(self, now):
        ine = self.inertia
        if ine is None:
            return
        dt = now - ine["t"]
        if dt <= 0:
            return
        ine["t"] = now
        cfg = self.cfg["inertia"]
        spec = ine["spec"]
        sign = 1 if spec.get("natural", True) else -1
        g = spec.get("gain", 40.0)
        winput.wheel(self._wheel_units(1, sign * ine["vy"] * dt * g))
        if spec.get("horizontal", True):
            winput.wheel(self._wheel_units(0, -sign * ine["vx"] * dt * g), horizontal=True)
        k = cfg["decay_per_s"] ** dt
        ine["vx"] *= k
        ine["vy"] *= k
        if math.hypot(ine["vx"], ine["vy"]) < cfg["stop_speed_mm_s"]:
            self.inertia = None
