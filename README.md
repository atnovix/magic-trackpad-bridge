# Magic Trackpad Bridge

Apple Magic Trackpad 1 (A1339) met volledige multitouch op **Windows 11**, ook met Secure Boot aan en zonder kernel-driver.
Een **ESP32** fungeert als Bluetooth-HID-host, zet het trackpad in multitouch-modus en stuurt de vingerposities over
USB-serieel naar een Python-achtergrondprogramma dat er muis, gestures en een numpad-modus van maakt.

```
Magic Trackpad 1 ──Bluetooth (klassiek)──▶ ESP32 (firmware-esp32/) ──USB-serieel 921600 baud──▶ Windows (driver/)
                                             HID-host, multitouch aan,                             cursor, tikken, scrollen,
                                             frames als tekstregels                                zoom, vegen, profielen, numpad
```

## Waarom een ESP32?

Het Magic Trackpad 1 spreekt alleen klassiek Bluetooth en meldt zich bij Windows aan als gewone muis (cursor en
linkerklik). De multitouch-reports (id `0x28`) staan niet in de HID-descriptor en de muis-collectie is voor programma's
afgeschermd. Zonder eigen kernel-driver, die met Secure Boot niet te laden is, kom je er vanuit Windows dus niet bij.

Daarom neemt een ESP32 de Bluetooth-kant over. Het bordje koppelt met het trackpad, stuurt het feature-report `D7 01`
(dezelfde truc als de Linux-driver `hid-magicmouse`) en krijgt daarna van elke aanraking de ruwe vingerdata. Die gaat
als leesbare tekstregels naar de laptop. Windows ziet het trackpad zelf niet meer, dus de driver doet alles via
`SendInput`.

## Wat werkt

| Vingers | Gebaar | Actie |
|---|---|---|
| 1 | bewegen | cursor met versnelling |
| 1 | tik / tik-tik-vasthouden / fysieke klik | linkerklik / slepen / linkerknop |
| 2 | tik | rechtsklik |
| 2 | schuiven | scrollen (natuurlijk, met traagheid, ook horizontaal) |
| 2 | knijpen | zoom (Ctrl + wiel) |
| 2 | draaien | per profiel (standaard uit) |
| 3 | tik | middelste klik |
| 3 | veeg links / rechts | vorig / volgend venster (Alt+Tab) |
| 3 | veeg omhoog / omlaag | taakweergave / bureaublad tonen |
| 4 | tik | numpad-modus aan/uit |
| 4 | veeg links / rechts | virtueel bureaublad wisselen |

Verder:

- **Profielen per programma.** Onder `profiles` in `config.json` staat per exe-naam wat scrollen, knijpen en draaien
  doen (wiel, muisknop slepen, of toetscombinaties). Meegeleverd: **Fusion 360** met twee vingers pannen (middelste
  knop), knijpen = zoom en draaien = orbit (Shift + middelste knop).
- **Numpad-modus** voor de Mobee NUM20-folie: een raster van 7 × 6 cellen dat toetsen typt (cijferblok, pijlen,
  Home/End/PgUp/PgDn, F13-F17). Aanzetten met een vier-vinger-tik of een tik op de schakelaarcel rechtsboven op de
  folie; een fysieke klik typt de toets onder de vinger.
- **Tray-icoon met flyout** in Windows 11-stijl (volgt thema en accentkleur): status en accu, tegels voor
  trackpad/numpad/actief, schuifregelaars voor cursor- en scrollsnelheid, schakelaars voor natuurlijk scrollen, tikken
  en de Fusion-richtingen, autostart bij aanmelden. Icoonkleur: groen = trackpad, blauw = numpad, oranje = wacht op het
  trackpad, grijs = geen seriële poort.
- **Batterijen sparen.** De driver stuurt elke 5 s een hartslag naar het bordje. Blijft die 60 s uit (laptop uit of in
  slaap), dan laat de ESP32 het trackpad los zodat het zelf gaat slapen. Na 10 s zonder aanraking mag de link in
  sniffmodus; de eerste aanraking maakt hem weer actief.
- **Robuust.** Eén exemplaar tegelijk (mutex), geen console, herstelt zelf bij een weggevallen seriële poort, en het
  bordje lost de verbindrace met het trackpad zelf op (zie `PROGRESS.md`).

## Benodigd

