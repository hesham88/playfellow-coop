"""Windows input and window handling for real games (research R1 section 3.6, R4 section 2): focus, high-DPI coordinates, scan-code input.

What goes wrong with a real game window, and the fix built here:

  * the game is not in front and Windows refuses to let a background program take the foreground: attach to the foreground thread's input queue, tap Alt (the documented exemption), then bring
    the window up (`FocusLock`); an input-injecting process must also run at an integrity level at least equal to the game's, or Windows silently drops the input (`integrity_ok`);
  * a scaled display makes window coordinates and captured pixels disagree: set per-monitor-v2 DPI awareness BEFORE anything else imports a GUI library (`set_dpi_awareness`), read the physical
    client rectangle (no title bar, no invisible resize border) and map the model's 0-1000 grid onto it (`model_to_pixel`), and onto SendInput's 0..65535 absolute grid (`to_absolute`);
  * games poll hardware scan codes, not virtual-key messages: `ScanBackend` sends keyboard events as scan codes with the extended flag where needed, and mouse moves relative or absolute.
Everything that touches Windows goes through an `api` object, so the logic is tested with a fake and the real `Win32Api` is only built on Windows.
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Callable, Protocol

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0001, 0x0002, 0x0008
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_WHEEL, MOUSEEVENTF_ABSOLUTE = 0x0008, 0x0010, 0x0800, 0x8000
DPI_PER_MONITOR_AWARE_V2 = -4
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _Union(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _Union)]


# hardware scan codes (set 1); the second value says whether the key needs the extended flag
SCANCODES: dict[str, tuple[int, bool]] = {
    "esc": (0x01, False), "1": (0x02, False), "2": (0x03, False), "3": (0x04, False), "4": (0x05, False), "5": (0x06, False), "6": (0x07, False), "7": (0x08, False), "8": (0x09, False),
    "9": (0x0A, False), "0": (0x0B, False), "tab": (0x0F, False), "q": (0x10, False), "w": (0x11, False), "e": (0x12, False), "r": (0x13, False), "t": (0x14, False), "y": (0x15, False),
    "u": (0x16, False), "i": (0x17, False), "o": (0x18, False), "p": (0x19, False), "enter": (0x1C, False), "ctrl": (0x1D, False), "a": (0x1E, False), "s": (0x1F, False),
    "d": (0x20, False), "f": (0x21, False), "g": (0x22, False), "h": (0x23, False), "j": (0x24, False), "k": (0x25, False), "l": (0x26, False), "shift": (0x2A, False), "z": (0x2C, False),
    "x": (0x2D, False), "c": (0x2E, False), "v": (0x2F, False), "b": (0x30, False), "n": (0x31, False), "m": (0x32, False), "alt": (0x38, False), "space": (0x39, False),
    "f1": (0x3B, False), "f2": (0x3C, False), "f3": (0x3D, False), "f4": (0x3E, False), "f5": (0x3F, False),
    "up": (0x48, True), "left": (0x4B, True), "right": (0x4D, True), "down": (0x50, True), "insert": (0x52, True), "delete": (0x53, True), "home": (0x47, True), "end": (0x4F, True),
}


class Api(Protocol):
    """Everything the logic needs from Windows. `Win32Api` implements it for real; tests implement it with a fake."""
    def set_dpi_awareness(self, context: int) -> bool: ...
    def client_size(self, hwnd: int) -> tuple[int, int]: ...
    def client_to_screen(self, hwnd: int, point: tuple[int, int]) -> tuple[int, int]: ...
    def screen_size(self) -> tuple[int, int]: ...
    def foreground(self) -> int: ...
    def is_iconic(self, hwnd: int) -> bool: ...
    def restore(self, hwnd: int) -> None: ...
    def thread_of(self, hwnd: int) -> int: ...
    def current_thread(self) -> int: ...
    def attach(self, current: int, other: int, on: bool) -> bool: ...
    def tap_alt(self) -> None: ...
    def bring_up(self, hwnd: int) -> None: ...
    def pin_topmost(self, hwnd: int) -> None: ...
    def integrity_level(self, hwnd: int | None) -> int: ...


def set_dpi_awareness(api: Api) -> bool:
    """Per-monitor v2 DPI awareness. Call it at the very start of the program: once a library has set the legacy awareness, Windows refuses to change it."""
    return bool(api.set_dpi_awareness(DPI_PER_MONITOR_AWARE_V2))


def client_rect(api: Api, hwnd: int) -> tuple[int, int, int, int]:
    """The game's playable area in physical screen pixels (left, top, right, bottom): no title bar and none of the invisible resize border."""
    width, height = api.client_size(hwnd)
    x0, y0 = api.client_to_screen(hwnd, (0, 0))
    x1, y1 = api.client_to_screen(hwnd, (width, height))
    return x0, y0, x1, y1


