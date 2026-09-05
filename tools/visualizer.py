"""Live weergave van de vingers op het Magic Trackpad, via de ESP32-brug op de seriële poort.

Gebruik:  python visualizer.py [COMx]
Sluiten: venster sluiten of Esc.
"""
import os, sys, threading, queue, time
import tkinter as tk
import serial

PORT = next((a for a in sys.argv[1:] if a.upper().startswith("COM")), "COM3")
BAUD = next((int(a) for a in sys.argv[1:] if a.isdigit()), 115200)
LOGFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge.log")

# Bereik van het trackpad in apparaat-eenheden (Linux hid-magicmouse); 130 x 110 mm
X_MIN, X_MAX = -2909, 3167
Y_MIN, Y_MAX = -2456, 2565
W, H = 650, 550

q = queue.Queue()

def reader():
    logf = open(LOGFILE, "a", encoding="utf-8")
    nframes = 0
    while True:
        try:
            with serial.Serial(PORT, BAUD, timeout=0.2) as ser:
                ser.dtr = False; ser.rts = False
                q.put(("status", f"verbonden met {PORT} @ {BAUD}"))
                while True:
                    line = ser.readline()
                    if not line:
                        continue
                    s = line.decode("utf-8", errors="replace").strip()
                    if s.startswith("F "):
                        nframes += 1
                        parts = s.split(" ", 4)
                        many = len(parts) > 3 and parts[3].isdigit() and int(parts[3]) >= 3
                        if many or nframes % 20 == 1:  # alles met 3+ vingers loggen, anders 1 op 20
                            logf.write(s + "\n"); logf.flush()
                    elif s:
                        logf.write(time.strftime("%H:%M:%S ") + s + "\n"); logf.flush()
                    if s[:2] in ("F ", "M ", "B ", "S "):
                        q.put(("line", s))
                    elif s.startswith(("W (", "E (")) or "bridge:" in s:
                        q.put(("log", s))
        except serial.SerialException as e:
            q.put(("status", f"seriële poort: {e}"))
            time.sleep(2)

root = tk.Tk()
root.title(f"Magic Trackpad via ESP32 ({PORT})")
canvas = tk.Canvas(root, width=W, height=H, bg="#202020", highlightthickness=0)
canvas.pack()
info = tk.Label(root, text="wachten op data...", anchor="w", font=("Consolas", 10), fg="#ddd", bg="#111")
info.pack(fill="x")
log = tk.Label(root, text="", anchor="w", font=("Consolas", 9), fg="#9ad", bg="#111")
log.pack(fill="x")
root.bind("<Escape>", lambda e: root.destroy())

state = {"btn": 0, "battery": "?", "status": "-", "frames": 0, "t0": time.time(), "fps": 0.0, "last": time.time()}
items = []

def to_px(x, y):
    # y groeit naar beneden (richting gebruiker), net als op Linux
    px = (x - X_MIN) / (X_MAX - X_MIN) * W
    py = (y - Y_MIN) / (Y_MAX - Y_MIN) * H
    return px, py

def draw_frame(parts):
    for it in items:
        canvas.delete(it)
    items.clear()
    btn = int(parts[1]); n = int(parts[3])
    state["btn"] = btn
    canvas.configure(bg="#3a2a2a" if btn else "#202020")
    for tok in parts[4:4 + n]:
        f = tok.split(",")
        if len(f) < 8:
            continue
        fid, x, y, st, major, minor, size, orient = (int(v) for v in f[:8])
        px, py = to_px(x, y)
        r = max(6, major / 2)
        color = "#5c5" if st else "#888"
        items.append(canvas.create_oval(px - r, py - r, px + r, py + r, outline=color, width=2))
        items.append(canvas.create_text(px, py - r - 10, text=f"{fid}", fill="#eee", font=("Consolas", 10)))
        items.append(canvas.create_text(px, py + r + 10, text=f"{x},{y}", fill="#aaa", font=("Consolas", 8)))

def tick():
    got = 0
    while True:
        try:
            kind, s = q.get_nowait()
        except queue.Empty:
            break
        got += 1
        if kind == "line":
            if s.startswith("F "):
                parts = s.split(" ")
                state["frames"] += 1
                now = time.time()
                dt = now - state["last"]; state["last"] = now
                if dt > 0:
                    state["fps"] = 0.9 * state["fps"] + 0.1 * (1 / dt)
                draw_frame(parts)
            elif s.startswith("B "):
                state["battery"] = s[2:] + "%"
            elif s.startswith("S "):
                state["status"] = s[2:]
            elif s.startswith("M "):
                state["status"] = "muismodus (nog geen multitouch): " + s
        elif kind in ("log", "status"):
            log.configure(text=s[-110:])
    info.configure(text=f"status: {state['status']}   accu: {state['battery']}   frames: {state['frames']}   ~{state['fps']:.0f} Hz   knop: {'INGEDRUKT' if state['btn'] else '-'}")
    root.after(15, tick)

threading.Thread(target=reader, daemon=True).start()
tick()
root.mainloop()
