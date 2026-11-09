from dataclasses import dataclass

import cv2
import numpy as np

from config import (
    HP_BAR_ROI,
    MENU_BLUE_MIN_SATURATION,
    MENU_BLUE_PIXEL_RATIO,
    MENU_PANEL_ROI,
    MIN_HP_RED_PIXELS,
    TARGET_FRAME_ROI,
    TARGET_NAME_ROI,
)

RelativeROI = tuple[float, float, float, float]


@dataclass(frozen=True)
class TargetStatus:
    banner_visible: bool
    red_pixels: int
    name_matches: bool | None = None
    require_name_match: bool = False

    @property
    def has_life(self) -> bool:
        return (
            self.banner_visible
            and self.name_matches is not False
            and (not self.require_name_match or self.name_matches is True)
            and self.red_pixels >= MIN_HP_RED_PIXELS
        )

    @property
    def bar_empty(self) -> bool:
        return (
            self.banner_visible
            and self.name_matches is not False
            and (not self.require_name_match or self.name_matches is True)
            and self.red_pixels < MIN_HP_RED_PIXELS
        )


class MenuOpenConfirmation:
    def __init__(self, required_frames: int = 3) -> None:
        self._required_frames = required_frames
        self._detected_frames = 0

    def update(self, detected: bool) -> bool:
        self._detected_frames = self._detected_frames + 1 if detected else 0
        return self._detected_frames >= self._required_frames


def get_roi_slice(frame: np.ndarray, roi: RelativeROI) -> np.ndarray:
    if frame.ndim < 2 or frame.shape[0] == 0 or frame.shape[1] == 0:
        raise ValueError("No se puede extraer un ROI de un frame vacío o inválido.")

    frame_height, frame_width = frame.shape[:2]
    try:
        x1, y1, x2, y2 = roi
        valid_roi = 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1
    except (TypeError, ValueError):
        valid_roi = False
    if not valid_roi:
        raise ValueError(
            f"ROI inválido {roi}: se espera (x1, y1, x2, y2) "
            "con 0 <= x1 < x2 <= 1 y 0 <= y1 < y2 <= 1."
        )
    left = int(frame_width * x1)
    top = int(frame_height * y1)
    right = int(frame_width * x2)
    bottom = int(frame_height * y2)
    if right <= left or bottom <= top:
        raise ValueError(
            f"El ROI {roi} genera un recorte vacío en un frame "
            f"de {frame_width}x{frame_height}."
        )
    return frame[top:bottom, left:right]


def get_target_name_region(frame: np.ndarray) -> np.ndarray:
    target_banner = get_roi_slice(frame, TARGET_FRAME_ROI)
    return get_roi_slice(target_banner, TARGET_NAME_ROI)


def get_target_name_signature(frame: np.ndarray) -> bytes:
    name_region = get_target_name_region(frame)
    gray_name = cv2.cvtColor(name_region, cv2.COLOR_BGR2GRAY)
    bright_text_mask = cv2.inRange(gray_name, 190, 255)
    normalized_mask = cv2.resize(
        bright_text_mask,
        (128, 32),
        interpolation=cv2.INTER_NEAREST,
    )
    return np.packbits(normalized_mask > 0).tobytes()


