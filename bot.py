"""Bot de farmeo para DMO en Windows.

Captura el área cliente de la ventana del juego, detecta la vida del objetivo y
usa una máquina de estados para buscarlo, atacar y girar la cámara.

Atajos globales (funcionan sin enfocar la vista previa):
    Ctrl+Shift+P: pausar o reanudar.
    Ctrl+Shift+Q: detener el bot sin cerrar la terminal.

Si la detección visual no coincide con la interfaz, ajustar los ROI y umbrales
de la sección de configuración antes de ejecutar.
"""

from __future__ import annotations

import time
import ctypes

import cv2
import mss
import numpy as np
import win32gui

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

WINDOW_TITLE_CONTAINS = "Client Version"

MAX_FPS = 30
PREVIEW_SCALE = 0.70

# ------------------------------------------------------------
# COORDENADAS EXACTAS DE LA BARRA DE VIDA (1920x1080)
# ------------------------------------------------------------
# Marco completo del objetivo (referencia visual)
TARGET_FRAME_ROI = (0.38, 0.015, 0.58, 0.11)

# Interior estricto de la barra de vida:
# Comienza DESPUÉS del chip [Vi] y termina ANTES del retrato.
# Excluye el icono de puño inferior.
HP_BAR_ROI = (0.442, 0.058, 0.505, 0.074)

# Umbral de brillo medio para saber si el marco general existe
TARGET_FRAME_MIN_BRIGHTNESS = 25.0

# Umbral estricto: en 0% hay 0 píxeles; con vida hay >250 píxeles
MIN_HP_RED_PIXELS = 50

# Región central donde aparece el panel del menú del juego.
MENU_PANEL_ROI = (0.30, 0.22, 0.70, 0.60)
MENU_BLUE_PIXEL_RATIO = 0.50
MENU_CLOSE_RETRY_INTERVAL = 0.75

# ------------------------------------------------------------
# TECLAS (Scan Codes DirectInput)
# ------------------------------------------------------------
KEY_ESC = 0x01  # Cancelar target / deseleccionar cadáver
KEY_TAB = 0x0F  # Seleccionar objetivo más cercano
KEY_1 = 0x02    # Habilidad / Ataque básico

# Atajos globales: funcionan aunque la ventana de vista previa no tenga el foco.
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_P = 0x50
VK_Q = 0x51

# ------------------------------------------------------------
# TEMPORIZADORES Y VELOCIDAD DE RESPUESTA
# ------------------------------------------------------------
ATTACK_KEY_INTERVAL = 0.40      # Cadencia al pulsar la tecla '1'
TAB_COOLDOWN = 0.25             # Pausa mínima entre intentos de pulsar TAB
CAMERA_DRAG_STEP = 38           # Píxeles de giro por cada paso de arrastre
DRAG_STEP_INTERVAL = 0.035      # Intervalo de movimiento del ratón


# ============================================================
# CONTROL NATIVO DE RATÓN Y TECLADO (WIN32 API)
# ============================================================

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
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def key_up(hex_code: int):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(0, hex_code, 0x0008 | 0x0002, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(1), ii_)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def press_key_fast(hex_code: int):
    key_down(hex_code)
    key_up(hex_code)

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


# ============================================================
# DETECCIÓN DE VENTANA Y CONDICIÓN DE VIDA (> 0%)
# ============================================================

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
    """
    Retorna: (is_alive, red_pixels, frame_exists)
    is_alive es True ÚNICAMENTE si el marco existe Y la barra interior tiene vida roja (> 0%).
    """
    # 1. Comprobar si el marco UI existe en pantalla
    frame_roi = get_roi_rect(client_rect, TARGET_FRAME_ROI)
    raw_frame = np.asarray(sct.grab(frame_roi), dtype=np.uint8)
    gray_frame = cv2.cvtColor(raw_frame[:, :, :3], cv2.COLOR_BGR2GRAY)
    frame_exists = float(np.mean(gray_frame)) >= TARGET_FRAME_MIN_BRIGHTNESS

    # 2. Medir píxeles de color rojo/naranja dentro de la barra de vida
    hp_roi = get_roi_rect(client_rect, HP_BAR_ROI)
    raw_hp = np.asarray(sct.grab(hp_roi), dtype=np.uint8)
    bgr_hp = raw_hp[:, :, :3]

    r = bgr_hp[:, :, 2].astype(int)
    g = bgr_hp[:, :, 1].astype(int)
    b = bgr_hp[:, :, 0].astype(int)

    red_mask = (r > 105) & (r > g + 25) & (r > b + 25)
    red_count = int(np.count_nonzero(red_mask))

    # Solo está vivo si el marco existe Y supera los píxeles de vida (> 0%)
    is_alive = frame_exists and (red_count >= MIN_HP_RED_PIXELS)

    return is_alive, red_count, frame_exists


