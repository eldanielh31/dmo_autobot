import math
from pathlib import Path
from typing import Final

WINDOW_TITLE_CONTAINS = "Client Version"

MAX_FPS = 30
PREVIEW_SCALE = 0.70

# ROI relativos al área cliente: (x1, y1, x2, y2), entre 0.0 y 1.0.
TARGET_FRAME_ROI = (0.41, 0.0, 0.55, 0.09)
TARGET_NAME_ROI = (0.15, 0.05, 0.85, 0.55)
HP_BAR_ROI = (0.427, 0.045, 0.510, 0.060)
MIN_HP_RED_PIXELS = 6
TARGET_NAME_OCR_SCALE = 3

MENU_PANEL_ROI = (0.30, 0.22, 0.70, 0.60)
MENU_BLUE_PIXEL_RATIO = 0.50
MENU_BLUE_MIN_SATURATION = 120

KEY_TAB = 0x0F
KEY_1 = 0x02
KEY_W = 0x11
KEY_A = 0x1E
KEY_S = 0x1F
KEY_D = 0x20

VK_CONTROL = 0x11
VK_MENU = 0x12
VK_SHIFT = 0x10
VK_P = 0x50
VK_Q = 0x51

ATTACK_KEY_INTERVAL = 0.40
TAB_COOLDOWN = 0.25
TARGET_SELECTION_SETTLE_DELAY = 1.0
TARGET_NAME_CONFIRMATION_TIMEOUT = 2.0
CAMERA_DRAG_STEP = 38
DRAG_STEP_INTERVAL = 0.035
CAMERA_SEARCH_TURN_DURATION = 5.0
WALK_SEARCH_DURATION = 16.0
WALK_SEARCH_STEP_DURATION = 2.0
ZERO_HP_FINISHER_DELAY = 0.20
STATUS_LOG_INTERVAL = 5.0

ANTIMACRO_HEADER_PATH: Final[Path] = Path(__file__).resolve().with_name("antimacro_header.png")
ANTIMACRO_MATCH_THRESHOLD: Final[float] = 0.82
ANTIMACRO_CLEAR_DELAY: Final[float] = 3.0
ANTIMACRO_ALARM_RELEASE_DELAY: Final[float] = 0.35
ANTIMACRO_SCREENSHOT_DIR: Final[Path] = Path(__file__).resolve().parent / "debug"
ENV_FILE: Final[Path] = Path(__file__).resolve().with_name(".env")
TELEGRAM_LOG_DATABASE_PATH: Final[Path] = Path(__file__).resolve().with_name(
    ".dmo_bot_telegram_logs.sqlite3"
)
TELEGRAM_API_TIMEOUT: Final[float] = 15.0
TELEGRAM_COMMAND_POLL_TIMEOUT: Final[float] = 10.0
ANTIMACRO_OCR_INTERVAL: Final[float] = 0.5


