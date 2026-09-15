"""Gesture-engine: zet multitouch-frames van de brug om in abstracte gebeurtenissen.

De engine weet niets van Windows; hij roept `emit(naam, **velden)` aan. Gebeurtenissen:
  pointer_move(dx_mm, dy_mm, dt)              één vinger beweegt
  button(name, down)                           fysieke klik (name = left/right/middle)
  tap(fingers, x_mm, y_mm)                     korte tik met n vingers
  drag(down)                                   tik-tik-vasthouden: slepen begint/eindigt (linkerknop)
  scroll_begin() / scroll(dx_mm, dy_mm, dt) / scroll_end(vx_mm_s, vy_mm_s)
  pinch_begin()  / pinch(d_mm)                 / pinch_end()
  rotate_begin() / rotate(d_deg)               / rotate_end()
  swipe(fingers, direction)                    3/4-vingerveeg: left/right/up/down
  hold(x_mm, y_mm)                             één vinger lang stil ingedrukt (numpad-schakelaar)
  session_begin(fingers) / session_end()       eerste vinger erop / laatste vinger eraf

Coördinaten in millimeter, met (0,0) linksboven op het trackpad; y groeit naar de gebruiker toe.
"""
import math
import time

from config import UNITS_PER_MM

X_MIN, Y_MIN = -2909, -2456


class Frame:
    __slots__ = ("t", "btn", "ts", "touches")

    def __init__(self, t, btn, ts, touches):
        self.t, self.btn, self.ts, self.touches = t, btn, ts, touches

    @staticmethod
    def parse(line, t=None):
        """'F <btn> <ts> <n> id,x,y,state,major,minor,size,orient ...' -> Frame of None."""
        parts = line.split()
        if len(parts) < 4 or parts[0] != "F":
            return None
        try:
            btn, ts, n = int(parts[1]), int(parts[2]), int(parts[3])
            touches = []
            for tok in parts[4:4 + n]:
                f = tok.split(",")
                if len(f) < 8:
                    continue
                tid, x, y, state, major, minor, size, orient = (int(v) for v in f[:8])
                touches.append({"id": tid, "x": (x - X_MIN) / UNITS_PER_MM, "y": (y - Y_MIN) / UNITS_PER_MM,
                                "state": state, "major": major, "minor": minor, "size": size})
        except ValueError:
            return None
        return Frame(time.monotonic() if t is None else t, btn, ts, touches)


class _Touch:
    __slots__ = ("id", "x", "y", "px", "py", "x0", "y0", "t0", "frames", "moved")

    def __init__(self, tid, x, y, t):
        self.id = tid
        self.x = self.px = self.x0 = x
        self.y = self.py = self.y0 = y
        self.t0 = t
        self.frames = 0
        self.moved = 0.0

    def update(self, x, y):
        self.px, self.py = self.x, self.y
        self.x, self.y = x, y
        self.frames += 1
        self.moved = max(self.moved, math.hypot(x - self.x0, y - self.y0))


def _wrap_deg(d):
    while d > 180:
        d -= 360
    while d < -180:
        d += 360
    return d


