"""Synthetische tests voor de gesture-engine (geen hardware nodig):  python test_gestures.py"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from gestures import Frame, GestureEngine


class Rec:
    def __init__(self):
        self.events = []

    def __call__(self, ev, **kw):
        self.events.append((ev, kw))

    def names(self):
        return [e for e, _ in self.events]


def touch(tid, x, y, state=4, major=60):
    return {"id": tid, "x": x, "y": y, "state": state, "major": major, "minor": 50, "size": 6}


def run(frames):
    rec = Rec()
    eng = GestureEngine(config.DEFAULTS, rec)
    t = 0.0
    for btn, touches in frames:
        eng.feed(Frame(t, btn, 0, touches))
        t += 0.01
    eng.tick(t + 0.2)
    return rec


def test_tap():
    rec = run([(0, [touch(1, 60, 50)])] * 8 + [(0, [])])
    assert rec.names() == ["session_begin", "tap", "session_end"], rec.names()
    assert rec.events[1][1]["fingers"] == 1


def test_two_finger_tap():
    rec = run([(0, [touch(1, 50, 50), touch(2, 70, 50)])] * 8 + [(0, [])])
    assert rec.events[1][0] == "tap" and rec.events[1][1]["fingers"] == 2, rec.events


def test_pointer_move():
    frames = [(0, [touch(1, 40 + i * 0.5, 50)]) for i in range(30)] + [(0, [])]
    rec = run(frames)
    moves = [kw for e, kw in rec.events if e == "pointer_move"]
    assert len(moves) >= 25, len(moves)
    assert all(abs(m["dx_mm"] - 0.5) < 1e-6 for m in moves)
    assert "tap" not in rec.names()


def test_scroll():
    frames = [(0, [touch(1, 50, 30 + i * 0.6), touch(2, 70, 30 + i * 0.6)]) for i in range(30)] + [(0, [])]
    rec = run(frames)
    n = rec.names()
    assert "scroll_begin" in n and "scroll_end" in n and n.count("scroll") >= 20, n
    assert "pinch_begin" not in n and "rotate_begin" not in n
    total = sum(kw["dy_mm"] for e, kw in rec.events if e == "scroll")
    assert total > 10, total
    assert rec.events[-2][1]["vy_mm_s"] > 30


def test_pinch():
    frames = [(0, [touch(1, 60 - i * 0.4, 50), touch(2, 60 + i * 0.4, 50)]) for i in range(30)] + [(0, [])]
    rec = run(frames)
    n = rec.names()
    assert "pinch_begin" in n and "pinch_end" in n, n
    assert "scroll_begin" not in n
    assert sum(kw["d_mm"] for e, kw in rec.events if e == "pinch") > 15


def test_rotate():
    frames = []
    for i in range(40):
        a = math.radians(i * 1.5)
        frames.append((0, [touch(1, 60 - 15 * math.cos(a), 50 - 15 * math.sin(a)),
                           touch(2, 60 + 15 * math.cos(a), 50 + 15 * math.sin(a))]))
    frames.append((0, []))
    rec = run(frames)
    n = rec.names()
    assert "rotate_begin" in n and "rotate_end" in n, n
    assert "scroll_begin" not in n and "pinch_begin" not in n, n
    assert sum(kw["d_deg"] for e, kw in rec.events if e == "rotate") > 30


def test_swipe3():
    frames = [(0, [touch(1, 30 + i, 40), touch(2, 40 + i, 50), touch(3, 50 + i, 60)]) for i in range(20)] + [(0, [])]
    rec = run(frames)
    sw = [kw for e, kw in rec.events if e == "swipe"]
    assert len(sw) == 1 and sw[0] == {"fingers": 3, "direction": "right"}, sw
    assert "tap" not in rec.names()


def test_swipe4_up():
    frames = [(0, [touch(k, 30 + 10 * k, 80 - i) for k in range(1, 5)]) for i in range(20)] + [(0, [])]
    rec = run(frames)
    sw = [kw for e, kw in rec.events if e == "swipe"]
    assert sw == [{"fingers": 4, "direction": "up"}], sw


def test_tap_drag():
    frames = [(0, [touch(1, 60, 50)])] * 6 + [(0, [])] * 10   # 100 ms los, dan opnieuw neer
    frames += [(0, [touch(1, 60 + i * 0.5, 50)]) for i in range(20)] + [(0, [])]
    rec = run(frames)
    n = rec.names()
    assert n[1] == "tap", n
    i = n.index("drag")
    assert rec.events[i][1]["down"] is True
    assert n[-2] == "drag" and rec.events[-2][1]["down"] is False, n
    assert "pointer_move" in n


def test_physical_button():
    frames = [(0, [touch(1, 60, 50)])] * 3 + [(1, [touch(1, 60, 50)])] * 5 + [(0, [touch(1, 60, 50)])] * 2 + [(0, [])]
    rec = run(frames)
    btns = [kw for e, kw in rec.events if e == "button"]
    assert btns == [{"name": "left", "down": True}, {"name": "left", "down": False}], btns


def test_palm_ignored():
    rec = run([(0, [touch(1, 60, 50, major=200)])] * 8 + [(0, [])])
    assert rec.names() == [], rec.names()


def test_two_to_one_no_jump():
    frames = [(0, [touch(1, 50, 50), touch(2, 70, 50)])] * 5
    frames += [(0, [touch(1, 50 + i, 50)]) for i in range(10)] + [(0, [])]
    rec = run(frames)
    assert "pointer_move" not in rec.names(), rec.names()


def test_hold():
    rec = run([(0, [touch(1, 120, 5)])] * 90 + [(0, [])])
    n = rec.names()
    assert "hold" in n and "tap" not in n, n


def test_numpad_click_types_key():
    rec = Rec()
    eng = GestureEngine(config.DEFAULTS, rec)
    eng.numpad = True
    t = 0.0
    for btn in [0, 0, 1, 1, 1, 0, 0]:
        eng.feed(Frame(t, btn, 0, [touch(1, 60, 50)])); t += 0.01
    eng.feed(Frame(t, 0, 0, []))
    eng.tick(t + 0.2)
    n = rec.names()
    assert "button" not in n and n.count("tap") == 1, n


def test_hold_with_physical_click_in_toggle_cell():
    rec = Rec()
    eng = GestureEngine(config.DEFAULTS, rec)
    eng.toggle_cell = lambda x, y: x > 110 and y < 15
    t = 0.0
    for i in range(90):
        eng.feed(Frame(t, 1 if i >= 2 else 0, 0, [touch(1, 124, 5)])); t += 0.01
    eng.feed(Frame(t, 0, 0, [touch(1, 124, 5)])); t += 0.01
    eng.feed(Frame(t, 0, 0, []))
    eng.tick(t + 0.2)
    n = rec.names()
    assert "hold" in n and "button" not in n, n


def test_short_physical_click_in_toggle_cell_is_deferred_click():
    rec = Rec()
    eng = GestureEngine(config.DEFAULTS, rec)
    eng.toggle_cell = lambda x, y: x > 110 and y < 15
    t = 0.0
    for btn in [0, 1, 1, 1, 0, 0]:
        eng.feed(Frame(t, btn, 0, [touch(1, 124, 5)])); t += 0.01
    eng.feed(Frame(t, 0, 0, []))
    eng.tick(t + 0.2)
    btns = [kw for e, kw in rec.events if e == "button"]
    assert btns == [{"name": "left", "down": True}, {"name": "left", "down": False}], btns
    assert "hold" not in rec.names()


def test_liftoff_glitch_is_one_tap():
    # één frame zonder contact midden in een tik, daarna hetzelfde contact terug: één tik, geen twee
    frames = [(0, [touch(1, 60, 50)])] * 5 + [(0, [])] + [(0, [touch(2, 60, 50)])] * 4 + [(0, [])]
    rec = run(frames)
    assert rec.names().count("tap") == 1 and rec.names().count("session_begin") == 1, rec.names()


def test_hold_then_liftoff_glitch_no_extra_tap():
    frames = [(0, [touch(1, 124, 5)])] * 90 + [(0, [])] + [(0, [touch(3, 124, 5)])] * 3 + [(0, [])]
    rec = run(frames)
    n = rec.names()
    assert "hold" in n and "tap" not in n, n
    assert rec.events[-1][0] == "session_end" and rec.events[-1][1]["hold"] is True


def test_parse_line():
    fr = Frame.parse("F 1 123 2 3,-1187,373,4,83,102,6,0 4,-147,-122,4,64,77,5,0", 0.0)
    assert fr.btn == 1 and len(fr.touches) == 2
    assert abs(fr.touches[0]["x"] - (-1187 + 2909) / config.UNITS_PER_MM) < 1e-9


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for tfn in tests:
        try:
            tfn()
            print("ok  ", tfn.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL", tfn.__name__, e)
    print(f"{len(tests) - failed}/{len(tests)} geslaagd")
    sys.exit(1 if failed else 0)
