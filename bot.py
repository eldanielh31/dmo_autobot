from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import ctypes
import threading
import unicodedata
import winsound
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Final

import cv2
import mss
import numpy as np
import requests
import win32gui
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

WINDOW_TITLE_CONTAINS = "Client Version"

MAX_FPS = 30
PREVIEW_SCALE = 0.70

# ROI relativos al área cliente: (x1, y1, x2, y2), entre 0.0 y 1.0.
TARGET_FRAME_ROI = (0.38, 0.015, 0.58, 0.11)
HP_BAR_ROI = (0.430, 0.051, 0.508, 0.067)

TARGET_FRAME_MIN_BRIGHTNESS = 25.0
MIN_HP_RED_PIXELS = 50

MENU_PANEL_ROI = (0.30, 0.22, 0.70, 0.60)
MENU_BLUE_PIXEL_RATIO = 0.50
MENU_BLUE_MIN_SATURATION = 120

KEY_TAB = 0x0F  # Seleccionar objetivo más cercano
KEY_1 = 0x02    # Habilidad / Ataque básico

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_P = 0x50
VK_Q = 0x51

ATTACK_KEY_INTERVAL = 0.40
TAB_COOLDOWN = 0.25
CAMERA_DRAG_STEP = 38
DRAG_STEP_INTERVAL = 0.035
STATUS_LOG_INTERVAL = 5.0
ANTIMACRO_HEADER_PATH: Final[Path] = Path(__file__).resolve().with_name("antimacro_header.png")
ANTIMACRO_MATCH_THRESHOLD: Final[float] = 0.82
ANTIMACRO_CLEAR_DELAY: Final[float] = 3.0
ANTIMACRO_ALARM_RELEASE_DELAY: Final[float] = 0.35
ANTIMACRO_SCREENSHOT_DIR: Final[Path] = Path(__file__).resolve().parent / "debug"
ENV_FILE: Final[Path] = Path(__file__).resolve().with_name(".env")
TELEGRAM_API_TIMEOUT: Final[float] = 15.0
ANTIMACRO_OCR_INTERVAL: Final[float] = 0.5

_antimacro_header: np.ndarray | None = None
_active_scan_codes: set[int] = set()

PUL = ctypes.POINTER(ctypes.c_ulong)

class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL)
    ]

class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_short), ("wParamH", ctypes.c_ushort)]

class MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]

class Input_I(ctypes.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyBdInput), ("hi", HardwareInput)]

class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]

def key_down(hex_code: int):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(0, hex_code, 0x0008, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    sent = ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x)) == 1
    if sent:
        _active_scan_codes.add(hex_code)
    return sent

def key_up(hex_code: int):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(0, hex_code, 0x0008 | 0x0002, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    sent = ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x)) == 1
    if sent:
        _active_scan_codes.discard(hex_code)
    return sent

def press_key_fast(hex_code: int):
    down_sent = key_down(hex_code)
    up_sent = key_up(hex_code)
    if not down_sent or not up_sent:
        logging.error(
            "[ENTRADA] SendInput no insertó ambos eventos para scan code 0x%02X "
            "(down=%s, up=%s).",
            hex_code,
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

def mouse_right_down():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)

def mouse_right_up():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

def mouse_drag_relative(dx: int, dy: int = 0):
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, dx, dy, 0, 0)


def find_window(title_contains: str) -> int | None:
    matches = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            if title_contains.lower() in win32gui.GetWindowText(hwnd).lower():
                matches.append(hwnd)
    win32gui.EnumWindows(callback, None)
    return matches[0] if matches else None

def get_client_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    x1, y1 = win32gui.ClientToScreen(hwnd, (0, 0))
    rect = win32gui.GetClientRect(hwnd)
    x2, y2 = win32gui.ClientToScreen(hwnd, (rect[2], rect[3]))
    return x1, y1, x2 - x1, y2 - y1

def get_roi_rect(client_rect: tuple[int, int, int, int], rel_coords: tuple[float, float, float, float]) -> dict:
    left, top, width, height = client_rect
    rx1, ry1, rx2, ry2 = rel_coords
    return {
        "left": left + int(width * rx1),
        "top": top + int(height * ry1),
        "width": max(1, int(width * (rx2 - rx1))),
        "height": max(1, int(height * (ry2 - ry1))),
    }