class GestureEngine:
    def __init__(self, cfg, emit):
        self.cfg = cfg
        self.emit = emit
        self.touches = {}          # id -> _Touch (alleen actieve contacten)
        self.session = None
        self.last_tap = None       # (t_end, fingers, x_mm, y_mm)
        self.drag = False
        self.btn_down = None       # naam van de knop die de fysieke klik nu vasthoudt
        self.last_t = None
        self.numpad = False        # in numpad-modus beweegt de cursor niet en is tik-tik-slepen uit
        self.lenient_tap = False   # numpad/kalibratie: ruimere tikgrenzen (typen gaat trager dan klikken)

    # ------------------------------------------------------------------ frames
    def feed(self, fr):
        c = self.cfg
        min_state = c["touch"]["touch_min_state"]
        palm = c["touch"]["palm_major"]
        dt = 0.01 if self.last_t is None else max(1e-3, fr.t - self.last_t)
        self.last_t = fr.t

        seen = set()
        for td in fr.touches:
            tid = td["id"]
            if td["state"] == 0:
                continue                      # losgelaten in dit frame
            if tid in self.touches:
                self.touches[tid].update(td["x"], td["y"])
                seen.add(tid)
            elif td["state"] >= min_state and td["major"] <= palm:
                self.touches[tid] = _Touch(tid, td["x"], td["y"], fr.t)
                seen.add(tid)
        for tid in [k for k in self.touches if k not in seen]:
            del self.touches[tid]

        n = len(self.touches)
        s = self.session

        if n > 0 and s is None:
            s = self.session = {"start": fr.t, "n": 0, "max_n": 0, "mode": None, "fired": False,
                                "suppress_pointer": False, "two": None, "swipe_base": None, "moved": 0.0,
                                "x0": None, "y0": None}
            first = next(iter(self.touches.values()))
            s["x0"], s["y0"] = first.x0, first.y0
            self.emit("session_begin", fingers=n)
            lt = self.last_tap
            if (n == 1 and not self.numpad and not self.lenient_tap and lt and lt[1] == 1
                    and fr.t - lt[0] < c["tap"]["double_tap_drag_ms"] / 1000.0
                    and math.hypot(first.x0 - lt[2], first.y0 - lt[3]) < c["tap"].get("double_tap_radius_mm", 6.0)):
                self.drag = True
                self.emit("drag", down=True)

        if s is not None and n != s["n"]:
            self._end_mode()
            if 0 < n < s["n"] and s["n"] >= 2:
                s["suppress_pointer"] = True
            s["n"] = n
            s["max_n"] = max(s["max_n"], n)
            s["two"] = self._two_baseline() if n == 2 else None
            s["swipe_base"] = self._centroid() if n in (3, 4) else None

        # fysieke klik
        if fr.btn and self.btn_down is None:
            if self.numpad and n >= 1:
                # in numpad-modus is de klik een toetsaanslag op de plek van de vinger, geen muisknop
                first = next(iter(self.touches.values()))
                self.btn_down = "numpad"
                s["fired"] = True
                self.emit("tap", fingers=1, x_mm=first.x, y_mm=first.y)
            else:
                name = c["tap"]["button_by_fingers"].get(str(max(n, 1)), "left")
                self.btn_down = name
                self.emit("button", name=name, down=True)
        elif not fr.btn and self.btn_down is not None:
            if self.btn_down != "numpad":
                self.emit("button", name=self.btn_down, down=False)
            self.btn_down = None

        # lang stil indrukken met één vinger (bijv. numpad-schakelaar op de folie)
        if (s is not None and n == 1 and not s["fired"] and not self.drag and self.btn_down is None
                and s["moved"] < c["tap"].get("hold_move_mm", 3.0)
                and fr.t - s["start"] > c["tap"].get("hold_ms", 700) / 1000.0):
            s["fired"] = True
            self.emit("hold", x_mm=s["x0"], y_mm=s["y0"])

        if s is not None and n > 0:
            s["moved"] = max(s["moved"], max(t.moved for t in self.touches.values()))
            if n == 1:
                self._pointer(dt)
            elif n == 2:
                self._two_finger(dt)
            elif n in (3, 4):
                self._swipe(n)

        if n == 0 and s is not None:
            self._end_mode()
            dur = fr.t - s["start"]
            if self.lenient_tap or self.numpad:
                max_move, max_ms = c["numpad"]["tap_move_mm"], c["numpad"]["tap_time_ms"]
            else:
                max_move, max_ms = c["tap"]["tap_move_mm"], c["tap"]["tap_time_ms"]
            is_tap = (not s["fired"] and s["mode"] is None and not self.drag
                      and s["moved"] < max_move and dur < max_ms / 1000.0)
            if self.drag:
                self.drag = False
                self.emit("drag", down=False)
                self.last_tap = None
            elif is_tap:
                self.emit("tap", fingers=s["max_n"], x_mm=s["x0"], y_mm=s["y0"])
                self.last_tap = (fr.t, s["max_n"], s["x0"], s["y0"])
            else:
                self.last_tap = None
            self.emit("session_end", fingers=s["max_n"], duration_ms=dur * 1000.0, moved_mm=s["moved"], tap=is_tap)
            self.session = None

    # ------------------------------------------------------------------ één vinger
    def _pointer(self, dt):
        s = self.session
        if s["suppress_pointer"] or self.numpad:
            return
        t = next(iter(self.touches.values()))
        if t.frames <= self.cfg["touch"]["settle_frames"]:
            return
        dx, dy = t.x - t.px, t.y - t.py
        if dx or dy:
            self.emit("pointer_move", dx_mm=dx, dy_mm=dy, dt=dt)

    # ------------------------------------------------------------------ twee vingers
    def _pair(self):
        a, b = sorted(self.touches.values(), key=lambda t: t.id)
        cx, cy = (a.x + b.x) / 2, (a.y + b.y) / 2
        d = math.hypot(b.x - a.x, b.y - a.y)
        ang = math.degrees(math.atan2(b.y - a.y, b.x - a.x))
        return cx, cy, d, ang

    def _two_baseline(self):
        cx, cy, d, ang = self._pair()
        return {"cx0": cx, "cy0": cy, "d0": d, "a0": ang, "cx": cx, "cy": cy, "d": d, "a": ang,
                "vx": 0.0, "vy": 0.0}

    def _two_finger(self, dt):
        s = self.session
        two = s["two"]
        if two is None:
            two = s["two"] = self._two_baseline()
            return
        cx, cy, d, ang = self._pair()
        tf = self.cfg["two_finger"]
        if s["mode"] is None:
            sc = math.hypot(cx - two["cx0"], cy - two["cy0"]) / tf["scroll_threshold_mm"]
            sp = abs(d - two["d0"]) / tf["pinch_threshold_mm"]
            sr = abs(_wrap_deg(ang - two["a0"])) / tf["rotate_threshold_deg"]
            best = max(sc, sp, sr)
            if best >= 1.0:
                s["mode"] = "scroll" if best == sc else ("pinch" if best == sp else "rotate")
                self.emit(s["mode"] + "_begin")
                two.update(cx=cx, cy=cy, d=d, a=ang)
                return
        mode = s["mode"]
        if mode == "scroll":
            dx, dy = cx - two["cx"], cy - two["cy"]
            # snelheid (mm/s) met exponentieel gemiddelde, voor traagheid na loslaten
            alpha = 0.4
            two["vx"] = alpha * (dx / dt) + (1 - alpha) * two["vx"]
            two["vy"] = alpha * (dy / dt) + (1 - alpha) * two["vy"]
            if dx or dy:
                self.emit("scroll", dx_mm=dx, dy_mm=dy, dt=dt)
        elif mode == "pinch":
            dd = d - two["d"]
            if dd:
                self.emit("pinch", d_mm=dd)
        elif mode == "rotate":
            da = _wrap_deg(ang - two["a"])
            if da:
                self.emit("rotate", d_deg=da)
        two.update(cx=cx, cy=cy, d=d, a=ang)

    def _end_mode(self):
        s = self.session
        if s is None or s["mode"] is None:
            return
        mode = s["mode"]
        if mode == "scroll":
            two = s["two"] or {}
            self.emit("scroll_end", vx_mm_s=two.get("vx", 0.0), vy_mm_s=two.get("vy", 0.0))
        else:
            self.emit(mode + "_end")
        s["mode"] = None
        s["fired"] = True

    # ------------------------------------------------------------------ drie/vier vingers
    def _centroid(self):
        ts = list(self.touches.values())
        return sum(t.x for t in ts) / len(ts), sum(t.y for t in ts) / len(ts)

    def _swipe(self, n):
        s = self.session
        if s["fired"] or s["swipe_base"] is None:
            return
        cx, cy = self._centroid()
        dx, dy = cx - s["swipe_base"][0], cy - s["swipe_base"][1]
        if math.hypot(dx, dy) < self.cfg["swipe"]["threshold_mm"]:
            return
        if abs(dx) >= abs(dy):
            direction = "right" if dx > 0 else "left"
        else:
            direction = "down" if dy > 0 else "up"
        s["fired"] = True
        self.emit("swipe", fingers=n, direction=direction)
