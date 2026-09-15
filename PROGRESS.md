# Voortgang MagicTrackpadBridge

Stand: dinsdag 15 september 2026, 20:45.

## Wat werkt

- De ESP32 (TTGO, ESP32-D0WDQ6) koppelt met het trackpad, zet het met feature-report `D7 01` in multitouch-modus en decodeert report `0x28`.
- Vingerposities gaan als `F`-regels over USB-serieel (921600 baud) naar de laptop; `tools/visualizer.py` tekent ze live.
- Eén en twee vingers werkten in v2 soepel. Printen loopt via een aparte taak met wachtrij (`drop=0`).
- **Firmware v4 is op 15-09-2026 geflasht en draait.** Bij een reset verbond het trackpad binnen 5 s zélf; de link bleef
  in actieve modus (`mode=0`, geen sniff-omschakeling meer) en het bordje is master. Multitouch-commando en accu (100 %) OK.
  De 3/4-vingertest met v4 is nog NIET gedaan (niemand aan het trackpad).

## Analyse van de fout van 6 september (v2, `tools/bridge.log`)

Twee losse problemen:

1. **3+ vingers: frames vallen weg in de Bluetooth-link, niet in de brug.** Van 2054 frames waren er 22 met drie en 31 met
   vier vingers, `drop=0`, geen L2CAP-fouten. Patroon in de log: bij 3 of 4 vingers komen steeds 4–5 frames vlak na
   elkaar binnen (trackpad-tijdstempels opeenvolgend), daarna niets meer zolang de vingers blijven liggen; pas bij
   optillen/neerzetten weer een korte burst. Een- en tweevingerframes (13 en 22 bytes) passen in één DH1-basebandpakket,
   drie- en viervingerframes (31/40 bytes) niet. Direct na elke verbinding meldde de controller
   `hcif mode change: mode 2, intv 18`: het trackpad zet de link in **sniffmodus met interval 18 slots (11,25 ms)** en de
   link bleef daar de hele sessie in. In die modus krijgt het trackpad per anchorpunt maar (bijna) één pakket kwijt;
   frames uit twee pakketten lopen vast. Bluedroid zelf zou pas na 30 s sniff vragen (54/30 slots), dus het verzoek
   kwam van het trackpad. Fix in v4: link policy zonder sniff/hold/park (controller wijst het LMP-sniffverzoek af),
   eigen registratie bij de Bluedroid power manager met eis "actief" (wint van alle andere partijen), master-rol vragen,
   alle ACL-pakkettypes toestaan. Bevestigd bij de eerste verbinding met v4: geen moduswissel meer.
2. **Verbinding valt weg en blijft op `disconnected`.** Race: ons eigen `esp_bt_hid_host_connect` liep nog (SDP) toen het
   trackpad zelf al de HID-kanalen opende. De uitstaande poging eindigde 5 s later in `conn complete st 0x4` (page
   timeout), waarop Bluedroid het apparaat sloot en L2CAP de link vergat, terwijl de basebandlink bleef staan: het trackpad
   bleef op 100 Hz zenden naar `unknown handle:128` en elke nieuwe poging gaf `Conn Exists`, tot de supervision-timeout
   na ~2 min. Fix in v4: met een koppelsleutel in NVS eerst 30 s wachten tot het trackpad zelf verbindt (bij aanraken),
   nooit zelf verbinden zolang er een ACL staat, en bij "HID dicht maar ACL nog open" de ACL zelf afbreken.

## Nieuw in v4 (`firmware-esp32/src/main.c`)

- Diagnostiek: `S mode`, `S link`, `S role`, `S pkt`, `S acl up/down`, `S gap n=<vingers> ms=<gat>` (gat > 150 ms terwijl
  er vingers lagen = verloren frames) en uitgebreide `S stats` (bytes, stalls, mode, role).
- Testcommando's over dezelfde seriële poort (één letter, in de viewer gewoon de toets indrukken): `?` toestand,
  `a`/`s` sniff weigeren/toestaan, `m`/`l` master/slave, `9`/`1` alle pakkettypes / alleen 1-slot, `c` zelf verbinden,
  `d` HID verbreken, `x` ACL afbreken, `t` D7 01 opnieuw, `b` accu, `z` tellers op nul.
- `tools/visualizer.py`: standaard 921600 baud, toetsen gaan als commando naar het bordje, teller "gaten" in de statusbalk.

## Volgende stappen

1. `python tools/visualizer.py COM3` starten, trackpad aanraken (verbindt zelf) en testen: 1, 2, 3, 4 en 5 vingers,
   ook 3 vingers ruim een seconde stil laten liggen. Kijk naar `n3`/`n4`/`n5`, `stalls` en `S gap`-regels.
2. Werkt 3+ nog niet: in de viewer `1` (alleen 1-slot pakketten) en daarna `9` proberen; `l` (slave) versus `m`;
   `s` om te bewijzen dat sniff de oorzaak is (verwachting: dan weer bursts van 4 frames).
3. Als de link stabiel is: achtergrondprogramma op de laptop dat `F`-regels vertaalt naar gestures (scrollen, rechtsklik,
   zoom) en het NUM20-numpadraster (Mobee-folie).
4. Op termijn: Raspberry Pi Pico W (klassiek Bluetooth én native USB) zodat het bordje zich als echt Precision Touchpad
   kan aanmelden; de ESP32 kan dat niet.

## Testopstelling

- Trackpad eerst uit Windows verwijderen (Instellingen > Bluetooth en apparaten), anders blijft Windows verbinden.
- Koppelmodus (alleen bij eerste keer of na wissen NVS): trackpad uit, knop ingedrukt houden tot het groene lampje
  knippert; de ESP32 verbindt dan zelf (geen koppelsleutel → na 3 s).
- Toolchain: PlatformIO met ESP-IDF 6.0.1 (`pio run -t upload`, COM3). Let op: het openen van de seriële poort reset het bordje.
- Logs: `tools/bridge.log` (viewer), `firmware-esp32/build.log`, `firmware-esp32/upload.log`. Deze staan in `.gitignore`.
