from __future__ import annotations

import logging
import threading
import time
from queue import Queue

import cv2
import mss
import numpy as np
import win32gui

from antimacro import (
    alarm_worker,
    enqueue_latest_frame,
    is_antimacro_present,
    load_antimacro_header,
    load_telegram_credentials,
    save_antimacro_screenshot,
    send_telegram_photo,
    start_ocr_worker,
)
from combat import CombatActions, CombatController
from config import (
    ANTIMACRO_ALARM_RELEASE_DELAY,
    ANTIMACRO_CLEAR_DELAY,
    CAMERA_DRAG_STEP,
    KEY_1,
    KEY_TAB,
    MAX_FPS,
    PREVIEW_SCALE,
    STATUS_LOG_INTERVAL,
    VK_CONTROL,
    VK_MENU,
    VK_P,
    VK_Q,
    VK_SHIFT,
    WINDOW_TITLE_CONTAINS,
)
from game_input import (
    find_window,
    get_client_screen_rect,
    is_key_down,
    mouse_drag_relative,
    mouse_right_down,
    mouse_right_up,
    press_key_fast,
    release_all_keys,
    set_cursor_position,
)
from target_detection import (
    MenuOpenConfirmation,
    TargetStatus,
    check_target_status,
    get_banner_preview_rect,
    get_target_bar_preview_rect,
    is_game_menu_open,
)

WINDOW_NAME = "DMO Farm Bot"
HOTKEYS_MESSAGE = "Ctrl+Alt+P: pausar/reanudar | Ctrl+Shift+Q: detener"


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def draw_preview(
    frame: np.ndarray,
    target: TargetStatus,
    controller: CombatController,
    auto_enabled: bool,
    menu_open: bool,
    antimacro_locked: bool,
    window_title: str,
) -> np.ndarray:
    preview = frame.copy()
    frame_width = preview.shape[1]

    banner_start, banner_end = get_banner_preview_rect(preview.shape)
    cv2.rectangle(preview, banner_start, banner_end, (255, 200, 0), 1)

    bar_start, bar_end = get_target_bar_preview_rect(preview.shape)
    bar_color = (0, 255, 0) if target.has_life else (0, 0, 255)
    cv2.rectangle(preview, bar_start, bar_end, bar_color, 2)

    state_text = (
        "ANTI-MACRO - RESOLVER MANUALMENTE"
        if antimacro_locked
        else "MENÚ ABIERTO - CIERRE MANUAL"
        if menu_open
        else controller.state.value
        if auto_enabled
        else "PAUSADO"
    )
    hp_text = (
        "VIVO"
        if target.has_life
        else "0% / BARRA VACÍA"
        if target.bar_empty
        else "SIN BANNER"
        if not target.banner_visible
        else "SIN VIDA DETECTABLE"
    )
    cv2.rectangle(preview, (10, 10), (480, 88), (0, 0, 0), -1)
    cv2.putText(
        preview,
        f"ESTADO: {state_text}",
        (20, 36),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 255),
        2,
    )
    cv2.putText(
        preview,
        f"Vida: {hp_text} (Rojo: {target.red_pixels}px)",
        (20, 68),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        bar_color,
        2,
    )

    if antimacro_locked:
        cv2.rectangle(preview, (0, 0), (frame_width, 90), (0, 0, 220), -1)
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

    return cv2.resize(preview, None, fx=PREVIEW_SCALE, fy=PREVIEW_SCALE)


