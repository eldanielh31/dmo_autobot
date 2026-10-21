import ctypes
import logging

import win32gui

PUL = ctypes.POINTER(ctypes.c_ulong)
_active_scan_codes: set[int] = set()


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class Input_I(ctypes.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyBdInput), ("hi", HardwareInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]


def key_down(scan_code: int) -> bool:
    extra = ctypes.c_ulong(0)
    keyboard_input = KeyBdInput(0, scan_code, 0x0008, 0, ctypes.pointer(extra))
    input_union = Input_I()
    input_union.ki = keyboard_input
    event = Input(ctypes.c_ulong(1), input_union)
    sent = ctypes.windll.user32.SendInput(
        1,
        ctypes.pointer(event),
        ctypes.sizeof(event),
    ) == 1
    if sent:
        _active_scan_codes.add(scan_code)
    return sent


def key_up(scan_code: int) -> bool:
    extra = ctypes.c_ulong(0)
    keyboard_input = KeyBdInput(0, scan_code, 0x0008 | 0x0002, 0, ctypes.pointer(extra))
    input_union = Input_I()
    input_union.ki = keyboard_input
    event = Input(ctypes.c_ulong(1), input_union)
    sent = ctypes.windll.user32.SendInput(
        1,
        ctypes.pointer(event),
        ctypes.sizeof(event),
    ) == 1
    if sent:
        _active_scan_codes.discard(scan_code)
    return sent


def press_key_fast(scan_code: int) -> bool:
    down_sent = key_down(scan_code)
    up_sent = key_up(scan_code)
    if not down_sent or not up_sent:
        logging.error(
            "[ENTRADA] SendInput no insertó ambos eventos para scan code 0x%02X "
            "(down=%s, up=%s).",
            scan_code,
            down_sent,
            up_sent,
        )
    return down_sent and up_sent


def release_all_keys() -> None:
    for scan_code in tuple(_active_scan_codes):
        if not key_up(scan_code):
            logging.error("[ENTRADA] No se pudo liberar scan code 0x%02X.", scan_code)


def is_key_down(virtual_key: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)


MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010


def mouse_right_down() -> None:
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)


def mouse_right_up() -> None:
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)


def mouse_drag_relative(dx: int, dy: int = 0) -> None:
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, dx, dy, 0, 0)


def set_cursor_position(x: int, y: int) -> None:
    ctypes.windll.user32.SetCursorPos(x, y)


def find_window(title_contains: str) -> int | None:
    matches: list[int] = []

    def callback(hwnd: int, _: object) -> None:
        if (
            win32gui.IsWindowVisible(hwnd)
            and title_contains.lower() in win32gui.GetWindowText(hwnd).lower()
        ):
            matches.append(hwnd)

    win32gui.EnumWindows(callback, None)
    return matches[0] if matches else None


def get_client_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    x1, y1 = win32gui.ClientToScreen(hwnd, (0, 0))
    rect = win32gui.GetClientRect(hwnd)
    x2, y2 = win32gui.ClientToScreen(hwnd, (rect[2], rect[3]))
    return x1, y1, x2 - x1, y2 - y1
