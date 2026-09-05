# Voortgang MagicTrackpadBridge

Stand: zaterdag 6 september 2026, 00:15.

## Wat werkt

- De ESP32 (TTGO, ESP32-D0WDQ6) verbindt en koppelt automatisch met het trackpad op het vaste Bluetooth-adres, zet het met feature-report `D7 01` in multitouch-modus en decodeert report `0x28`.
- Vingerposities gaan als `F`-regels over USB-serieel (921600 baud) naar de laptop; `tools/visualizer.py` tekent ze live. Boven/onder klopt (Y-as omgedraaid in de viewer).
- Eén en twee vingers werken soepel. Printen loopt via een aparte taak met wachtrij, dus de Bluetooth-taak wacht nooit op de USB-poort (`drop=0` in de log).
- Elke 5 seconden komt een `S stats`-regel met aantallen frames per vingeraantal, zodat zichtbaar is of frames het bordje bereiken.

## Openstaand

- **Drie of meer vingers zijn erg traag / lijken te hangen.** Uit `tools/bridge.log` (00:11): 2054 frames, waarvan 22 met drie en 31 met vier vingers, 0 drops. De frames komen dus nauwelijks bij het bordje aan. Het zit in de Bluetooth-link (vermoedelijk de sniff-modus die het trackpad aanvraagt), niet in de seriële kant.
- **Verbinding valt soms weg en blijft op `disconnected`.** Trackpad uit- en aanzetten hielp.
- **Firmware v3 in `firmware-esp32/src/main.c` pakt dit aan, maar is nog NIET geflasht.** Wijzigingen: link policy zonder sniff/hold/park en actieve modus afdwingen (elke moduswissel wordt gelogd), alle ACL-pakkettypes toegestaan (`0xCC18`, inclusief EDR), rustiger herverbinden (8 s wachten op het trackpad, 10 s na een mislukte poging). De upload naar COM3 mislukte: "Could not open COM3, the port is busy or doesn't exist" (USB-kabel / CP2102 niet gezien). Een auto-flash-wachtlus stond te wachten tot de poort terugkwam.

## Volgende stappen

1. USB-kabel van het ESP32-bordje controleren; zodra COM3 terug is: `cd firmware-esp32 && pio run -t upload`.
2. `python tools/visualizer.py COM3` starten en de test herhalen: 1 vinger, 2 vingers, 3 vingers, 4 vingers. Let op `n3`/`n4` in de stats-regel en op moduswissel-logregels.
3. Als de link stabiel is: achtergrondprogramma op de laptop dat `F`-regels vertaalt naar gestures (scrollen, rechtsklik, zoom) en het NUM20-numpadraster (Mobee-folie).
4. Op termijn: Raspberry Pi Pico W (klassiek Bluetooth én native USB) zodat het bordje zich als echt Precision Touchpad kan aanmelden; de ESP32 kan dat niet.

## Testopstelling

- Trackpad eerst uit Windows verwijderen (Instellingen > Bluetooth en apparaten), anders blijft Windows verbinden.
- Koppelmodus: trackpad uit, knop ingedrukt houden tot het groene lampje knippert. De ESP32 probeert elke 5 s te verbinden.
- Toolchain: PlatformIO met ESP-IDF 6.0.1; de eerste build duurt enkele minuten (Bluedroid).
- Logs: `tools/bridge.log` (viewer), `firmware-esp32/build.log`, `firmware-esp32/upload.log`. Deze staan in `.gitignore`.