def send_combat_actions(
    actions: CombatActions,
    client_rect: tuple[int, int, int, int],
    mouse_is_down: bool,
) -> tuple[bool, bool]:
    attack_inserted = False
    if actions.stop_rotation and mouse_is_down:
        mouse_right_up()
        mouse_is_down = False

    if actions.press_tab:
        press_key_fast(KEY_TAB)
    if actions.attack:
        attack_inserted = press_key_fast(KEY_1)

    if actions.start_rotation and not mouse_is_down:
        center_x = client_rect[0] + client_rect[2] // 2
        center_y = client_rect[1] + client_rect[3] // 2
        set_cursor_position(center_x, center_y)
        mouse_right_down()
        mouse_is_down = True

    if actions.drag_camera and mouse_is_down:
        mouse_drag_relative(CAMERA_DRAG_STEP, 0)
    return mouse_is_down, attack_inserted


def main() -> None:
    configure_logging()
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

    controller = CombatController()
    menu_confirmation = MenuOpenConfirmation()
    mouse_is_down = False
    auto_enabled = True
    menu_was_open = False
    antimacro_locked = False
    antimacro_clear_since: float | None = None
    state_started_at = time.time()
    last_target_log: tuple[bool, bool, bool] | None = None
    last_status_log = 0.0
    attack_inputs_since_status = 0
    pause_hotkey_was_down = False
    stop_hotkey_was_down = False
    focus_warning_shown = False

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    logging.info("[ATAJOS] %s", HOTKEYS_MESSAGE)

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
    ocr_thread = start_ocr_worker(ocr_frames, ocr_detection, ocr_shutdown)

    try:
        with mss.MSS() as sct:
            while True:
                loop_start = time.time()
                pause_hotkey_down = (
                    is_key_down(VK_CONTROL)
                    and is_key_down(VK_MENU)
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
                    controller.reset_search()
                    state_started_at = time.time()
                    if mouse_is_down:
                        mouse_right_up()
                        mouse_is_down = False
                    logging.info("[PAUSADO]" if not auto_enabled else "[REANUDADO]")
                pause_hotkey_was_down = pause_hotkey_down
                stop_hotkey_was_down = stop_hotkey_down

                if not win32gui.IsWindow(hwnd):
                    logging.warning("[VENTANA] La ventana del juego ya no existe; deteniendo.")
                    break

                client_rect = get_client_screen_rect(hwnd)
                now = time.time()
                screen_rect = {
                    "left": client_rect[0],
                    "top": client_rect[1],
                    "width": client_rect[2],
                    "height": client_rect[3],
                }
                raw_screen = np.asarray(sct.grab(screen_rect), dtype=np.uint8)
                frame = cv2.cvtColor(raw_screen, cv2.COLOR_BGRA2BGR)
                enqueue_latest_frame(ocr_frames, frame)
                antimacro_present = is_antimacro_present(frame, ocr_detection.is_set())

                if antimacro_present:
                    antimacro_clear_since = None
                    if not antimacro_locked:
                        antimacro_locked = True
                        controller.reset_search()
                        state_started_at = now
                        alarm_active.set()
                        if mouse_is_down:
                            mouse_right_up()
                            mouse_is_down = False
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
                elif antimacro_locked:
                    if antimacro_clear_since is None:
                        antimacro_clear_since = now
                        logging.info(
                            "[ANTI-MACRO] No visible; verificando cierre antes de detener la alarma."
                        )
                    if now - antimacro_clear_since >= ANTIMACRO_ALARM_RELEASE_DELAY:
                        if alarm_active.is_set():
                            alarm_active.clear()
                            logging.info(
                                "[ANTI-MACRO] Alarma detenida; esperando cierre estable."
                            )
                    if now - antimacro_clear_since >= ANTIMACRO_CLEAR_DELAY:
                        antimacro_locked = False
                        controller.reset_search()
                        state_started_at = now
                        antimacro_clear_since = None
                        logging.info(
                            "[ANTI-MACRO] Cierre estable; reanudando búsqueda con TAB."
                        )

                if antimacro_locked:
                    target = TargetStatus(banner_visible=False, red_pixels=0)
                    menu_open = menu_confirmation.update(False)
                else:
                    target = check_target_status(frame)
                    menu_open = menu_confirmation.update(is_game_menu_open(frame))

                target_log = (
                    target.banner_visible,
                    target.has_life,
                    target.bar_empty,
                )
                if target_log != last_target_log:
                    logging.info(
                        "[OBJETIVO] banner=%s; vida=%s; barra_vacía=%s; píxeles_rojos=%d",
                        "visible" if target.banner_visible else "no visible",
                        "detectada" if target.has_life else "no detectada",
                        "sí" if target.bar_empty else "no",
                        target.red_pixels,
                    )
                    last_target_log = target_log

                if menu_open:
                    if not menu_was_open:
                        logging.warning(
                            "[MENÚ] Detectado; automatización pausada hasta cerrarlo manualmente."
                        )
                        state_started_at = now
                    controller.reset_search()
                    if mouse_is_down:
                        mouse_right_up()
                        mouse_is_down = False
                    menu_was_open = True
                else:
                    if menu_was_open:
                        logging.info("[MENÚ] Cerrado; automatización disponible.")
                        state_started_at = now
                    menu_was_open = False

                if not antimacro_locked and auto_enabled and not menu_open:
                    if win32gui.GetForegroundWindow() != hwnd:
                        try:
                            focus_set = bool(win32gui.SetForegroundWindow(hwnd))
                            if not focus_set and not focus_warning_shown:
                                logging.warning(
                                    "[VENTANA] Windows no confirmó el foco del juego."
                                )
                            focus_warning_shown = not focus_set
                        except Exception as exc:
                            if not focus_warning_shown:
                                logging.warning(
                                    "[VENTANA] No se pudo dar foco al juego: %s", exc
                                )
                                focus_warning_shown = True

                    previous_state = controller.state
                    actions = controller.update(target, now)
                    mouse_is_down, attack_inserted = send_combat_actions(
                        actions,
                        client_rect,
                        mouse_is_down,
                    )
                    if attack_inserted:
                        attack_inputs_since_status += 1
                    if controller.state is not previous_state:
                        state_started_at = now
                        logging.info(
                            "[ESTADO] %s -> %s",
                            previous_state.value,
                            controller.state.value,
                        )

                if now - last_status_log >= STATUS_LOG_INTERVAL:
                    logging.info(
                        "[RESUMEN] estado=%s automatización=%s objetivo=%s banner=%s "
                        "rojos=%d barra_vacía=%s TAB_pendientes=%d menú=%s "
                        "clic_derecho=%s cliente=%dx%d foco_juego=%s "
                        "tiempo_estado=%.1fs ataques_insertados=%d",
                        controller.state.value,
                        "activa" if auto_enabled else "pausada",
                        "con vida" if target.has_life else "sin vida detectable",
                        "sí" if target.banner_visible else "no",
                        target.red_pixels,
                        "sí" if target.bar_empty else "no",
                        controller.tab_attempts,
                        "abierto" if menu_open else "cerrado",
                        "presionado" if mouse_is_down else "suelto",
                        client_rect[2],
                        client_rect[3],
                        "sí" if win32gui.GetForegroundWindow() == hwnd else "no",
                        now - state_started_at,
                        attack_inputs_since_status,
                    )
                    attack_inputs_since_status = 0
                    last_status_log = now

                preview = draw_preview(
                    frame,
                    target,
                    controller,
                    auto_enabled,
                    menu_open,
                    antimacro_locked,
                    window_title,
                )
                cv2.imshow(WINDOW_NAME, preview)
                cv2.waitKey(1)

                elapsed = time.time() - loop_start
                frame_time = 1.0 / MAX_FPS
                if elapsed < frame_time:
                    time.sleep(frame_time - elapsed)
    finally:
        if mouse_is_down:
            mouse_right_up()
        release_all_keys()
        alarm_active.clear()
        alarm_shutdown.set()
        ocr_shutdown.set()
        alarm_thread.join(timeout=1.0)
        ocr_thread.join(timeout=2.0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
