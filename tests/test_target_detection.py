import unittest

import cv2
import numpy as np

from config import HP_BAR_ROI, TARGET_FRAME_ROI
from target_detection import (
    MenuOpenConfirmation,
    check_target_status,
    get_roi_slice,
    get_target_name_region,
    get_target_name_signature,
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

    def test_one_red_pixel_is_not_enough_to_confirm_a_live_target(self) -> None:
        self.hp_bar[0, 0] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)
        self.assertEqual(status.red_pixels, 0)
        self.assertFalse(status.has_life)
        self.assertTrue(status.bar_empty)

    def test_inverted_roi_raises_a_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "ROI inválido"):
            get_roi_slice(self.frame, (0.50, 0.015, 0.48, 0.11))

    def test_malformed_roi_raises_a_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "ROI inválido"):
            get_roi_slice(self.frame, (0.1, 0.2, 0.3))

    def test_roi_that_rounds_to_an_empty_slice_raises_a_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "recorte vacío"):
            get_roi_slice(np.zeros((10, 10, 3), dtype=np.uint8), HP_BAR_ROI)

    def test_empty_frame_raises_a_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "frame vacío"):
            get_roi_slice(np.zeros((0, 0, 3), dtype=np.uint8), HP_BAR_ROI)

    def test_compact_red_bar_is_detected_as_live(self) -> None:
        self.hp_bar[3:9, 15:65] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertTrue(status.has_life)
        self.assertEqual(status.red_pixels, 300)

    def test_fifteen_percent_red_fill_is_detected_despite_bar_outline(self) -> None:
        frame = np.zeros((1009, 1920, 3), dtype=np.uint8)
        target_banner = get_roi_slice(frame, TARGET_FRAME_ROI)
        banner_height, banner_width = target_banner.shape[:2]
        cv2.rectangle(
            target_banner,
            (int(banner_width * 0.20), 0),
            (int(banner_width * 0.78), int(banner_height * 0.75)),
            (255, 180, 0),
            2,
        )
        hp_bar = get_roi_slice(frame, HP_BAR_ROI)
        bar_height, bar_width = hp_bar.shape[:2]
        cv2.rectangle(hp_bar, (0, 0), (bar_width - 1, bar_height - 1), (0, 0, 200), 1)
        hp_bar[1:-1, 1:25] = (0, 0, 200)

        status = check_target_status(frame)

        self.assertTrue(status.has_life)
        self.assertGreaterEqual(status.red_pixels, 100)

    def test_full_health_bar_at_screenshot_dimensions_is_detected(self) -> None:
        frame = np.zeros((768, 1366, 3), dtype=np.uint8)
        target_banner = get_roi_slice(frame, TARGET_FRAME_ROI)
        banner_height, banner_width = target_banner.shape[:2]
        cv2.rectangle(
            target_banner,
            (int(banner_width * 0.20), 0),
            (int(banner_width * 0.78), int(banner_height * 0.75)),
            (255, 180, 0),
            2,
        )
        hp_bar = get_roi_slice(frame, HP_BAR_ROI)
        hp_bar[3:9, 7:49] = (33, 31, 114)
        hp_bar[3:9, 69:111] = (33, 31, 114)

        status = check_target_status(frame)

        self.assertEqual(status.red_pixels, 504)
        self.assertTrue(status.has_life)

    def test_two_percent_fill_is_detected_inside_red_bar_outline(self) -> None:
        bar_height, bar_width = self.hp_bar.shape[:2]
        cv2.rectangle(
            self.hp_bar,
            (0, 0),
            (bar_width - 1, bar_height - 1),
            (0, 0, 200),
            1,
        )
        self.hp_bar[2:7, 11:13] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertEqual(status.red_pixels, 10)
        self.assertTrue(status.has_life)

    def test_fragmented_two_percent_fill_is_detected(self) -> None:
        self.hp_bar[2:5, 11:13] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertEqual(status.red_pixels, 6)
        self.assertTrue(status.has_life)

    def test_one_percent_edge_fill_is_detected(self) -> None:
        frame = np.zeros((1009, 1920, 3), dtype=np.uint8)
        target_banner = get_roi_slice(frame, TARGET_FRAME_ROI)
        banner_height, banner_width = target_banner.shape[:2]
        cv2.rectangle(
            target_banner,
            (int(banner_width * 0.20), 0),
            (int(banner_width * 0.78), int(banner_height * 0.75)),
            (255, 180, 0),
            2,
        )
        hp_bar = get_roi_slice(frame, HP_BAR_ROI)
        hp_bar[2:11, 1:4] = (0, 0, 200)
        hp_bar[2, 4:6] = (0, 0, 200)

        status = check_target_status(frame)

        self.assertEqual(status.red_pixels, 29)
        self.assertTrue(status.has_life)

    def test_short_live_fill_with_bar_like_aspect_ratio_is_detected(self) -> None:
        frame = np.zeros((1009, 1920, 3), dtype=np.uint8)
        target_banner = get_roi_slice(frame, TARGET_FRAME_ROI)
        banner_height, banner_width = target_banner.shape[:2]
        cv2.rectangle(
            target_banner,
            (int(banner_width * 0.20), 0),
            (int(banner_width * 0.78), int(banner_height * 0.75)),
            (255, 180, 0),
            2,
        )
        hp_bar = get_roi_slice(frame, HP_BAR_ROI)
        hp_bar[2:9, 10:27] = (0, 0, 200)

        status = check_target_status(frame)

        self.assertEqual(status.red_pixels, 119)
        self.assertTrue(status.has_life)

    def test_red_bar_outline_without_fill_is_not_detected_as_life(self) -> None:
        bar_height, bar_width = self.hp_bar.shape[:2]
        cv2.rectangle(
            self.hp_bar,
            (0, 0),
            (bar_width - 1, bar_height - 1),
            (0, 0, 200),
            1,
        )

        status = check_target_status(self.frame)

        self.assertEqual(status.red_pixels, 0)
        self.assertFalse(status.has_life)

    def test_bright_blue_banner_outline_is_detected(self) -> None:
        banner_height, banner_width = self.target_banner.shape[:2]
        self.target_banner[:] = (68, 42, 12)
        cv2.rectangle(
            self.target_banner,
            (int(banner_width * 0.20), 0),
            (int(banner_width * 0.78), int(banner_height * 0.75)),
            (255, 180, 0),
            2,
        )

        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)

    def test_solid_blue_background_filling_banner_roi_is_not_a_banner(self) -> None:
        self.target_banner[:] = (120, 80, 40)
        self.hp_bar[3:9, 15:65] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertFalse(status.banner_visible)
        self.assertFalse(status.has_life)

    def test_large_bright_blue_background_patch_is_not_a_banner(self) -> None:
        self.target_banner[:] = (70, 80, 90)
        banner_height, banner_width = self.target_banner.shape[:2]
        cv2.rectangle(
            self.target_banner,
            (int(banner_width * 0.08), int(banner_height * 0.10)),
            (int(banner_width * 0.82), int(banner_height * 0.75)),
            (200, 150, 80),
            -1,
        )

        status = check_target_status(self.frame)

        self.assertFalse(status.banner_visible)
        self.assertFalse(status.has_life)

    def test_top_edge_fragmented_target_banner_is_detected(self) -> None:
        self.target_banner[:] = (70, 80, 90)
        banner_height, banner_width = self.target_banner.shape[:2]
        cv2.rectangle(
            self.target_banner,
            (int(banner_width * 0.25), int(banner_height * 0.05)),
            (int(banner_width * 0.71), int(banner_height * 0.25)),
            (255, 180, 0),
            2,
        )

        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)

    def test_wide_thin_blue_health_frame_fragment_confirms_banner(self) -> None:
        self.target_banner[:] = (70, 80, 90)
        banner_height, banner_width = self.target_banner.shape[:2]
        self.target_banner[
            int(banner_height * 0.45),
            int(banner_width * 0.28) : int(banner_width * 0.78),
        ] = (255, 180, 0)

        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)

    def test_red_pixels_cannot_be_mistaken_for_blue_banner(self) -> None:
        self.target_banner[:] = (0, 0, 200)
        self.hp_bar[3:9, 15:65] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertFalse(status.banner_visible)
        self.assertFalse(status.has_life)

    def test_sampled_red_bar_tone_is_detected_as_life(self) -> None:
        self.hp_bar[2:8, 10:60] = (24, 34, 129)

        status = check_target_status(self.frame)

        self.assertTrue(status.has_life)
        self.assertEqual(status.red_pixels, 300)

    def test_name_filter_requires_a_matching_enemy_name(self) -> None:
        self.hp_bar[2:8, 10:60] = (24, 34, 129)

        status = check_target_status(self.frame)
        filtered_status = type(status)(
            banner_visible=status.banner_visible,
            red_pixels=status.red_pixels,
            name_matches=False,
        )

        self.assertTrue(status.has_life)
        self.assertFalse(filtered_status.has_life)
        self.assertFalse(filtered_status.bar_empty)

    def test_target_name_signature_changes_when_name_text_changes(self) -> None:
        name_region = get_target_name_region(self.frame)
        cv2.putText(
            name_region,
            "MetalGreymon",
            (2, name_region.shape[0] - 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (255, 255, 255),
            1,
        )
        metalgreymon_signature = get_target_name_signature(self.frame)

        name_region[:] = (30, 35, 40)
        cv2.putText(
            name_region,
            "Greymon",
            (2, name_region.shape[0] - 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (255, 255, 255),
            1,
        )

        self.assertNotEqual(
            metalgreymon_signature,
            get_target_name_signature(self.frame),
        )

    def test_a_few_sampled_red_pixels_are_not_enough_to_confirm_life(self) -> None:
        self.hp_bar[4, 10:13] = [
            (24, 34, 129),
            (41, 54, 197),
            (46, 60, 218),
        ]

        status = check_target_status(self.frame)

        self.assertFalse(status.has_life)
        self.assertEqual(status.red_pixels, 0)

    def test_69_background_color_pixels_are_not_treated_as_life(self) -> None:
        self.hp_bar[4:7, 10:33] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)
        self.assertEqual(status.red_pixels, 0)
        self.assertFalse(status.has_life)
        self.assertTrue(status.bar_empty)

    def test_orange_background_pixels_are_not_treated_as_red_life(self) -> None:
        self.hp_bar[2:9, 10:96] = (40, 80, 160)

        status = check_target_status(self.frame)

        self.assertEqual(status.red_pixels, 0)
        self.assertFalse(status.has_life)

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
        self.assertEqual(status.red_pixels, 0)
        self.assertFalse(status.has_life)

    def test_menu_requires_three_consecutive_positive_detections(self) -> None:
        confirmation = MenuOpenConfirmation()

        self.assertFalse(confirmation.update(True))
        self.assertFalse(confirmation.update(True))
        self.assertTrue(confirmation.update(True))
        self.assertFalse(confirmation.update(False))


if __name__ == "__main__":
    unittest.main()
