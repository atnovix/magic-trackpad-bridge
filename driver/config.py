"""Instellingen van de trackpad-driver: standaardwaarden, laden/bewaren als JSON in de projectmap.

Alle afstanden op het trackpad staan in millimeters (het trackpad meldt ~46,7 eenheden per mm).
Gains staan per millimeter vingerbeweging, zodat ze intuïtief te tunen zijn.
"""
import copy
import json
import os

# Config en log staan in de projectmap (naast driver/), niet in %APPDATA%: de Python uit de Microsoft Store
# leidt schrijfacties naar AppData\Roaming om naar een verborgen pakketmap (LocalCache), en dan vindt niemand ze terug.
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "driver.log")

UNITS_PER_MM = 6076 / 130.0   # X-bereik -2909..3167 over 130 mm (Linux hid-magicmouse)

DEFAULTS = {
    "serial": {"port": "COM3", "baud": 921600},

    # Aanraking: state >= touch_min_state telt als "ligt erop" (1-2 = nadering, 3 = start, 4 = vast).
    # Contacten met touch-major boven palm_major (grote vlakken) worden genegeerd.
    "touch": {"touch_min_state": 3, "palm_major": 150, "settle_frames": 2},

    "pointer": {
        "gain_px_per_mm": 4.0,        # langzaam: pixels per mm vingerbeweging
        "max_gain_px_per_mm": 16.0,   # snel
        "accel_start_mm_s": 40.0,     # onder deze snelheid geen versnelling
        "accel_span_mm_s": 250.0,     # snelheid waarbij de maximale gain bereikt wordt
    },

    "tap": {
        "tap_time_ms": 220,           # maximale duur van een tik
        "tap_move_mm": 2.5,           # maximale verplaatsing tijdens een tik
        "double_tap_drag_ms": 260,    # tik-tik-vasthouden binnen dit venster = slepen ...
        "double_tap_radius_mm": 6.0,  # ... en alleen als de tweede tik zo dicht bij de eerste begint
        "hold_ms": 700,               # één vinger zo lang stil = "hold" (numpad-schakelaar op de folie)
        "hold_move_mm": 5.0,
        "actions": {"1": "click:left", "2": "click:right", "3": "click:middle", "4": "numpad_toggle", "5": "none"},
        "button_by_fingers": {"1": "left", "2": "right", "3": "middle"},   # fysieke klik met n vingers
    },

    "two_finger": {
        "scroll_threshold_mm": 1.5,   # verplaatsing van het midden voordat scrollen begint
        "pinch_threshold_mm": 2.5,    # afstandsverandering voordat zoomen begint
        "rotate_threshold_deg": 9.0,  # hoekverandering voordat draaien begint
        "lock_mode": True,            # eenmaal gekozen gesture vasthouden tot vingers loslaten
    },

    "swipe": {"threshold_mm": 12.0},  # verplaatsing van het midden voor een 3/4-vingerveeg

    "inertia": {"enabled": True, "min_speed_mm_s": 60.0, "decay_per_s": 0.08, "stop_speed_mm_s": 8.0},

    # Profielen: 'default' geldt overal, andere sleutels zijn exe-namen (kleine letters).
    # scroll/pinch/rotate: type = wheel | drag | keys | none
    #   wheel: gain = wieleenheden per mm (120 = één klik); modifiers worden ingedrukt gehouden; natural keert om
    #   drag:  button ingedrukt houden en de muis bewegen; gain = pixels per mm (rotate: pixels per graad, axis x|y)
    #   keys:  chord per stap (step_mm / step_deg): forward/back resp. cw/ccw
    "profiles": {
        "default": {
            "scroll": {"type": "wheel", "gain": 40.0, "natural": True, "horizontal": True},
            "pinch": {"type": "wheel", "gain": 50.0, "modifiers": ["ctrl"], "invert": False},
            "rotate": {"type": "none"},
            "swipe3": {"left": "alt+shift+tab", "right": "alt+tab", "up": "win+tab", "down": "win+d"},
            "swipe4": {"left": "win+ctrl+left", "right": "win+ctrl+right", "up": "none", "down": "none"},
        },
        "fusion360.exe": {
            "scroll": {"type": "drag", "button": "middle", "gain": 12.0, "natural": False},
            "pinch": {"type": "wheel", "gain": 50.0, "modifiers": [], "invert": True},
            "rotate": {"type": "drag", "button": "middle", "modifiers": ["shift"], "axis": "x", "gain": 4.0, "invert": True},
        },
    },

    # Numpad-modus (Mobee NUM20-folie). Het raster wordt gelijkmatig verdeeld over x_mm/y_mm (0..130, 0..110,
    # gemeten vanaf linksboven). Pas rows aan op de folie; zet calibrate aan om tikposities in het log te zien.
    "numpad": {
        "enabled_at_start": False,
        "calibrate": False,
        "tap_time_ms": 600,           # typen op de folie gaat trager dan klikken: ruimere tikgrenzen
        "tap_move_mm": 4.0,
        "toggle_debounce_s": 1.0,     # na een omschakeling de schakelaar zo lang negeren
        "sound": True,                # korte toon bij omschakelen (hoog = numpad aan, laag = uit)
        "x_mm": [-7, 135], "y_mm": [-5, 110],   # gekalibreerd op de NUM20-folie (15-09-2026): 7 kolommen x 6 rijen
        "rows": [
            ["f13", "f14", "f15", "f16", "f17", "win+tab", "numpad_toggle"],
            ["none", "home", "pgup", "backspace", "equals", "divide", "multiply"],
            ["delete", "end", "pgdn", "numpad7", "numpad8", "numpad9", "subtract"],
            ["none", "none", "none", "numpad4", "numpad5", "numpad6", "add"],
            ["none", "up", "none", "numpad1", "numpad2", "numpad3", "enter"],
            ["left", "down", "right", "numpad0", "numpad0", "decimal", "enter"],
        ],
    },
}


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load():
    """Config laden; ontbrekende sleutels worden met de standaardwaarden aangevuld. Eerste keer: bestand aanmaken."""
    os.makedirs(APP_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        save(DEFAULTS)
        return copy.deepcopy(DEFAULTS)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        user = json.load(f)
    return _merge(DEFAULTS, user)


def save(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def profile_for(cfg, exe):
    """Profiel voor een programma: exe-specifiek bovenop 'default'."""
    profiles = cfg["profiles"]
    return _merge(profiles["default"], profiles.get(exe, {}))