def is_game_menu_open(sct: mss.MSS, client_rect: tuple[int, int, int, int]) -> bool:
    """Detecta el panel azul del menú de DMO en la zona central de la ventana."""
    menu_roi = get_roi_rect(client_rect, MENU_PANEL_ROI)
    raw_menu = np.asarray(sct.grab(menu_roi), dtype=np.uint8)
    hsv_menu = cv2.cvtColor(raw_menu[:, :, :3], cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(
        hsv_menu,
        np.array((90, 80, 20), dtype=np.uint8),
        np.array((135, 255, 220), dtype=np.uint8),
    )
    blue_ratio = float(np.count_nonzero(blue_mask)) / blue_mask.size
    return blue_ratio >= MENU_BLUE_PIXEL_RATIO


# ============================================================
# MÁQUINA DE ESTADOS Y BUCLE PRINCIPAL
# ============================================================

class State:
    SEARCHING_TAB = "BUSCANDO (TAB)"
    ROTATING_CAMERA = "ROTANDO CÁMARA (CLIC DER.)"
    ATTACKING = "ATACANDO (VIDA > 0%)"

def main():
    """Conecta con la ventana de DMO y ejecuta el ciclo de detección y combate."""
    hwnd = find_window(WINDOW_TITLE_CONTAINS)
    if hwnd is None:
        raise SystemExit(f"[ERROR] No se encontró ventana con: '{WINDOW_TITLE_CONTAINS}'.")

    print(f"[CONECTADO] DMO: {win32gui.GetWindowText(hwnd)}")

    state = State.SEARCHING_TAB
    state_start_time = time.time()
    last_attack_time = 0.0
    last_tab_time = 0.0
    last_drag_time = 0.0
    last_menu_escape_time = 0.0
    tab_attempts = 0
    is_mouse_down = False
    menu_was_open = False

    auto_enabled = True
    pause_hotkey_was_down = False
    stop_hotkey_was_down = False
    cv2.namedWindow("DMO Farm Bot", cv2.WINDOW_NORMAL)
    print("[ATAJOS] Ctrl+Shift+P: pausar/reanudar | Ctrl+Shift+Q: detener")

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
                print("[DETENIDO] Atajo Ctrl+Shift+Q.")
                break
            if pause_hotkey_down and not pause_hotkey_was_down:
                auto_enabled = not auto_enabled
                if is_mouse_down:
                    mouse_right_up()
                    is_mouse_down = False
                state = State.SEARCHING_TAB
                print("[PAUSADO]" if not auto_enabled else "[REANUDADO]")

            pause_hotkey_was_down = pause_hotkey_down
            stop_hotkey_was_down = stop_hotkey_down

            if not win32gui.IsWindow(hwnd):
                if is_mouse_down:
                    mouse_right_up()
                break

            client_rect = get_client_screen_rect(hwnd)
            target_alive, red_pixels, frame_exists = check_target_status(sct, client_rect)
            menu_open = is_game_menu_open(sct, client_rect)
            now = time.time()

            if menu_open:
                if not menu_was_open:
                    print("[MENÚ] Detectado; esperando a que se cierre.")
                if is_mouse_down:
                    mouse_right_up()
                    is_mouse_down = False
                state = State.SEARCHING_TAB
                tab_attempts = 0
                if now - last_menu_escape_time >= MENU_CLOSE_RETRY_INTERVAL:
                    press_key_fast(KEY_ESC)
                    last_menu_escape_time = now
                menu_was_open = True
            else:
                menu_was_open = False

            if auto_enabled and not menu_open:
                if win32gui.GetForegroundWindow() != hwnd:
                    try:
                        win32gui.SetForegroundWindow(hwnd)
                    except Exception:
                        pass

                # --- 1. BUSCANDO OBJETIVO CON TAB ---
                if state == State.SEARCHING_TAB:
                    if is_mouse_down:
                        mouse_right_up()
                        is_mouse_down = False

                    if target_alive:
                        # Objetivo válido con vida > 0%: atacar
                        state = State.ATTACKING
                        state_start_time = now
                        tab_attempts = 0
                        press_key_fast(KEY_1)
                    else:
                        # Si quedó el marco pegado al 0%, deseleccionar con ESC
                        if frame_exists and not target_alive:
                            press_key_fast(KEY_ESC)
                            last_tab_time = now
                            tab_attempts = 0
                        else:
                            # Pulsar TAB periódicamente para seleccionar otro
                            if now - last_tab_time >= TAB_COOLDOWN:
                                press_key_fast(KEY_TAB)
                                last_tab_time = now
                                tab_attempts += 1

                            # Si tras 2 intentos no engancha nada vivo, rotar cámara
                            if tab_attempts >= 2:
                                state = State.ROTATING_CAMERA
                                state_start_time = now
                                tab_attempts = 0

                                # Iniciar arrastre con clic derecho
                                cx = client_rect[0] + client_rect[2] // 2
                                cy = client_rect[1] + client_rect[3] // 2
                                ctypes.windll.user32.SetCursorPos(cx, cy)
                                mouse_right_down()
                                is_mouse_down = True

                # --- 2. ROTANDO CÁMARA CON CLIC DERECHO ---
                elif state == State.ROTATING_CAMERA:
                    if target_alive:
                        # Enemigo vivo avistado y seleccionado: soltar clic y atacar
                        if is_mouse_down:
                            mouse_right_up()
                            is_mouse_down = False
                        state = State.ATTACKING
                        state_start_time = now
                        press_key_fast(KEY_1)
                    else:
                        # Arrastre horizontal constante
                        if now - last_drag_time >= DRAG_STEP_INTERVAL:
                            mouse_drag_relative(CAMERA_DRAG_STEP, 0)
                            last_drag_time = now

                        # Pulsar TAB mientras gira
                        if now - last_tab_time >= TAB_COOLDOWN:
                            press_key_fast(KEY_TAB)
                            last_tab_time = now

                # --- 3. ATACANDO (SOLO MIENTRAS VIDA > 0%) ---
                elif state == State.ATTACKING:
                    if is_mouse_down:
                        mouse_right_up()
                        is_mouse_down = False

                    if target_alive:
                        if now - last_attack_time >= ATTACK_KEY_INTERVAL:
                            press_key_fast(KEY_1)
                            last_attack_time = now
                    else:
                        # ¡ENEMIGO AL 0% O SIN BARRA!
                        # ESC puede abrir el menú; no enviar más teclas en este ciclo.
                        press_key_fast(KEY_ESC)
                        last_tab_time = now
                        tab_attempts = 0
                        state = State.SEARCHING_TAB
                        state_start_time = now

            # --- MONITOR VISUAL DE CONFIRMACIÓN ---
            full_roi = {"left": client_rect[0], "top": client_rect[1], "width": client_rect[2], "height": client_rect[3]}
            raw_screen = np.asarray(sct.grab(full_roi), dtype=np.uint8)
            preview = cv2.cvtColor(raw_screen, cv2.COLOR_BGRA2BGR)

            w, h = client_rect[2], client_rect[3]

            # Caja exterior del marco
            fx1, fy1 = int(w * TARGET_FRAME_ROI[0]), int(h * TARGET_FRAME_ROI[1])
            fx2, fy2 = int(w * TARGET_FRAME_ROI[2]), int(h * TARGET_FRAME_ROI[3])
            cv2.rectangle(preview, (fx1, fy1), (fx2, fy2), (255, 200, 0), 1)

            # Caja exacta interior de la barra de vida
            hx1, hy1 = int(w * HP_BAR_ROI[0]), int(h * HP_BAR_ROI[1])
            hx2, hy2 = int(w * HP_BAR_ROI[2]), int(h * HP_BAR_ROI[3])
            hp_color = (0, 255, 0) if target_alive else (0, 0, 255)
            cv2.rectangle(preview, (hx1, hy1), (hx2, hy2), hp_color, 2)

            # Telemetría en pantalla
            status_hp = "VIVO (> 0%)" if target_alive else ("MUERTO (0%)" if frame_exists else "SIN TARGET")
            status_state = "MENÚ ABIERTO - CERRANDO" if menu_open else (
                state if auto_enabled else "PAUSADO"
            )
            cv2.rectangle(preview, (10, 10), (430, 85), (0, 0, 0), -1)
            cv2.putText(preview, f"ESTADO: {status_state}", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(preview, f"Vida: {status_hp} (Rojo: {red_pixels}px)", (20, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, hp_color, 2)

            resized_preview = cv2.resize(preview, None, fx=PREVIEW_SCALE, fy=PREVIEW_SCALE)
            cv2.imshow("DMO Farm Bot", resized_preview)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord('q')):
                if is_mouse_down:
                    mouse_right_up()
                break

            elapsed = time.time() - loop_start
            target_time = 1.0 / MAX_FPS
            if elapsed < target_time:
                time.sleep(target_time - elapsed)

    if is_mouse_down:
        mouse_right_up()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()