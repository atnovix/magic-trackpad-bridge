# MagicTrackpadBridge

Apple Magic Trackpad 1 (A1339, alleen klassiek Bluetooth) bruikbaar maken op Windows 11 met Secure Boot aan, zonder kernel-driver.

Windows ziet het trackpad zelf alleen als muis (cursor + linkerklik): de muis-collectie is voor programma's afgeschermd en de multitouch-reports staan niet in de HID-descriptor. Daarom leest een **ESP32** (TTGO, ESP32-D0WDQ6) het trackpad uit als Bluetooth-HID-host, zet het in multitouch-modus en stuurt de vingerposities via USB-serieel naar de laptop.

```
Magic Trackpad 1  --Bluetooth-->  ESP32 (firmware-esp32)  --USB-serieel 921600 baud-->  laptop (driver/: muis, gestures, numpad)
```

## Mappen

- `firmware-esp32/` — PlatformIO-project (framework ESP-IDF). Bouwen: `pio run`, flashen: `pio run -t upload` (poort COM3).
  Firmware v4 houdt de link uit de sniffmodus (anders vallen frames met 3+ vingers weg) en kent testcommando's over de
  seriële poort (`?` voor de lijst).
- `driver/` — het Windows-achtergrondprogramma (Python, alleen `pyserial`, `pystray`, `Pillow`). Zie hieronder.
- `tools/serial_tail.py` — N seconden meelezen op de seriële poort (`python serial_tail.py COM3 10 --reset`).
- `tools/visualizer.py` — live vingerweergave (`python visualizer.py COM3`); toetsen in het venster gaan als commando naar de ESP32.

## Driver (Windows)

```
pip install pyserial pystray pillow
pythonw driver	rackpad_driver.py          # tray-icoon; python ... --console voor log in de console
```

Windows ziet het trackpad zelf niet meer (de ESP32 is de Bluetooth-host), dus de driver doet alles via `SendInput`:

| Vingers | Actie |
|---|---|
| 1 | cursor (met versnelling), tik = klik, tik-tik-vasthouden = slepen, fysieke klik = linkerknop |
| 2 | tik = rechtsklik; schuiven = scrollen (natural, met traagheid), knijpen = zoom (Ctrl+wiel), draaien = per profiel |
| 3 | tik = middelste klik; veeg links/rechts = vorig/volgend venster (Alt+Tab), omhoog = taakweergave, omlaag = bureaublad |
| 4 | tik = numpad-modus aan/uit; veeg links/rechts = virtueel bureaublad wisselen |

**Tray-icoon**: groen = trackpad-modus, blauw met toetsen = numpad-modus, oranje = wacht op het trackpad, grijs = geen
seriële poort. Linksklik opent een flyout in Windows 11-stijl bij het icoon (zoals het wifi-paneel): status en accu,
tegels voor trackpad/numpad/actief, schuifregelaars voor cursor- en scrollsnelheid, schakelaars voor natuurlijk
scrollen, tikken en de Fusion-richtingen, en autostart. Het paneel volgt het lichte/donkere thema en de accentkleur
van Windows en sluit bij een klik ernaast. "Meer instellingen" opent het uitgebreide venster (`driver/ui.py`).
Rechtsklik geeft een kort menu.
De driver draait als één exemplaar (mutex), zonder console, en herstelt zelf bij een weggevallen poort.

Profiel **Fusion 360** (`fusion360.exe`): twee vingers schuiven = pannen (middelste knop slepen), knijpen = zoom (wiel),
draaien = orbit (Shift + middelste knop). Profielen, gains en toetscombinaties staan in
`config.json` in de projectmap (tray-menu > Config openen, daarna Config herladen). Andere programma's
krijgen een eigen profiel door hun exe-naam als sleutel onder `profiles` te zetten.

**Numpad-modus** (Mobee NUM20-folie): aan met een vier-vinger-tik of door het schuifknopje rechtsboven op de folie ~0,7 s
ingedrukt te houden; uit met een tik op datzelfde knopje of weer vier vingers. Een fysieke klik typt in numpad-modus de toets onder de vinger.
Het raster (7 kolommen x 6 rijen, `numpad.rows`) is gekalibreerd op de folie: F13-F17, raster-icoon = taakweergave,
schuifknop = terug naar muis; lege toets, home, page up, clear (= backspace), = / *; del, end, page down, 7 8 9 -;
4 5 6 +; pijl omhoog, 1 2 3 enter; pijlen links/omlaag/rechts, 0 . enter. Klopt een toets niet: zet in het tray-menu
"Numpad-kalibratie" aan, tik, lees in het log welke cel geraakt wordt en pas `rows`, `x_mm` of `y_mm` aan. Autostart bij aanmelden staat in het tray-menu (registersleutel HKCU\...\Run).

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