def _is_finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_config() -> None:
    errors: list[str] = []

    for name, roi in (
        ("TARGET_FRAME_ROI", TARGET_FRAME_ROI),
        ("TARGET_NAME_ROI", TARGET_NAME_ROI),
        ("HP_BAR_ROI", HP_BAR_ROI),
        ("MENU_PANEL_ROI", MENU_PANEL_ROI),
    ):
        if (
            not isinstance(roi, tuple)
            or len(roi) != 4
            or not all(_is_finite_number(value) for value in roi)
        ):
            errors.append(f"{name} debe contener cuatro números finitos.")
            continue
        x1, y1, x2, y2 = roi
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            errors.append(
                f"{name} debe cumplir 0 <= x1 < x2 <= 1 "
                "y 0 <= y1 < y2 <= 1."
            )

    for name, value in (
        ("PREVIEW_SCALE", PREVIEW_SCALE),
        ("ATTACK_KEY_INTERVAL", ATTACK_KEY_INTERVAL),
        ("TAB_COOLDOWN", TAB_COOLDOWN),
        ("TARGET_SELECTION_SETTLE_DELAY", TARGET_SELECTION_SETTLE_DELAY),
        ("TARGET_NAME_CONFIRMATION_TIMEOUT", TARGET_NAME_CONFIRMATION_TIMEOUT),
        ("DRAG_STEP_INTERVAL", DRAG_STEP_INTERVAL),
        ("CAMERA_SEARCH_TURN_DURATION", CAMERA_SEARCH_TURN_DURATION),
        ("WALK_SEARCH_DURATION", WALK_SEARCH_DURATION),
        ("WALK_SEARCH_STEP_DURATION", WALK_SEARCH_STEP_DURATION),
        ("ZERO_HP_FINISHER_DELAY", ZERO_HP_FINISHER_DELAY),
        ("STATUS_LOG_INTERVAL", STATUS_LOG_INTERVAL),
        ("ANTIMACRO_MATCH_THRESHOLD", ANTIMACRO_MATCH_THRESHOLD),
        ("ANTIMACRO_CLEAR_DELAY", ANTIMACRO_CLEAR_DELAY),
        ("ANTIMACRO_ALARM_RELEASE_DELAY", ANTIMACRO_ALARM_RELEASE_DELAY),
        ("ANTIMACRO_OCR_INTERVAL", ANTIMACRO_OCR_INTERVAL),
        ("TELEGRAM_API_TIMEOUT", TELEGRAM_API_TIMEOUT),
        ("TELEGRAM_COMMAND_POLL_TIMEOUT", TELEGRAM_COMMAND_POLL_TIMEOUT),
    ):
        if not _is_finite_number(value) or value <= 0:
            errors.append(f"{name} debe ser un número finito mayor que cero.")

    for name, value in (
        ("MENU_BLUE_PIXEL_RATIO", MENU_BLUE_PIXEL_RATIO),
        ("ANTIMACRO_MATCH_THRESHOLD", ANTIMACRO_MATCH_THRESHOLD),
    ):
        if not _is_finite_number(value):
            errors.append(f"{name} debe ser un número finito entre 0 y 1.")
        elif not 0 <= value <= 1:
            errors.append(f"{name} debe estar entre 0 y 1.")

    if not isinstance(MAX_FPS, int) or isinstance(MAX_FPS, bool) or MAX_FPS <= 0:
        errors.append("MAX_FPS debe ser un entero mayor que cero.")
    if (
        not isinstance(MIN_HP_RED_PIXELS, int)
        or isinstance(MIN_HP_RED_PIXELS, bool)
        or MIN_HP_RED_PIXELS <= 0
    ):
        errors.append("MIN_HP_RED_PIXELS debe ser un entero mayor que cero.")
    if (
        not isinstance(MENU_BLUE_MIN_SATURATION, int)
        or isinstance(MENU_BLUE_MIN_SATURATION, bool)
        or not 0 <= MENU_BLUE_MIN_SATURATION <= 255
    ):
        errors.append("MENU_BLUE_MIN_SATURATION debe ser un entero entre 0 y 255.")
    if (
        not isinstance(TARGET_NAME_OCR_SCALE, int)
        or isinstance(TARGET_NAME_OCR_SCALE, bool)
        or TARGET_NAME_OCR_SCALE <= 0
    ):
        errors.append("TARGET_NAME_OCR_SCALE debe ser un entero mayor que cero.")
    if (
        not isinstance(CAMERA_DRAG_STEP, int)
        or isinstance(CAMERA_DRAG_STEP, bool)
        or CAMERA_DRAG_STEP <= 0
    ):
        errors.append("CAMERA_DRAG_STEP debe ser un entero mayor que cero.")

    for name, value in (
        ("KEY_TAB", KEY_TAB),
        ("KEY_1", KEY_1),
        ("KEY_W", KEY_W),
        ("KEY_A", KEY_A),
        ("KEY_S", KEY_S),
        ("KEY_D", KEY_D),
        ("VK_CONTROL", VK_CONTROL),
        ("VK_MENU", VK_MENU),
        ("VK_SHIFT", VK_SHIFT),
        ("VK_P", VK_P),
        ("VK_Q", VK_Q),
    ):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= 255
        ):
            errors.append(f"{name} debe ser un código de tecla entre 0 y 255.")

    if (
        _is_finite_number(ANTIMACRO_ALARM_RELEASE_DELAY)
        and _is_finite_number(ANTIMACRO_CLEAR_DELAY)
        and ANTIMACRO_ALARM_RELEASE_DELAY >= ANTIMACRO_CLEAR_DELAY
    ):
        errors.append(
            "ANTIMACRO_ALARM_RELEASE_DELAY debe ser menor que ANTIMACRO_CLEAR_DELAY."
        )

    if errors:
        raise ValueError("[CONFIG] Configuración inválida:\n- " + "\n- ".join(errors))


validate_config()