def model_to_pixel(gx: float, gy: float, rect: tuple[int, int, int, int], grid: int = 1000) -> tuple[int, int]:
    """A point on the model's 0-1000 grid as a physical screen pixel inside the client rectangle."""
    x0, y0, x1, y1 = rect
    clamp = lambda v: min(max(v, 0.0), float(grid))  # noqa: E731
    return x0 + round(clamp(gx) * (x1 - x0 - 1) / grid), y0 + round(clamp(gy) * (y1 - y0 - 1) / grid)


def to_absolute(x: int, y: int, screen_w: int, screen_h: int) -> tuple[int, int]:
    """A physical screen pixel on SendInput's 0..65535 absolute grid."""
    return round(x * 65535 / max(screen_w - 1, 1)), round(y * 65535 / max(screen_h - 1, 1))


def integrity_ok(api: Api, hwnd: int) -> bool:
    """Windows silently drops injected input aimed at a window of higher integrity than the injecting process (no error). True when we are at least as privileged as the game."""
    return api.integrity_level(None) >= api.integrity_level(hwnd)


class FocusLock:
    def __init__(self, api: Api, pin: bool = False):
        self.api, self.pin = api, pin
        self.log: list[str] = []

    def ensure(self, hwnd: int) -> bool:
        """Bring the window to the front and focus it, whatever the foreground lock says. True when it is the foreground window afterwards."""
        api = self.api
        if api.foreground() == hwnd:
            return True
        if api.is_iconic(hwnd):
            api.restore(hwnd)
            self.log.append("restore")
        current, other = api.current_thread(), api.thread_of(api.foreground())
        attached = False
        if other and other != current:
            attached = bool(api.attach(current, other, True))
            self.log.append("attach")
        try:
            api.tap_alt()  # a keyboard event just now satisfies Windows' foreground exemption
            api.bring_up(hwnd)
            if self.pin:
                api.pin_topmost(hwnd)
        finally:
            if attached:
                api.attach(current, other, False)  # always detach: a leaked attachment couples our input queue to another program's
                self.log.append("detach")
        return api.foreground() == hwnd


def key_input(key: str, up: bool = False) -> INPUT:
    """A keyboard event for a key name, as a hardware scan code (what DirectInput and raw input games read)."""
    if key.lower() not in SCANCODES:
        raise KeyError(f"no scan code for key {key!r}")
    scan, extended = SCANCODES[key.lower()]
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0) | (KEYEVENTF_KEYUP if up else 0)
    packet = INPUT(type=INPUT_KEYBOARD)
    packet.ki = KEYBDINPUT(0, scan, flags, 0, 0)
    return packet


def mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    packet = INPUT(type=INPUT_MOUSE)
    packet.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return packet


class ScanBackend:
    """Keyboard and mouse as scan-code and mouse packets, sent with `send(packets)` (the real SendInput on Windows, a recorder in tests). Implements chunks.Backend."""

    def __init__(self, send: Callable[[list[INPUT]], int]):
        self.send = send

    def key_down(self, key: str) -> None:
        self.send([key_input(key)])

    def key_up(self, key: str) -> None:
        self.send([key_input(key, up=True)])

    def mouse_move(self, dx: int, dy: int) -> None:
        """Relative movement (3D camera): integer pixel deltas, never a large jump (use chunks.mouse_substeps)."""
        self.send([mouse_input(MOUSEEVENTF_MOVE, dx, dy)])

    def mouse_absolute(self, x: int, y: int, screen_w: int, screen_h: int) -> None:
        ax, ay = to_absolute(x, y, screen_w, screen_h)
        self.send([mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay)])

    def click(self, right: bool = False) -> None:
        down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if right else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
        self.send([mouse_input(down), mouse_input(up)])

    def wheel(self, notches: int) -> None:
        self.send([mouse_input(MOUSEEVENTF_WHEEL, data=notches * 120)])


