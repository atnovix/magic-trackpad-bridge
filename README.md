# MagicTrackpadBridge

Apple Magic Trackpad 1 (A1339, alleen klassiek Bluetooth) bruikbaar maken op Windows 11 met Secure Boot aan, zonder kernel-driver.

Windows ziet het trackpad zelf alleen als muis (cursor + linkerklik): de muis-collectie is voor programma's afgeschermd en de multitouch-reports staan niet in de HID-descriptor. Daarom leest een **ESP32** (TTGO, ESP32-D0WDQ6) het trackpad uit als Bluetooth-HID-host, zet het in multitouch-modus en stuurt de vingerposities via USB-serieel naar de laptop.

```
Magic Trackpad 1  --Bluetooth-->  ESP32 (firmware-esp32)  --USB-serieel 921600 baud-->  laptop (tools/, later achtergrondprogramma)
```

## Mappen

- `firmware-esp32/` — PlatformIO-project (framework ESP-IDF). Bouwen: `pio run`, flashen: `pio run -t upload` (poort COM3).
- `tools/serial_tail.py` — N seconden meelezen op de seriële poort (`python serial_tail.py COM3 10 --reset`).
- `tools/visualizer.py` — live vingerweergave (`python visualizer.py COM3`).

## Protocol trackpad (uit Linux `hid-magicmouse.c`)

- Multitouch aanzetten: feature-report `D7 01`.
- Daarna input-report `0x28`: 4 bytes header (byte 1 bit 0 = knop, 18-bit tijdstempel) + 9 bytes per vinger:
  x en y 13-bit signed, tracking-id, touch major/minor, size, oriëntatie, state (0 = los).
- Bereik: X −2909..3167, Y −2456..2565 (130 × 110 mm). Accu: feature-report `0x47`, byte 1 = procent.

## Regelformaat ESP32 → laptop

```
F <knop> <ts> <n> <id>,<x>,<y>,<state>,<major>,<minor>,<size>,<orient> ...
M <knoppen> <dx> <dy>      (muis-report: multitouch nog niet actief)
B <procent>                (accu)
S connected|disconnected|paired
R <hex>                    (onbekend report)
```
