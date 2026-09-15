"""Lees N seconden van de seriële poort van de ESP32-brug en print de regels.

Gebruik:  python serial_tail.py [poort] [seconden] [baud] [--reset] [--raw]
  --reset  : pulseer DTR/RTS zodat de ESP32 herstart en je de opstartlog ziet
  --raw    : ook ESP-IDF-logregels tonen (standaard: alleen F/M/B/S/R-regels + waarschuwingen)
"""
import sys, time
import serial

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

port = next((a for a in sys.argv[1:] if a.upper().startswith("COM")), "COM3")
secs = next((float(a) for a in sys.argv[1:] if a.replace(".", "", 1).isdigit()), 10.0)
baud = 921600
for a in sys.argv[1:]:
    if a.isdigit() and int(a) >= 9600:
        baud = int(a)
        secs = next((float(b) for b in sys.argv[1:] if b.replace(".", "", 1).isdigit() and b != a), secs)
reset = "--reset" in sys.argv
raw = "--raw" in sys.argv

with serial.Serial(port, baud, timeout=0.2) as ser:
    if reset:
        # esptool-achtige resetpuls: EN laag via RTS
        ser.dtr = False; ser.rts = True; time.sleep(0.1); ser.rts = False
    else:
        # DTR/RTS laag houden, anders houdt de CP2102 de ESP32 in reset/bootloader
        ser.dtr = False; ser.rts = False
    ser.reset_input_buffer()
    t_end = time.time() + secs
    counts = {}
    last_beat = 0.0
    while time.time() < t_end:
        if time.time() - last_beat >= 5:      # hartslag voor firmware v5
            last_beat = time.time(); ser.write(b"k")
        line = ser.readline()
        if not line:
            continue
        s = line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not s:
            continue
        key = s[0]
        counts[key] = counts.get(key, 0) + 1
        if raw or key in "FMBSR" or s.startswith(("W (", "E (")) or "bridge:" in s:
            # F-regels kunnen heel snel komen; toon er maximaal 1 per 10
            if key == "F" and not raw and counts[key] % 10 != 1:
                continue
            print(s, flush=True)
    print(f"-- klaar; regels per type: {counts}", flush=True)