- Apple Magic Trackpad 1 (A1339, de versie op AA-batterijen).
- ESP32 met klassiek Bluetooth, bijvoorbeeld een TTGO-bordje met ESP32-D0WDQ6 en CP2102 USB-serieel. ESP32-S2/S3/C3
  werken **niet** (geen BR/EDR).
- Windows 11 met Python 3.11+ en de pakketten `pyserial`, `pystray` en `Pillow`.
- [PlatformIO](https://platformio.org/) om de firmware te bouwen (framework ESP-IDF, getest met ESP-IDF 6.0.1).

## Aan de slag

### 1. Firmware op de ESP32

Zet eerst het Bluetooth-adres van jouw trackpad in `firmware-esp32/src/main.c` (`s_trackpad_bda`). Je vindt het in
Windows onder Instellingen > Bluetooth > eigenschappen van het trackpad, of in het ESP-IDF-log zodra het trackpad in
koppelmodus staat.

```
cd firmware-esp32
pio run                 # bouwen
pio run -t upload       # flashen (poort in platformio.ini, standaard COM3)
```

Verwijder het trackpad daarna uit Windows (Instellingen > Bluetooth en apparaten), anders blijft Windows er zelf mee
verbinden.

### 2. Koppelen

Alleen de eerste keer (of na het wissen van de NVS van het bordje): trackpad uit, de knop ingedrukt houden tot het
groene lampje knippert. De ESP32 verbindt dan zelf en bewaart de koppelsleutel. Daarna verbindt het trackpad bij de
eerste aanraking uit zichzelf.

### 3. Driver op Windows

```
pip install pyserial pystray pillow
pythonw driver\trackpad_driver.py             # tray-icoon, geen venster
python  driver\trackpad_driver.py --console   # met log in de console (handig bij tunen)
```

Bij de eerste start schrijft de driver `config.json` in de projectmap. Pas daar de seriële poort aan als het bordje niet
op COM3 zit. Autostart bij aanmelden zet je aan in het tray-menu (registersleutel `HKCU\...\Run`).

Overige opties: `--no-tray`, `--show` (flyout direct openen, met `--keep` open laten), `--settings` (instellingenvenster).

## Instellen

Alles staat in `config.json` naast de map `driver/` (tray-menu > Config openen, daarna Config herladen). Afstanden zijn
in millimeters, gains per millimeter vingerbeweging. De standaardwaarden met uitleg staan in `driver/config.py`.

| Sectie | Wat |
|---|---|
| `serial` | poort en baudrate |
| `touch` | vanaf welke druk een contact telt, palmonderdrukking, loslaat-respijt |
| `pointer` | cursor-gain en versnellingscurve |
| `tap` | tikduur, tik-tik-slepen, hold, acties per aantal vingers |
| `two_finger` | drempels voor scrollen, knijpen en draaien; gesture vasthouden tot loslaten |
| `swipe`, `inertia` | veegdrempel, scroll-traagheid |
| `profiles` | per exe-naam: `scroll`, `pinch`, `rotate`, `swipe3`, `swipe4` |
| `numpad` | raster (`rows`, `x_mm`, `y_mm`), tikgrenzen, kalibratie, toon |

**Eigen profiel:** zet de exe-naam in kleine letters als sleutel onder `profiles`; ontbrekende velden komen uit
`default`. Types: `wheel` (muiswiel met modifiers), `drag` (muisknop ingedrukt houden en bewegen), `keys`
(toetscombinatie per stap) of `none`.

**Numpad kalibreren:** zet `numpad.calibrate` aan (ook via het tray-menu), tik op de folie en lees in `driver.log` welke
cel geraakt wordt. Pas dan `rows`, `x_mm` of `y_mm` aan.

## Hulpprogramma's

- `tools/visualizer.py [COMx] [baud]` tekent de vingers live in een venster. Toetsen in het venster gaan als
  testcommando naar het bordje.
- `tools/serial_tail.py [COMx] [seconden] [--reset] [--raw]` leest de seriële poort mee; `--reset` herstart het bordje
  zodat je de opstartlog ziet.
- `driver/test_gestures.py`: de gesture-engine wordt zonder hardware getest: `python driver\test_gestures.py`
  (21 tests, ook geschikt voor pytest).

Let op: het openen van de seriële poort reset het bordje.

## Testcommando's op het bordje

De firmware luistert op dezelfde seriële poort naar losse letters, zodat je linkinstellingen zonder herflashen kunt
proberen. `?` toont de toestand en de lijst:

| Toets | Werking |
|---|---|
| `a` / `s` | sniffmodus weigeren (standaard) / toestaan |
| `m` / `l` | master- / slave-rol |
| `9` / `1` | alle ACL-pakkettypes (standaard) / alleen 1-slot |
| `c` / `d` / `x` | nu zelf verbinden / HID-verbinding verbreken / ACL afbreken |
| `t` / `b` | multitouch-commando opnieuw sturen / accu opvragen |
| `z` | tellers op nul |
| `k` | hartslag (stuurt de driver zelf) |

## Protocol

**Trackpad (uit Linux `hid-magicmouse.c`).** Multitouch aan met feature-report `D7 01`. Daarna input-report `0x28`:
4 bytes header (byte 1 bit 0 = knop, 18-bit tijdstempel) plus 9 bytes per vinger: x en y 13-bit signed, tracking-id,
touch major/minor, size, oriëntatie, state (0 = los). Bereik X −2909..3167, Y −2456..2565 op 130 × 110 mm. Accu via
feature-report `0x47`, byte 1 = procent.

**ESP32 → laptop**, één regel per gebeurtenis:

```
F <knop> <ts> <n> <id>,<x>,<y>,<state>,<major>,<minor>,<size>,<orient> ...   multitouch-frame
M <knoppen> <dx> <dy>      muis-report (multitouch nog niet actief)
B <procent>                accu
S connected|disconnected|paired|mode ..|gap ..|stats ..|link ..   status en diagnostiek
R <hex>                    onbekend report
```

Alle andere regels zijn ESP-IDF-logging.

## Waarom de firmware doet wat hij doet

Twee dingen die de eerste versies onbruikbaar maakten, uitgebreid beschreven in `PROGRESS.md`:

1. **Frames met drie of meer vingers vielen weg.** Het trackpad zet de link in sniffmodus met een interval van 11,25 ms.
   Frames met 1 of 2 vingers passen in één basebandpakket, die met 3+ vingers niet, en in sniffmodus komt het tweede
   pakket niet door. De firmware weigert daarom sniff via de link policy, registreert zich bij de Bluedroid power manager
   met eis "actief", vraagt de master-rol en staat alle ACL-pakkettypes toe.
2. **De verbinding liep vast.** Zelf verbinden terwijl het trackpad ook al verbond gaf een halfdode link
   (`rcvd ACL for unknown handle`). Met een koppelsleutel wacht het bordje nu eerst tot het trackpad zelf verbindt, en
   breekt het een ACL af als de HID-kanalen dicht zijn maar de baseband-link blijft staan.

De firmware gebruikt bewust de lage Bluedroid-API (`esp_bt_hid_host_*`) en niet de `esp_hid`-component, want die
filtert reports die niet in de HID-descriptor staan, en dat is precies report `0x28`.

## Mappen

```
firmware-esp32/   PlatformIO-project (ESP-IDF): src/main.c, sdkconfig.defaults, platformio.ini
driver/           Windows-driver (Python)
  trackpad_driver.py   hoofdprogramma: seriële lus, tray, flyout
  bridge.py            parser van de regels van het bordje
  gestures.py          gesture-engine (hardwareloos, getest)
  actions.py           gestures -> muis/toetsen volgens profiel
  numpad.py            raster van de NUM20-folie
  winput.py            SendInput: muis, wiel, toetscombinaties
  flyout.py / ui.py    Windows 11-flyout (thema en accentkleur uit het register) en instellingenvenster
  config.py            standaardwaarden en config.json
  test_gestures.py     tests
tools/            visualizer.py, serial_tail.py
PROGRESS.md       voortgang, analyses en testopstelling
```

## Beperkingen

- Het trackpad meldt zich niet aan als Precision Touchpad; Windows-eigen touchpadgebaren en -instellingen werken dus
  niet. Alles loopt via de driver. Een Pi Pico W die zich als echt Precision Touchpad aanmeldt staat op het wensenlijstje.
- Getest met één trackpad, één TTGO-bordje en Python uit de Microsoft Store. Het Bluetooth-adres van het trackpad staat
  nog vast in de firmware.
- Het Magic Trackpad 2 (Lightning, BLE) werkt niet met deze firmware.