def check_target_status(sct: mss.MSS, client_rect: tuple[int, int, int, int]) -> tuple[bool, int, bool]:
    frame_roi = get_roi_rect(client_rect, TARGET_FRAME_ROI)
    raw_frame = np.asarray(sct.grab(frame_roi), dtype=np.uint8)
    gray_frame = cv2.cvtColor(raw_frame[:, :, :3], cv2.COLOR_BGR2GRAY)
    frame_exists = float(np.mean(gray_frame)) >= TARGET_FRAME_MIN_BRIGHTNESS

    hp_roi = get_roi_rect(client_rect, HP_BAR_ROI)
    raw_hp = np.asarray(sct.grab(hp_roi), dtype=np.uint8)
    bgr_hp = raw_hp[:, :, :3]

    r = bgr_hp[:, :, 2].astype(int)
    g = bgr_hp[:, :, 1].astype(int)
    b = bgr_hp[:, :, 0].astype(int)

    red_mask = (r > 105) & (r > g + 25) & (r > b + 25)
    red_count = int(np.count_nonzero(red_mask))

    is_alive = frame_exists and (red_count >= MIN_HP_RED_PIXELS)

    return is_alive, red_count, frame_exists


def is_game_menu_open(sct: mss.MSS, client_rect: tuple[int, int, int, int]) -> bool:
    """Detecta el panel azul saturado del menú, no tonos azul-gris del escenario."""
    menu_roi = get_roi_rect(client_rect, MENU_PANEL_ROI)
    raw_menu = np.asarray(sct.grab(menu_roi), dtype=np.uint8)
    hsv_menu = cv2.cvtColor(raw_menu[:, :, :3], cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(
        hsv_menu,
        np.array((90, MENU_BLUE_MIN_SATURATION, 20), dtype=np.uint8),
        np.array((135, 255, 220), dtype=np.uint8),
    )
    blue_ratio = float(np.count_nonzero(blue_mask)) / blue_mask.size
    return blue_ratio >= MENU_BLUE_PIXEL_RATIO


def load_antimacro_header() -> None:
    global _antimacro_header
    _antimacro_header = cv2.imread(str(ANTIMACRO_HEADER_PATH), cv2.IMREAD_COLOR)
    if _antimacro_header is None:
        logging.warning(
            "[ANTI-MACRO] No se encontró %s; se usará solo la detección HSV.",
            ANTIMACRO_HEADER_PATH,
        )
    else:
        logging.info("[ANTI-MACRO] Plantilla cargada: %s", ANTIMACRO_HEADER_PATH)


async def recognize_antimacro_header(frame: np.ndarray, ocr: OcrEngine) -> str:
    frame_height, _ = frame.shape[:2]
    for _, timer_y, _, timer_height in find_antimacro_timer_bars(frame):
        header_y = max(0, timer_y - int(timer_height * 15.25))
        header = frame[
            header_y:min(frame_height, header_y + int(frame_height * 0.13)),
            :,
        ]
        enlarged = cv2.resize(
            header,
            None,
            fx=2.0,
            fy=2.0,
            interpolation=cv2.INTER_CUBIC,
        )
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        encoded_ok, encoded_header = cv2.imencode(".png", gray)
        if not encoded_ok:
            raise ValueError("No se pudo codificar la región de texto para OCR.")
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(encoded_header.tobytes())
        await writer.store_async()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        recognized = await ocr.recognize_async(bitmap)
        if is_antimacro_text_present(recognized.text):
            return recognized.text
    return ""


def is_antimacro_text_present(recognized_text: str) -> bool:
    normalized_text = unicodedata.normalize("NFKD", recognized_text)
    normalized_text = normalized_text.encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z0-9]+", normalized_text)
    antimacro_found = any(
        SequenceMatcher(None, word, "antimacro").ratio() >= 0.85
        for word in words
    )
    activated_found = any(
        SequenceMatcher(None, word, "activado").ratio() >= 0.85
        for word in words
    )
    return antimacro_found and activated_found


