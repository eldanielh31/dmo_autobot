import asyncio
import logging
import os
import re
import threading
import unicodedata
import winsound
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from queue import Empty, Full, Queue

import cv2
import numpy as np
import requests
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

from config import (
    ANTIMACRO_HEADER_PATH,
    ANTIMACRO_MATCH_THRESHOLD,
    ANTIMACRO_OCR_INTERVAL,
    ANTIMACRO_SCREENSHOT_DIR,
    ENV_FILE,
    TELEGRAM_API_TIMEOUT,
)

_header_template: np.ndarray | None = None


def load_antimacro_header() -> None:
    global _header_template
    _header_template = cv2.imread(str(ANTIMACRO_HEADER_PATH), cv2.IMREAD_COLOR)
    if _header_template is None:
        logging.warning(
            "[ANTI-MACRO] No se encontró %s; se usará detección por color y OCR.",
            ANTIMACRO_HEADER_PATH,
        )
    else:
        logging.info("[ANTI-MACRO] Plantilla cargada: %s", ANTIMACRO_HEADER_PATH)


def find_timer_bars(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
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
    contours, _ = cv2.findContours(
        yellow_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    frame_height, frame_width = frame.shape[:2]
    timer_bars = []
    for contour in contours:
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


def is_antimacro_text_present(recognized_text: str) -> bool:
    normalized = unicodedata.normalize("NFKD", recognized_text)
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z0-9]+", normalized)
    antimacro_found = any(
        SequenceMatcher(None, word, "antimacro").ratio() >= 0.85
        for word in words
    )
    activated_found = any(
        SequenceMatcher(None, word, "activado").ratio() >= 0.85
        for word in words
    )
    return antimacro_found and activated_found


async def recognize_text(image: np.ndarray, ocr: OcrEngine) -> str:
    encoded_ok, encoded_image = cv2.imencode(".png", image)
    if not encoded_ok:
        raise ValueError("No se pudo codificar la región de texto para OCR.")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(encoded_image.tobytes())
    await writer.store_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    recognized = await ocr.recognize_async(bitmap)
    return recognized.text


async def recognize_antimacro_header(frame: np.ndarray, ocr: OcrEngine) -> str:
    frame_height, _ = frame.shape[:2]
    for _, timer_y, _, timer_height in find_timer_bars(frame):
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
        recognized_text = await recognize_text(gray, ocr)
        if is_antimacro_text_present(recognized_text):
            return recognized_text
    return ""


def _ocr_worker(
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
                    "[OCR] Error al analizar el aviso anti-macro (%s).",
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
    finally:
        loop.close()


def start_ocr_worker(
    frames: Queue[np.ndarray],
    detection: threading.Event,
    shutdown: threading.Event,
) -> threading.Thread:
    thread = threading.Thread(
        target=_ocr_worker,
        args=(frames, detection, shutdown),
        name="antimacro-ocr",
        daemon=True,
    )
    thread.start()
    return thread


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


def is_antimacro_present(frame: np.ndarray, ocr_detected: bool = False) -> bool:
    if ocr_detected:
        return True
    if _header_template is None:
        return False
    template_height, template_width = _header_template.shape[:2]
    frame_height, frame_width = frame.shape[:2]
    if template_width > frame_width or template_height > frame_height:
        return False
    match = cv2.matchTemplate(frame, _header_template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(match)[1]) >= ANTIMACRO_MATCH_THRESHOLD


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
    file_values: dict[str, str] = {}
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
            for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                key = key.removeprefix("export ").strip()
                value = value.strip().strip("\"'")
                if key in {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}:
                    file_values[key] = value
        except OSError as exc:
            logging.error("[TELEGRAM] No se pudo leer %s: %s", env_path, exc)

    return (
        (
            file_values.get("TELEGRAM_BOT_TOKEN")
            or os.getenv("TELEGRAM_BOT_TOKEN", "")
        ).strip(),
        (
            file_values.get("TELEGRAM_CHAT_ID")
            or os.getenv("TELEGRAM_CHAT_ID", "")
        ).strip(),
    )


def send_telegram_message(message: str, token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            data={"chat_id": chat_id, "text": message},
            timeout=TELEGRAM_API_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or not result.get("ok", False):
            logging.error(
                "[TELEGRAM] La API rechazó el mensaje para chat_id=%s: %s",
                chat_id,
                _telegram_api_description(result),
            )
            return
        logging.info("[TELEGRAM] Notificación de estado enviada.")
    except (requests.RequestException, ValueError) as exc:
        logging.error(
            "[TELEGRAM] Falló el envío de la notificación a chat_id=%s (%s: %s).",
            chat_id,
            type(exc).__name__,
            _telegram_request_error(exc),
        )


def _telegram_api_description(payload: object) -> str:
    if isinstance(payload, dict):
        description = payload.get("description")
        if isinstance(description, str) and description:
            return description[:300]
    return "respuesta no válida de Telegram"


def _telegram_request_error(error: Exception) -> str:
    if isinstance(error, requests.HTTPError) and error.response is not None:
        try:
            payload = error.response.json()
        except ValueError:
            return f"HTTP {error.response.status_code}"
        return _telegram_api_description(payload)
    return type(error).__name__


def send_telegram_photo(
    screenshot_path: Path,
    token: str,
    chat_id: str,
    caption: str = "Alerta: reto anti-macro detectado.",
) -> None:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with screenshot_path.open("rb") as photo:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": (screenshot_path.name, photo, "image/png")},
                timeout=TELEGRAM_API_TIMEOUT,
            )
        response.raise_for_status()
        if not response.json().get("ok", False):
            logging.error("[TELEGRAM] La API rechazó el envío de la captura.")
            return
        logging.info("[TELEGRAM] Captura del reto enviada.")
    except (OSError, requests.RequestException, ValueError) as exc:
        logging.error(
            "[TELEGRAM] Falló el envío de la captura (%s).",
            type(exc).__name__,
        )
