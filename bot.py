from __future__ import annotations

import logging
import time
import ctypes

import cv2
import mss
import numpy as np
import win32gui

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
    return ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x)) == 1

def key_up(hex_code: int):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(0, hex_code, 0x0008 | 0x0002, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    return ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x)) == 1

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


class State:
    SEARCHING_TAB = "BUSCANDO (TAB)"
    ROTATING_CAMERA = "ROTANDO CÁMARA (CLIC DER.)"
    ATTACKING = "ATACANDO (VIDA > 0%)"

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    hwnd = find_window(WINDOW_TITLE_CONTAINS)
    if hwnd is None:
        raise SystemExit(f"[ERROR] No se encontró ventana con: '{WINDOW_TITLE_CONTAINS}'.")

    logging.info("[CONECTADO] DMO: %s", win32gui.GetWindowText(hwnd))

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

    auto_enabled = True
    pause_hotkey_was_down = False
    stop_hotkey_was_down = False
    cv2.namedWindow("DMO Farm Bot", cv2.WINDOW_NORMAL)
    logging.info("[ATAJOS] Ctrl+Shift+P: pausar/reanudar | Ctrl+Shift+Q: detener")

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
                state = State.SEARCHING_TAB
                logging.info("[PAUSADO]" if not auto_enabled else "[REANUDADO]")

            pause_hotkey_was_down = pause_hotkey_down
            stop_hotkey_was_down = stop_hotkey_down

            if not win32gui.IsWindow(hwnd):
                if is_mouse_down:
                    mouse_right_up()
                    is_mouse_down = False
                logging.warning("[VENTANA] La ventana del juego ya no existe; deteniendo.")
                break

            client_rect = get_client_screen_rect(hwnd)
            target_alive, red_pixels, frame_exists = check_target_status(sct, client_rect)
            menu_open = is_game_menu_open(sct, client_rect)
            now = time.time()
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

            if auto_enabled and not menu_open:
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

            full_roi = {"left": client_rect[0], "top": client_rect[1], "width": client_rect[2], "height": client_rect[3]}
            raw_screen = np.asarray(sct.grab(full_roi), dtype=np.uint8)
            preview = cv2.cvtColor(raw_screen, cv2.COLOR_BGRA2BGR)

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

            resized_preview = cv2.resize(preview, None, fx=PREVIEW_SCALE, fy=PREVIEW_SCALE)
            cv2.imshow("DMO Farm Bot", resized_preview)

            cv2.waitKey(1)

            elapsed = time.time() - loop_start
            target_time = 1.0 / MAX_FPS
            if elapsed < target_time:
                time.sleep(target_time - elapsed)

    if is_mouse_down:
        mouse_right_up()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()