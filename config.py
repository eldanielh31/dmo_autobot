from pathlib import Path
from typing import Final

WINDOW_TITLE_CONTAINS = "Client Version"

MAX_FPS = 30
PREVIEW_SCALE = 0.70

# ROI relativos al área cliente: (x1, y1, x2, y2), entre 0.0 y 1.0.
TARGET_FRAME_ROI = (0.38, 0.015, 0.58, 0.11)
HP_BAR_ROI = (0.427, 0.051, 0.510, 0.065)
TARGET_FRAME_MIN_BRIGHTNESS = 25.0
MIN_HP_RED_PIXELS = 1

MENU_PANEL_ROI = (0.30, 0.22, 0.70, 0.60)
MENU_BLUE_PIXEL_RATIO = 0.50
MENU_BLUE_MIN_SATURATION = 120

KEY_TAB = 0x0F
KEY_1 = 0x02

VK_CONTROL = 0x11
VK_MENU = 0x12
VK_SHIFT = 0x10
VK_P = 0x50
VK_Q = 0x51

ATTACK_KEY_INTERVAL = 0.40
TAB_COOLDOWN = 0.25
CAMERA_DRAG_STEP = 38
DRAG_STEP_INTERVAL = 0.035
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
