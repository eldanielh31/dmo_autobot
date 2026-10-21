from dataclasses import dataclass

import cv2
import numpy as np

from config import (
    HP_BAR_ROI,
    MENU_BLUE_MIN_SATURATION,
    MENU_BLUE_PIXEL_RATIO,
    MENU_PANEL_ROI,
    MIN_HP_RED_PIXELS,
    TARGET_FRAME_MIN_BRIGHTNESS,
    TARGET_FRAME_ROI,
)

RelativeROI = tuple[float, float, float, float]


@dataclass(frozen=True)
class TargetStatus:
    banner_visible: bool
    red_pixels: int

    @property
    def has_life(self) -> bool:
        return self.banner_visible and self.red_pixels >= MIN_HP_RED_PIXELS

    @property
    def bar_empty(self) -> bool:
        return self.banner_visible and self.red_pixels < MIN_HP_RED_PIXELS


class MenuOpenConfirmation:
    def __init__(self, required_frames: int = 3) -> None:
        self._required_frames = required_frames
        self._detected_frames = 0

    def update(self, detected: bool) -> bool:
        self._detected_frames = self._detected_frames + 1 if detected else 0
        return self._detected_frames >= self._required_frames


def get_roi_slice(frame: np.ndarray, roi: RelativeROI) -> np.ndarray:
    frame_height, frame_width = frame.shape[:2]
    x1, y1, x2, y2 = roi
    return frame[
        int(frame_height * y1):int(frame_height * y2),
        int(frame_width * x1):int(frame_width * x2),
    ]


def _count_reliable_red_pixels(red_mask: np.ndarray) -> int:
    red_pixels = int(np.count_nonzero(red_mask))
    if red_pixels == 0:
        return 0

    ys, xs = np.where(red_mask)
    width = int(xs.max() - xs.min() + 1)
    height = int(ys.max() - ys.min() + 1)
    if width <= 0 or height <= 0:
        return 0

    fill_ratio = red_pixels / float(width * height)
    if fill_ratio < 0.20:
        return 0
    return red_pixels


def check_target_status(frame: np.ndarray) -> TargetStatus:
    target_banner = get_roi_slice(frame, TARGET_FRAME_ROI)
    gray_banner = cv2.cvtColor(target_banner, cv2.COLOR_BGR2GRAY)
    banner_visible = float(np.mean(gray_banner)) >= TARGET_FRAME_MIN_BRIGHTNESS

    hp_bar = get_roi_slice(frame, HP_BAR_ROI)
    red = hp_bar[:, :, 2].astype(np.int16)
    green = hp_bar[:, :, 1].astype(np.int16)
    blue = hp_bar[:, :, 0].astype(np.int16)
    red_mask = (red > 105) & (red > green + 25) & (red > blue + 25)
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
