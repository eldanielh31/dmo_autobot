import unittest

import cv2
import numpy as np

from config import HP_BAR_ROI, TARGET_FRAME_ROI
from target_detection import (
    MenuOpenConfirmation,
    check_target_status,
    get_roi_slice,
)


class TargetDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
        self.target_banner = get_roi_slice(self.frame, TARGET_FRAME_ROI)
        self.target_banner[:] = (30, 35, 40)
        banner_height, banner_width = self.target_banner.shape[:2]
        cv2.rectangle(
            self.target_banner,
            (int(banner_width * 0.20), 0),
            (int(banner_width * 0.78), int(banner_height * 0.75)),
            (255, 180, 0),
            2,
        )
        self.hp_bar = get_roi_slice(self.frame, HP_BAR_ROI)

    def test_one_red_pixel_is_still_a_live_target(self) -> None:
        self.hp_bar[0, 0] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)
        self.assertEqual(status.red_pixels, 1)
        self.assertTrue(status.has_life)
        self.assertFalse(status.bar_empty)

    def test_inverted_roi_raises_a_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "ROI inválido"):
            get_roi_slice(self.frame, (0.50, 0.015, 0.48, 0.11))

    def test_compact_red_bar_is_detected_as_live(self) -> None:
        self.hp_bar[3:9, 15:65] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertTrue(status.has_life)
        self.assertEqual(status.red_pixels, 300)

    def test_user_sampled_dark_banner_blue_is_detected(self) -> None:
        banner_height, banner_width = self.target_banner.shape[:2]
        cv2.rectangle(
            self.target_banner,
            (int(banner_width * 0.20), 0),
            (int(banner_width * 0.78), int(banner_height * 0.75)),
            (68, 42, 12),
            -1,
        )

        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)

    def test_red_screen_tint_does_not_hide_target_banner(self) -> None:
        tint = np.zeros_like(self.target_banner)
        tint[:] = (0, 0, 120)
        self.target_banner[:] = cv2.addWeighted(
            self.target_banner,
            0.10,
            tint,
            0.90,
            0,
        )
        self.hp_bar[3:9, 15:65] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)
        self.assertTrue(status.has_life)

    def test_user_sampled_red_life_colors_are_detected(self) -> None:
        self.hp_bar[4, 10:13] = [
            (24, 34, 129),
            (41, 54, 197),
            (46, 60, 218),
        ]

        status = check_target_status(self.frame)

        self.assertTrue(status.has_life)
        self.assertEqual(status.red_pixels, 3)

    def test_empty_red_bar_is_distinct_from_missing_banner(self) -> None:
        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)
        self.assertEqual(status.red_pixels, 0)
        self.assertFalse(status.has_life)
        self.assertTrue(status.bar_empty)

    def test_sparse_red_noise_is_not_treated_as_a_live_bar(self) -> None:
        noise_positions = [
            (0, 0), (0, 1), (0, 2), (0, 3),
            (1, 2), (2, 4), (3, 6), (4, 9),
            (5, 12), (6, 16), (7, 20), (8, 24),
        ]
        for y, x in noise_positions:
            self.hp_bar[y, x] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)
        self.assertEqual(status.red_pixels, 0)
        self.assertFalse(status.has_life)
        self.assertTrue(status.bar_empty)

    def test_bright_background_and_red_text_do_not_fake_target_banner(self) -> None:
        self.target_banner[:] = (70, 80, 90)
        banner_height, banner_width = self.target_banner.shape[:2]
        cv2.rectangle(
            self.target_banner,
            (0, 0),
            (int(banner_width * 0.30), int(banner_height * 0.30)),
            (255, 180, 0),
            -1,
        )
        cv2.putText(
            self.target_banner,
            "Seleccionar objetivo",
            (2, banner_height - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.3,
            (0, 0, 255),
            1,
        )
        self.hp_bar[4:11, :10] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertFalse(status.banner_visible)
        self.assertEqual(status.red_pixels, 70)
        self.assertFalse(status.has_life)

    def test_menu_requires_three_consecutive_positive_detections(self) -> None:
        confirmation = MenuOpenConfirmation()

        self.assertFalse(confirmation.update(True))
        self.assertFalse(confirmation.update(True))
        self.assertTrue(confirmation.update(True))
        self.assertFalse(confirmation.update(False))


if __name__ == "__main__":
    unittest.main()