def find_antimacro_timer_bars(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    yellow_mask = cv2.inRange(
        hsv,
        np.array((15, 100, 100), dtype=np.uint8),
        np.array((40, 255, 255), dtype=np.uint8),
    )
    yellow_mask = cv2.morphologyEx(
        yellow_mask,
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
    )
    yellow_contours, _ = cv2.findContours(
        yellow_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    frame_height, frame_width = frame.shape[:2]
    timer_bars = []
    for contour in yellow_contours:
        x, y, width, height = cv2.boundingRect(contour)
        aspect_ratio = width / height if height else 0
        if (
            width < frame_width * 0.07
            or width > frame_width * 0.18
            or height < frame_height * 0.008
            or height > frame_height * 0.06
            or aspect_ratio < 4.5
            or y < frame_height * 0.08
            or y > frame_height * 0.95
        ):
            continue
        timer_bars.append((x, y, width, height))
    return sorted(timer_bars, key=lambda rect: rect[2], reverse=True)


def antimacro_ocr_worker(
    frames: Queue[np.ndarray],
    detection: threading.Event,
    shutdown: threading.Event,
) -> None:
    try:
        ocr = OcrEngine.try_create_from_user_profile_languages()
    except (OSError, RuntimeError) as exc:
        logging.error("[OCR] No se pudo inicializar Windows OCR (%s).", type(exc).__name__)
        return
    if ocr is None:
        logging.error(
            "[OCR] Windows no tiene un paquete de reconocimiento compatible con los idiomas del usuario."
        )
        return
    logging.info("[OCR] Windows OCR listo; idioma=%s.", ocr.recognizer_language.language_tag)
    loop = asyncio.new_event_loop()

    try:
        _run_antimacro_ocr(frames, detection, shutdown, ocr, loop)
    finally:
        loop.close()


def _run_antimacro_ocr(
    frames: Queue[np.ndarray],
    detection: threading.Event,
    shutdown: threading.Event,
    ocr: OcrEngine,
    loop: asyncio.AbstractEventLoop,
) -> None:
    while not shutdown.is_set():
        try:
            frame = frames.get(timeout=0.2)
        except Empty:
            continue
        if shutdown.wait(ANTIMACRO_OCR_INTERVAL):
            break
        try:
            recognized_text = loop.run_until_complete(
                recognize_antimacro_header(frame, ocr)
            )
            detected = is_antimacro_text_present(recognized_text)
        except (OSError, RuntimeError, ValueError, cv2.error) as exc:
            logging.error(
                "[OCR] Error al analizar el texto de la ventana (%s).",
                type(exc).__name__,
            )
            continue
        if detected != detection.is_set():
            logging.info(
                "[OCR] Texto 'Antimacro activado' %s.",
                "detectado" if detected else "ya no visible",
            )
        if detected:
            detection.set()
        else:
            detection.clear()


def enqueue_latest_frame(frames: Queue[np.ndarray], frame: np.ndarray) -> None:
    try:
        frames.put_nowait(frame.copy())
    except Full:
        try:
            frames.get_nowait()
        except Empty:
            pass
        try:
            frames.put_nowait(frame.copy())
        except Full:
            logging.warning("[OCR] No se pudo actualizar el fotograma pendiente.")


def is_antimacro_present(frame: np.ndarray, ocr_text_detected: bool = False) -> bool:
    if ocr_text_detected:
        return True
    if _antimacro_header is not None:
        template_height, template_width = _antimacro_header.shape[:2]
        frame_height, frame_width = frame.shape[:2]
        if template_width <= frame_width and template_height <= frame_height:
            match = cv2.matchTemplate(
                frame,
                _antimacro_header,
                cv2.TM_CCOEFF_NORMED,
            )
            if float(cv2.minMaxLoc(match)[1]) >= ANTIMACRO_MATCH_THRESHOLD:
                return True
    return False


def alarm_worker(alarm_active: threading.Event, shutdown: threading.Event) -> None:
    while not shutdown.is_set():
        if not alarm_active.is_set():
            shutdown.wait(0.1)
            continue
        try:
            winsound.Beep(1000, 450)
            if alarm_active.is_set() and not shutdown.is_set():
                winsound.Beep(1600, 450)
        except (RuntimeError, OSError) as exc:
            logging.error("[ALARMA] No se pudo reproducir el aviso: %s", exc)
            alarm_active.clear()


def save_antimacro_screenshot(frame: np.ndarray) -> Path | None:
    try:
        ANTIMACRO_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = ANTIMACRO_SCREENSHOT_DIR / f"antimacro_{timestamp}.png"
        if not cv2.imwrite(str(screenshot_path), frame):
            logging.error("[ANTI-MACRO] No se pudo guardar la captura en %s.", screenshot_path)
            return None
    except (OSError, cv2.error) as exc:
        logging.error("[ANTI-MACRO] Error al guardar la captura local: %s", exc)
        return None
    return screenshot_path


def load_telegram_credentials(env_path: Path = ENV_FILE) -> tuple[str, str]:
    if not env_path.exists():
        try:
            env_path.write_text(
                "TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n",
                encoding="utf-8",
            )
            logging.info("[TELEGRAM] Se creó %s; completa las credenciales.", env_path)
        except OSError as exc:
            logging.error("[TELEGRAM] No se pudo crear %s: %s", env_path, exc)

    if env_path.exists():
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                key = key.removeprefix("export ").strip()
                value = value.strip().strip("\"'")
                if key in {
                    "TELEGRAM_BOT_TOKEN",
                    "TELEGRAM_CHAT_ID",
                } and not os.getenv(key):
                    os.environ[key] = value
        except OSError as exc:
            logging.error("[TELEGRAM] No se pudo leer %s: %s", env_path, exc)

    return (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


def send_telegram_photo(screenshot_path: Path, token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with screenshot_path.open("rb") as photo:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "caption": "Alerta: reto anti-macro detectado."},
                files={"photo": (screenshot_path.name, photo, "image/png")},
                timeout=TELEGRAM_API_TIMEOUT,
            )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok", False):
            logging.error("[TELEGRAM] La API rechazó el envío de la captura.")
            return
        logging.info("[TELEGRAM] Captura del reto enviada.")
    except (OSError, requests.RequestException, ValueError) as exc:
        logging.error(
            "[TELEGRAM] Falló el envío de la captura (%s).",
            type(exc).__name__,
        )


def handle_remote_answer(option_index: int) -> None:
    raise NotImplementedError("La respuesta remota no está habilitada.")


class State:
    SEARCHING_TAB = "BUSCANDO (TAB)"
    ROTATING_CAMERA = "ROTANDO CÁMARA (CLIC DER.)"
    ATTACKING = "ATACANDO (VIDA > 0%)"
    ANTIMACRO_LOCKED = "ANTI-MACRO - RESOLVER MANUALMENTE"

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    hwnd = find_window(WINDOW_TITLE_CONTAINS)
    if hwnd is None:
        raise SystemExit(f"[ERROR] No se encontró ventana con: '{WINDOW_TITLE_CONTAINS}'.")

    window_title = win32gui.GetWindowText(hwnd)
    logging.info("[CONECTADO] DMO: %s", window_title)
    load_antimacro_header()
    telegram_token, telegram_chat_id = load_telegram_credentials()
    if not telegram_token or not telegram_chat_id:
        logging.warning(
            "[TELEGRAM] Sin credenciales configuradas; la captura solo se guardará localmente."
        )

    state = State.SEARCHING_TAB
    state_start_time = time.time()
    last_attack_time = 0.0
    last_tab_time = 0.0
    last_drag_time = 0.0
    tab_attempts = 0
    is_mouse_down = False
    menu_was_open = False
    last_target_status = None
    last_status_log = 0.0
    focus_warning_shown = False
    attack_inputs_since_status = 0
    antimacro_clear_since: float | None = None

    auto_enabled = True
    pause_hotkey_was_down = False
    stop_hotkey_was_down = False
    cv2.namedWindow("DMO Farm Bot", cv2.WINDOW_NORMAL)
    logging.info("[ATAJOS] Ctrl+Shift+P: pausar/reanudar | Ctrl+Shift+Q: detener")
    alarm_active = threading.Event()
    alarm_shutdown = threading.Event()
    ocr_shutdown = threading.Event()
    ocr_detection = threading.Event()
    ocr_frames: Queue[np.ndarray] = Queue(maxsize=1)
    alarm_thread = threading.Thread(
        target=alarm_worker,
        args=(alarm_active, alarm_shutdown),
        name="antimacro-alarm",
        daemon=True,
    )
    alarm_thread.start()
    ocr_thread = threading.Thread(
        target=antimacro_ocr_worker,
        args=(ocr_frames, ocr_detection, ocr_shutdown),
        name="antimacro-ocr",
        daemon=True,
    )
    ocr_thread.start()

    with mss.MSS() as sct:
        while True:
            loop_start = time.time()

            pause_hotkey_down = (
                is_key_down(VK_CONTROL)
                and is_key_down(VK_SHIFT)
                and is_key_down(VK_P)
            )
            stop_hotkey_down = (
                is_key_down(VK_CONTROL)
                and is_key_down(VK_SHIFT)
                and is_key_down(VK_Q)
            )

            if stop_hotkey_down and not stop_hotkey_was_down:
                logging.info("[DETENIDO] Atajo Ctrl+Shift+Q.")
                break
            if pause_hotkey_down and not pause_hotkey_was_down:
                auto_enabled = not auto_enabled
                if is_mouse_down:
                    mouse_right_up()
                    is_mouse_down = False
                if state != State.ANTIMACRO_LOCKED:
                    state = State.SEARCHING_TAB
                    logging.info("[PAUSADO]" if not auto_enabled else "[REANUDADO]")
                else:
                    logging.info(
                        "[ANTI-MACRO] Farming %s, pero sigue bloqueado hasta resolver el reto.",
                        "pausado" if not auto_enabled else "habilitado",
                    )

            pause_hotkey_was_down = pause_hotkey_down
            stop_hotkey_was_down = stop_hotkey_down

            if not win32gui.IsWindow(hwnd):
                if is_mouse_down:
                    mouse_right_up()
                    is_mouse_down = False
                logging.warning("[VENTANA] La ventana del juego ya no existe; deteniendo.")
                break

            client_rect = get_client_screen_rect(hwnd)
            now = time.time()
            full_roi = {
                "left": client_rect[0],
                "top": client_rect[1],
                "width": client_rect[2],
                "height": client_rect[3],
            }
            raw_screen = np.asarray(sct.grab(full_roi), dtype=np.uint8)
            frame = cv2.cvtColor(raw_screen, cv2.COLOR_BGRA2BGR)
            enqueue_latest_frame(ocr_frames, frame)
            antimacro_present = is_antimacro_present(frame, ocr_detection.is_set())

            if antimacro_present:
                antimacro_clear_since = None
                if state != State.ANTIMACRO_LOCKED:
                    state = State.ANTIMACRO_LOCKED
                    state_start_time = now
                    alarm_active.set()
                    mouse_right_up()
                    is_mouse_down = False
                    release_all_keys()
                    screenshot_path = save_antimacro_screenshot(frame)
                    logging.critical(
                        "[ANTI-MACRO] Detectado en '%s'; entradas bloqueadas. "
                        "Resuelve el reto manualmente. Captura local: %s",
                        window_title,
                        screenshot_path or "no disponible",
                    )
                    if screenshot_path and telegram_token and telegram_chat_id:
                        threading.Thread(
                            target=send_telegram_photo,
                            args=(screenshot_path, telegram_token, telegram_chat_id),
                            name="antimacro-telegram",
                            daemon=True,
                        ).start()
                else:
                    alarm_active.set()
            elif state == State.ANTIMACRO_LOCKED:
                if antimacro_clear_since is None:
                    antimacro_clear_since = now
                    logging.info(
                        "[ANTI-MACRO] No visible; verificando cierre antes de detener la alarma.",
                    )
                if now - antimacro_clear_since >= ANTIMACRO_ALARM_RELEASE_DELAY:
                    if alarm_active.is_set():
                        alarm_active.clear()
                        logging.info("[ANTI-MACRO] Alarma detenida; esperando cierre estable.")
                if now - antimacro_clear_since >= ANTIMACRO_CLEAR_DELAY:
                    logging.info(
                        "[ANTI-MACRO] Cierre estable por %.1f segundos; reanudando búsqueda.",
                        ANTIMACRO_CLEAR_DELAY,
                    )
                    state = State.SEARCHING_TAB
                    state_start_time = now
                    tab_attempts = 0
                    antimacro_clear_since = None

            if state == State.ANTIMACRO_LOCKED:
                target_alive, red_pixels, frame_exists = False, 0, False
                menu_open = False
            else:
                target_alive, red_pixels, frame_exists = check_target_status(sct, client_rect)
                menu_open = is_game_menu_open(sct, client_rect)

            target_status = (frame_exists, target_alive)
            if target_status != last_target_status:
                logging.info(
                    "[OBJETIVO] %s; marco=%s; píxeles rojos=%d",
                    "vida detectada" if target_alive else "sin vida detectable",
                    "detectado" if frame_exists else "no detectado",
                    red_pixels,
                )
                last_target_status = target_status

            if menu_open:
                if not menu_was_open:
                    logging.warning("[MENÚ] Detectado; automatización pausada hasta cerrarlo manualmente.")
                if is_mouse_down:
                    mouse_right_up()
                    is_mouse_down = False
                state = State.SEARCHING_TAB
                tab_attempts = 0
                menu_was_open = True
            else:
                if menu_was_open:
                    logging.info("[MENÚ] Cerrado; automatización disponible.")
                menu_was_open = False

            if state != State.ANTIMACRO_LOCKED and auto_enabled and not menu_open:
                if win32gui.GetForegroundWindow() != hwnd:
                    try:
                        focus_set = bool(win32gui.SetForegroundWindow(hwnd))
                        if not focus_set and not focus_warning_shown:
                            logging.warning("[VENTANA] Windows no confirmó el foco del juego.")
                        focus_warning_shown = not focus_set
                    except Exception as exc:
                        if not focus_warning_shown:
                            logging.warning("[VENTANA] No se pudo dar foco al juego: %s", exc)
                            focus_warning_shown = True

                if state == State.SEARCHING_TAB:
                    if is_mouse_down:
                        mouse_right_up()
                        is_mouse_down = False

                    if target_alive:
                        state = State.ATTACKING
                        state_start_time = now
                        tab_attempts = 0
                        logging.info("[ESTADO] Objetivo con vida seleccionado; iniciando ataque.")
                        if press_key_fast(KEY_1):
                            attack_inputs_since_status += 1
                    else:
                        if now - last_tab_time >= TAB_COOLDOWN:
                            press_key_fast(KEY_TAB)
                            last_tab_time = now
                            tab_attempts += 1

                        if tab_attempts >= 2:
                            state = State.ROTATING_CAMERA
                            state_start_time = now
                            tab_attempts = 0
                            logging.info("[ESTADO] Sin objetivo con vida tras TAB; girando cámara.")

                            cx = client_rect[0] + client_rect[2] // 2
                            cy = client_rect[1] + client_rect[3] // 2
                            ctypes.windll.user32.SetCursorPos(cx, cy)
                            mouse_right_down()
                            is_mouse_down = True

                elif state == State.ROTATING_CAMERA:
                    if target_alive:
                        if is_mouse_down:
                            mouse_right_up()
                            is_mouse_down = False
                        state = State.ATTACKING
                        state_start_time = now
                        logging.info("[ESTADO] Objetivo con vida detectado al girar; iniciando ataque.")
                        if press_key_fast(KEY_1):
                            attack_inputs_since_status += 1
                    else:
                        if now - last_drag_time >= DRAG_STEP_INTERVAL:
                            mouse_drag_relative(CAMERA_DRAG_STEP, 0)
                            last_drag_time = now

                        if now - last_tab_time >= TAB_COOLDOWN:
                            press_key_fast(KEY_TAB)
                            last_tab_time = now

                elif state == State.ATTACKING:
                    if is_mouse_down:
                        mouse_right_up()
                        is_mouse_down = False

                    if target_alive:
                        if now - last_attack_time >= ATTACK_KEY_INTERVAL:
                            if press_key_fast(KEY_1):
                                attack_inputs_since_status += 1
                            last_attack_time = now
                    else:
                        press_key_fast(KEY_TAB)
                        last_tab_time = now
                        tab_attempts = 0
                        state = State.SEARCHING_TAB
                        state_start_time = now
                        logging.info("[ESTADO] Vida no detectada; buscando el siguiente objetivo.")

            if now - last_status_log >= STATUS_LOG_INTERVAL:
                logging.info(
                    "[RESUMEN] estado=%s automatización=%s objetivo=%s marco=%s "
                    "rojos=%d TAB_pendientes=%d menú=%s clic_derecho=%s cliente=%dx%d "
                    "foco_juego=%s tiempo_estado=%.1fs ataques_insertados=%d",
                    state,
                    "activa" if auto_enabled else "pausada",
                    "con vida" if target_alive else "sin vida detectable",
                    "sí" if frame_exists else "no",
                    red_pixels,
                    tab_attempts,
                    "abierto" if menu_open else "cerrado",
                    "presionado" if is_mouse_down else "suelto",
                    client_rect[2],
                    client_rect[3],
                    "sí" if win32gui.GetForegroundWindow() == hwnd else "no",
                    now - state_start_time,
                    attack_inputs_since_status,
                )
                attack_inputs_since_status = 0
                last_status_log = now

            preview = frame.copy()

            w, h = client_rect[2], client_rect[3]

            fx1, fy1 = int(w * TARGET_FRAME_ROI[0]), int(h * TARGET_FRAME_ROI[1])
            fx2, fy2 = int(w * TARGET_FRAME_ROI[2]), int(h * TARGET_FRAME_ROI[3])
            cv2.rectangle(preview, (fx1, fy1), (fx2, fy2), (255, 200, 0), 1)

            hx1, hy1 = int(w * HP_BAR_ROI[0]), int(h * HP_BAR_ROI[1])
            hx2, hy2 = int(w * HP_BAR_ROI[2]), int(h * HP_BAR_ROI[3])
            hp_color = (0, 255, 0) if target_alive else (0, 0, 255)
            cv2.rectangle(preview, (hx1, hy1), (hx2, hy2), hp_color, 2)

            status_hp = "VIVO (> 0%)" if target_alive else ("MUERTO (0%)" if frame_exists else "SIN TARGET")
            status_state = (
                "MENÚ ABIERTO - CIERRE MANUAL"
                if menu_open
                else state
                if auto_enabled
                else "PAUSADO"
            )
            cv2.rectangle(preview, (10, 10), (430, 85), (0, 0, 0), -1)
            cv2.putText(preview, f"ESTADO: {status_state}", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(preview, f"Vida: {status_hp} (Rojo: {red_pixels}px)", (20, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, hp_color, 2)

            if state == State.ANTIMACRO_LOCKED:
                cv2.rectangle(preview, (0, 0), (w, 90), (0, 0, 220), -1)
                cv2.putText(
                    preview,
                    "ANTIMACRO DETECTADO - RESUELVA MANUALMENTE",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.70,
                    (255, 255, 255),
                    2,
                )
                cv2.putText(
                    preview,
                    f"Ventana: {window_title[:100]}",
                    (20, 72),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.50,
                    (255, 255, 255),
                    1,
                )

            resized_preview = cv2.resize(preview, None, fx=PREVIEW_SCALE, fy=PREVIEW_SCALE)
            cv2.imshow("DMO Farm Bot", resized_preview)

            cv2.waitKey(1)

            elapsed = time.time() - loop_start
            target_time = 1.0 / MAX_FPS
            if elapsed < target_time:
                time.sleep(target_time - elapsed)

    if is_mouse_down:
        mouse_right_up()
    alarm_active.clear()
    alarm_shutdown.set()
    ocr_shutdown.set()
    alarm_thread.join(timeout=1.0)
    if ocr_thread is not None:
        ocr_thread.join(timeout=2.0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()