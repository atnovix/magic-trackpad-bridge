# Voortgang MagicTrackpadBridge

Stand: dinsdag 15 september 2026, 22:00.

## Wat werkt

- De ESP32 (TTGO, ESP32-D0WDQ6) koppelt met het trackpad, zet het met feature-report `D7 01` in multitouch-modus en decodeert report `0x28`.
- Vingerposities gaan als `F`-regels over USB-serieel (921600 baud) naar de laptop; `tools/visualizer.py` tekent ze live.
- Eén en twee vingers werkten in v2 soepel. Printen loopt via een aparte taak met wachtrij (`drop=0`).
- **Firmware v4 is op 15-09-2026 geflasht en draait.** Bij een reset verbond het trackpad binnen 5 s zélf; de link bleef
  in actieve modus (`mode=0`, geen sniff-omschakeling meer) en het bordje is master. Multitouch-commando en accu (100 %) OK.
  Getest door de gebruiker: werkt, ook met 10 vingers.
- **Driver op de laptop (`driver/`, 15-09-2026):** cursor met versnelling, tik/tik-tik-slepen/fysieke klik, 2-vinger
  scrollen (natural, traagheid), pinch-zoom, draaien, 3/4-vingervegen, per-programma-profielen (Fusion 360: pannen,
  zoom, orbit), numpad-modus met kalibratie, tray-icoon met autostart. Gesture-engine is hardwareloos getest
  (`driver/test_gestures.py`, 21 tests). In de praktijk getest: muis, Fusion-gestures en numpad werken.
- **Flyout (driver/flyout.py):** linksklik op het tray-icoon opent een randloos paneel in Windows 11-stijl bij het icoon
  (thema en accentkleur uit het register, afgeronde hoeken via transparante kleur, tegels, schakelaars, schuifregelaars,
  sluit bij klik ernaast). "Meer instellingen" opent het uitgebreide venster.
- **Statusvenster en tray (15-09-2026 avond):** menu "Meer instellingen..." opent een venster met status (poort, trackpad,
  accu, modus, frames, profiel), modusknoppen en instellingen; icoon groen/blauw/oranje/grijs per toestand. Autostart
  bij aanmelden staat aan (HKCU Run, pythonw-alias in WindowsApps). Eén exemplaar tegelijk (mutex).
- **Numpad-schakelaar aanzetten betrouwbaar (25-09-2026):** aanzetten (lang stil op de cel rechtsboven) pakte lang niet
  altijd, uitzetten (tik) wel. Oorzaak: het trackpad meldt alleen veranderingen, dus een stil liggende vinger levert geen
  frames op en de hold werd alleen per frame gecontroleerd — hij vuurde pas bij het loslaten, als er al geen vinger meer
  lag. De hold komt nu ook uit `tick()` (`GestureEngine._check_hold`), dus puur op tijd. Daarnaast telt een tik tot
  `numpad.edge_margin_mm` (8 mm) buiten het raster mee voor de buitenste rij/kolom, en logt de driver een hold die
  naast de schakelaar valt (positie + cel). Tests: 21. Sinds dezelfde dag zet ook een korte tik op de schakelaarcel
  de numpad aan (zelfde gebaar als uitzetten); een tik daar is dus geen linkerklik meer, slepen/vasthouden blijft muis.
- **Status "wacht op het trackpad" terwijl alles werkt (25-09-2026):** het bordje meldt `S connected` alleen op het moment
  van verbinden. Start de driver opnieuw zonder dat het bordje reset, dan bleef het bolletje oranje. De driver zet de
  status nu ook op verbonden zodra er F-frames binnenkomen.

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

## Nieuw in v5 (geflasht 15-09-2026, 23:57)

- Hartslag: de laptop stuurt elke 5 s `k` (driver, visualizer en serial_tail). Zonder hartslag gedurende 60 s laat het
  bordje het trackpad los en zet het zichzelf op niet-verbindbaar; bij de eerste hartslag weer verbindbaar en zelf
  verbinden. Bij opstarten is het bordje niet verbindbaar tot de eerste hartslag.
- Stilstand: 10 s zonder frames -> sniff toegestaan (`S link ... active=0 (stilstand)`); eerste aanraking -> actief.

## Nieuw in v4 (`firmware-esp32/src/main.c`)

- Diagnostiek: `S mode`, `S link`, `S role`, `S pkt`, `S acl up/down`, `S gap n=<vingers> ms=<gat>` (gat > 150 ms terwijl
  er vingers lagen = verloren frames) en uitgebreide `S stats` (bytes, stalls, mode, role).
- Testcommando's over dezelfde seriële poort (één letter, in de viewer gewoon de toets indrukken): `?` toestand,
  `a`/`s` sniff weigeren/toestaan, `m`/`l` master/slave, `9`/`1` alle pakkettypes / alleen 1-slot, `c` zelf verbinden,
  `d` HID verbreken, `x` ACL afbreken, `t` D7 01 opnieuw, `b` accu, `z` tellers op nul.
- `tools/visualizer.py`: standaard 921600 baud, toetsen gaan als commando naar het bordje, teller "gaten" in de statusbalk.

## Volgende stappen

1. Driver in de praktijk tunen: `python driver	rackpad_driver.py --console`, cursorsnelheid (`pointer`), tikdrempels,
   scroll/pinch/rotate-drempels en de Fusion-gains in `config.json` in de projectmap.
2. NUM20-raster is gekalibreerd (15-09-2026, 35 tikken, 7x6) en ingevuld naar de foto van de folie; in de praktijk controleren.
3. Wensen daarna: palm-/duimonderdrukking verfijnen, gesture voor Fusion "kijk van voren" e.d., eventueel een
   Pi Pico W zodat het bordje zich als echt Precision Touchpad kan aanmelden (niet nodig voor Fusion-gestures).

## Testopstelling

- Trackpad eerst uit Windows verwijderen (Instellingen > Bluetooth en apparaten), anders blijft Windows verbinden.
- Koppelmodus (alleen bij eerste keer of na wissen NVS): trackpad uit, knop ingedrukt houden tot het groene lampje
  knippert; de ESP32 verbindt dan zelf (geen koppelsleutel → na 3 s).
- Het bordje (CP2102, serienummer 01DFE707) heet in Apparaatbeheer "Trackpad dongle (COM3)" in plaats van "Silicon Labs
  CP210x USB to UART Bridge" (19-09-2026; `FriendlyName` onder `HKLM\SYSTEM\CurrentControlSet\Enum\USB\VID_10C4&PID_EA60\01DFE707`,
  als beheerder gezet). Na een herinstallatie van de CP210x-driver moet dit opnieuw.
- Toolchain: PlatformIO met ESP-IDF 6.0.1 (`pio run -t upload`, COM3). Let op: het openen van de seriële poort reset het bordje.
- Logs: `tools/bridge.log` (viewer), `firmware-esp32/build.log`, `firmware-esp32/upload.log`. Deze staan in `.gitignore`.