def _count_reliable_red_pixels(red_mask: np.ndarray) -> int:
    fill_start = red_mask.shape[0] // 6
    fill_end = red_mask.shape[0] * 5 // 6
    side_margin = max(1, int(red_mask.shape[1] * 0.01))
    fill_mask = red_mask[fill_start:fill_end, side_margin:-side_margin]
    component_count, _, stats, _ = cv2.connectedComponentsWithStats(
        fill_mask.astype(np.uint8),
        connectivity=8,
    )
    reliable_red_pixels = 0
    for index in range(1, component_count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        aspect_ratio = width / float(height)
        small_fill = (
            2 <= width <= max(3, red_mask.shape[1] * 0.06)
            and height >= max(3, int(red_mask.shape[0] * 0.25))
            and aspect_ratio >= 0.30
            and area >= MIN_HP_RED_PIXELS
        )
        regular_fill = (
            width >= max(8, red_mask.shape[1] * 0.08)
            and height >= max(2, red_mask.shape[0] * 0.35)
            and aspect_ratio >= 2.0
        )
        if not (small_fill or regular_fill):
            continue
        min_density = 0.50 if small_fill else 0.65
        if area / float(width * height) < min_density:
            continue
        reliable_red_pixels += area
    return reliable_red_pixels


def _has_target_banner(target_banner: np.ndarray) -> bool:
    hsv_banner = cv2.cvtColor(target_banner, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(
        hsv_banner,
        np.array((85, 120, 150), dtype=np.uint8),
        np.array((130, 255, 255), dtype=np.uint8),
    )
    component_count, _, stats, _ = cv2.connectedComponentsWithStats(
        blue_mask,
        connectivity=8,
    )
    min_width = target_banner.shape[1] * 0.40
    min_height = target_banner.shape[0] * 0.20
    for index in range(1, component_count):
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        area = int(stats[index, cv2.CC_STAT_AREA])
        if (
            width < min_width
            or height < min_height
            or width >= target_banner.shape[1] * 0.90
            or height >= target_banner.shape[0] * 0.90
        ):
            is_banner_component = False
        else:
            is_banner_component = area / float(width * height) <= 0.55
        if is_banner_component:
            return True

        center_x = int(stats[index, cv2.CC_STAT_LEFT]) + width / 2
        is_fragmented_health_frame = (
            width >= target_banner.shape[1] * 0.25
            and height <= max(3, target_banner.shape[0] * 0.05)
            and width / float(height) >= 8.0
            and area >= width * 0.35
            and target_banner.shape[1] * 0.25
            <= center_x
            <= target_banner.shape[1] * 0.75
        )
        if is_fragmented_health_frame:
            return True
    return False


def check_target_status(frame: np.ndarray) -> TargetStatus:
    target_banner = get_roi_slice(frame, TARGET_FRAME_ROI)
    banner_visible = _has_target_banner(target_banner)

    hp_bar = get_roi_slice(frame, HP_BAR_ROI)
    hsv_bar = cv2.cvtColor(hp_bar, cv2.COLOR_BGR2HSV)
    red_mask = cv2.inRange(
        hsv_bar,
        np.array((0, 150, 100), dtype=np.uint8),
        np.array((7, 255, 255), dtype=np.uint8),
    ) | cv2.inRange(
        hsv_bar,
        np.array((175, 150, 100), dtype=np.uint8),
        np.array((179, 255, 255), dtype=np.uint8),
    )
    red_pixels = _count_reliable_red_pixels(red_mask)
    return TargetStatus(banner_visible=banner_visible, red_pixels=red_pixels)


def is_game_menu_open(frame: np.ndarray) -> bool:
    menu_region = get_roi_slice(frame, MENU_PANEL_ROI)
    hsv_menu = cv2.cvtColor(menu_region, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(
        hsv_menu,
        np.array((90, MENU_BLUE_MIN_SATURATION, 20), dtype=np.uint8),
        np.array((135, 255, 220), dtype=np.uint8),
    )
    blue_ratio = float(np.count_nonzero(blue_mask)) / blue_mask.size
    return blue_ratio >= MENU_BLUE_PIXEL_RATIO


def get_target_bar_preview_rect(
    frame_shape: tuple[int, ...],
) -> tuple[tuple[int, int], tuple[int, int]]:
    frame_height, frame_width = frame_shape[:2]
    x1, y1, x2, y2 = HP_BAR_ROI
    return (
        (int(frame_width * x1), int(frame_height * y1)),
        (int(frame_width * x2), int(frame_height * y2)),
    )


def get_banner_preview_rect(
    frame_shape: tuple[int, ...],
) -> tuple[tuple[int, int], tuple[int, int]]:
    frame_height, frame_width = frame_shape[:2]
    x1, y1, x2, y2 = TARGET_FRAME_ROI
    return (
        (int(frame_width * x1), int(frame_height * y1)),
        (int(frame_width * x2), int(frame_height * y2)),
    )
