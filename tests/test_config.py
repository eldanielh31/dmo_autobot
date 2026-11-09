import unittest
from unittest.mock import patch

import config


class ConfigValidationTests(unittest.TestCase):
    def test_default_configuration_is_valid(self) -> None:
        config.validate_config()

    def test_rejects_invalid_roi(self) -> None:
        with patch.object(config, "HP_BAR_ROI", (0.8, 0.2, 0.4, 0.3)):
            with self.assertRaisesRegex(ValueError, "HP_BAR_ROI"):
                config.validate_config()

    def test_rejects_non_finite_roi_coordinates(self) -> None:
        with patch.object(config, "TARGET_FRAME_ROI", (0.1, 0.1, float("inf"), 0.9)):
            with self.assertRaisesRegex(ValueError, "TARGET_FRAME_ROI"):
                config.validate_config()

    def test_rejects_non_numeric_menu_color_ratio(self) -> None:
        with patch.object(config, "MENU_BLUE_PIXEL_RATIO", "invalid"):
            with self.assertRaisesRegex(
                ValueError,
                "MENU_BLUE_PIXEL_RATIO",
            ):
                config.validate_config()

    def test_rejects_invalid_timing_and_pixel_settings(self) -> None:
        with (
            patch.object(config, "ATTACK_KEY_INTERVAL", 0),
            patch.object(config, "MIN_HP_RED_PIXELS", -1),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "(?s)ATTACK_KEY_INTERVAL.*MIN_HP_RED_PIXELS",
            ):
                config.validate_config()

    def test_rejects_zero_minimum_hp_pixels(self) -> None:
        with patch.object(config, "MIN_HP_RED_PIXELS", 0):
            with self.assertRaisesRegex(ValueError, "MIN_HP_RED_PIXELS"):
                config.validate_config()

    def test_rejects_invalid_target_name_roi(self) -> None:
        with patch.object(config, "TARGET_NAME_ROI", (0.8, 0.2, 0.4, 0.3)):
            with self.assertRaisesRegex(ValueError, "TARGET_NAME_ROI"):
                config.validate_config()

    def test_rejects_invalid_target_name_ocr_scale(self) -> None:
        with patch.object(config, "TARGET_NAME_OCR_SCALE", 0):
            with self.assertRaisesRegex(ValueError, "TARGET_NAME_OCR_SCALE"):
                config.validate_config()

    def test_requires_antimacro_alarm_to_release_before_unlocking(self) -> None:
        with (
            patch.object(config, "ANTIMACRO_ALARM_RELEASE_DELAY", 3.0),
            patch.object(config, "ANTIMACRO_CLEAR_DELAY", 3.0),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "ANTIMACRO_ALARM_RELEASE_DELAY",
            ):
                config.validate_config()


if __name__ == "__main__":
    unittest.main()
