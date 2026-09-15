"""Windows-invoer via SendInput (muis, wiel, toetsen) en hulpfuncties voor het voorgrondprogramma.

Alles via ctypes, zonder extra pakketten. Werkt vanuit elke thread.
"""
import ctypes
import ctypes.wintypes as wt
import os

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- SendInput-structuren -------------------------------------------------------------------
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP = 0x0080, 0x0100
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
WHEEL_DELTA = 120

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wt.UINT


def _send(*inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    return sent == n


def _mouse(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return inp


def _key(vk, up=False, extended=False):
    inp = INPUT(type=INPUT_KEYBOARD)
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    inp.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    return inp


# --- Muis -------------------------------------------------------------------------------------
def mouse_move(dx, dy):
    """Relatieve cursorbeweging in pixels (Windows past zelf geen versnelling toe op SendInput)."""
    if dx or dy:
        _send(_mouse(MOUSEEVENTF_MOVE, int(dx), int(dy)))


_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    "x1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 1),
    "x2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 2),
}


def mouse_down(button):
    down, _, data = _BUTTONS[button]
    _send(_mouse(down, data=data))


def mouse_up(button):
    _, up, data = _BUTTONS[button]
    _send(_mouse(up, data=data))


def mouse_click(button="left", count=1):
    down, up, data = _BUTTONS[button]
    seq = []
    for _ in range(count):
        seq.append(_mouse(down, data=data))
        seq.append(_mouse(up, data=data))
    _send(*seq)


def wheel(delta, horizontal=False):
    """Wielbeweging; delta in wieleenheden (120 = één klik). Kleine waarden zijn toegestaan (high-res)."""
    delta = int(delta)
    if delta:
        _send(_mouse(MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL, data=ctypes.c_long(delta).value))


def cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def set_cursor_pos(x, y):
    user32.SetCursorPos(int(x), int(y))


# --- Toetsen ----------------------------------------------------------------------------------
_VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "menu": 0x12,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C, "super": 0x5B,
    "tab": 0x09, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "home": 0x24, "end": 0x23, "pgup": 0x21, "pageup": 0x21, "pgdn": 0x22, "pagedown": 0x22,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91, "printscreen": 0x2C, "pause": 0x13, "apps": 0x5D,
    "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62, "numpad3": 0x63, "numpad4": 0x64,
    "numpad5": 0x65, "numpad6": 0x66, "numpad7": 0x67, "numpad8": 0x68, "numpad9": 0x69,
    "multiply": 0x6A, "add": 0x6B, "separator": 0x6C, "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
    "volumeup": 0xAF, "volumedown": 0xAE, "volumemute": 0xAD, "medianext": 0xB0, "mediaprev": 0xB1,
    "mediaplay": 0xB3, "browserback": 0xA6, "browserforward": 0xA7,
    "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE, "equals": 0xBB,
}
for _i in range(1, 25):
    _VK[f"f{_i}"] = 0x6F + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    _VK[_c] = ord(_c.upper())
for _c in "0123456789":
    _VK[_c] = ord(_c)

# Toetsen die als "extended" gestuurd moeten worden (anders ziet Windows bijv. pijl-links als numpad 4).
_EXTENDED = {0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x21, 0x22, 0x2D, 0x2E, 0x6F, 0x5B, 0x5C, 0x5D, 0x90, 0x2C,
             0xAF, 0xAE, 0xAD, 0xB0, 0xB1, 0xB3, 0xA6, 0xA7}


def parse_chord(chord):
    """'ctrl+shift+tab' -> lijst virtuele toetscodes in volgorde. Onbekende naam -> KeyError."""
    keys = []
    for part in chord.replace(" ", "").lower().split("+"):
        if not part:
            continue
        keys.append(_VK[part])
    return keys


def key_down(vk):
    _send(_key(vk, False, vk in _EXTENDED))


def key_up(vk):
    _send(_key(vk, True, vk in _EXTENDED))


def send_chord(chord):
    """Druk een toetscombinatie (bijv. 'alt+tab', 'win+d', 'numpad7') in en laat hem weer los."""
    if not chord or chord.lower() in ("none", "-", ""):
        return
    vks = parse_chord(chord)
    seq = [_key(vk, False, vk in _EXTENDED) for vk in vks]
    seq += [_key(vk, True, vk in _EXTENDED) for vk in reversed(vks)]
    _send(*seq)


class HeldModifiers:
    """Modifiers (ctrl/shift/alt) ingedrukt houden zolang een gesture loopt."""

    def __init__(self):
        self._held = []

    def hold(self, names):
        self.release()
        for n in names or []:
            vk = _VK[n.lower()]
            key_down(vk)
            self._held.append(vk)

    def release(self):
        for vk in reversed(self._held):
            key_up(vk)
        self._held = []


# --- Voorgrondprogramma -----------------------------------------------------------------------
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
kernel32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = (wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD))
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))


def foreground_exe():
    """Bestandsnaam (kleine letters) van het programma met het actieve venster, bijv. 'fusion360.exe'."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(h)