def bezier_path(start: tuple[float, float], end: tuple[float, float], steps: int = 12, bend: float = 0.15) -> list[tuple[int, int]]:
    """Points along a gently curved path from start to end (a cubic Bezier bent sideways by `bend` of the distance): a drag that looks like a hand, not a teleport. Ends exactly at `end`."""
    (x0, y0), (x1, y1) = start, end
    dx, dy = x1 - x0, y1 - y0
    nx, ny = -dy * bend, dx * bend
    c1, c2 = (x0 + dx / 3 + nx, y0 + dy / 3 + ny), (x0 + 2 * dx / 3 + nx, y0 + 2 * dy / 3 + ny)
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        out.append((round(a * x0 + b * c1[0] + c * c2[0] + d * x1), round(a * y0 + b * c1[1] + c * c2[1] + d * y1)))
    out[-1] = (round(x1), round(y1))
    return out


def precise_sleep(ms: float, clock: Callable[[], float] = lambda: time.perf_counter() * 1000.0, sleep: Callable[[float], None] = lambda s: time.sleep(s), spin_ms: float = 1.5) -> None:
    """Sleep `ms` accurately: a normal sleep for all but the last `spin_ms` (the scheduler can be 15 ms late), then spin on the clock for the rest."""
    target = clock() + ms
    coarse = ms - spin_ms
    if coarse > 0:
        sleep(coarse / 1000.0)
    while clock() < target:
        pass


class Win32Api:  # pragma: no cover - exercised only on a real Windows desktop
    """The real thing. Built only on Windows."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Win32Api needs Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def set_dpi_awareness(self, context: int) -> bool:
        return bool(self.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(context)))

    def client_size(self, hwnd: int) -> tuple[int, int]:
        rect = wintypes.RECT()
        self.user32.GetClientRect(hwnd, ctypes.byref(rect))
        return rect.right - rect.left, rect.bottom - rect.top

    def client_to_screen(self, hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
        p = wintypes.POINT(*point)
        self.user32.ClientToScreen(hwnd, ctypes.byref(p))
        return p.x, p.y

    def screen_size(self) -> tuple[int, int]:
        return self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1)

    def foreground(self) -> int:
        return int(self.user32.GetForegroundWindow() or 0)

    def is_iconic(self, hwnd: int) -> bool:
        return bool(self.user32.IsIconic(hwnd))

    def restore(self, hwnd: int) -> None:
        self.user32.ShowWindow(hwnd, 9)

    def thread_of(self, hwnd: int) -> int:
        return int(self.user32.GetWindowThreadProcessId(hwnd, None))

    def current_thread(self) -> int:
        return int(self.kernel32.GetCurrentThreadId())

    def attach(self, current: int, other: int, on: bool) -> bool:
        return bool(self.user32.AttachThreadInput(current, other, on))

    def tap_alt(self) -> None:
        self.send([key_input("alt"), key_input("alt", up=True)])

    def send(self, packets: list[INPUT]) -> int:
        array = (INPUT * len(packets))(*packets)
        return int(self.user32.SendInput(len(packets), array, ctypes.sizeof(INPUT)))

    def bring_up(self, hwnd: int) -> None:
        self.user32.BringWindowToTop(hwnd)
        self.user32.SetForegroundWindow(hwnd)
        self.user32.SetFocus(hwnd)

    def pin_topmost(self, hwnd: int) -> None:
        self.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)

    def integrity_level(self, hwnd: int | None) -> int:
        """The integrity level (RID) of the process that owns `hwnd`, or of this process when `hwnd` is None: 0x1000 low, 0x2000 medium, 0x3000 high (elevated), 0x4000 system.
        0 when it cannot be read (access denied): the caller then treats the window as not higher than us."""
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = self.kernel32
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        advapi.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        advapi.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        pid = wintypes.DWORD(0)
        if hwnd is None:
            handle = kernel.GetCurrentProcess()
        else:
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            handle = kernel.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return 0
        token = wintypes.HANDLE()
        try:
            if not advapi.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
                return 0
            size = wintypes.DWORD(0)
            advapi.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))  # TokenIntegrityLevel
            buffer = ctypes.create_string_buffer(size.value)
            if not advapi.GetTokenInformation(token, 25, buffer, size, ctypes.byref(size)):
                return 0
            sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_MANDATORY_LABEL starts with the SID pointer
            advapi.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
            advapi.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
            count = advapi.GetSidSubAuthorityCount(sid)[0]
            return int(advapi.GetSidSubAuthority(sid, count - 1)[0])
        finally:
            if token:
                kernel.CloseHandle(token)
            if hwnd is not None and handle:
                kernel.CloseHandle(handle)
