import unittest

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
        get_roi_slice(self.frame, TARGET_FRAME_ROI)[:] = 80
        self.hp_bar = get_roi_slice(self.frame, HP_BAR_ROI)

    def test_one_red_pixel_is_still_a_live_target(self) -> None:
        self.hp_bar[0, 0] = (0, 0, 200)

        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)
        self.assertEqual(status.red_pixels, 1)
        self.assertTrue(status.has_life)
        self.assertFalse(status.bar_empty)

    def test_empty_red_bar_is_distinct_from_missing_banner(self) -> None:
        status = check_target_status(self.frame)

        self.assertTrue(status.banner_visible)
        self.assertEqual(status.red_pixels, 0)
        self.assertFalse(status.has_life)
        self.assertTrue(status.bar_empty)

    def test_menu_requires_three_consecutive_positive_detections(self) -> None:
        confirmation = MenuOpenConfirmation()

        self.assertFalse(confirmation.update(True))
        self.assertFalse(confirmation.update(True))
        self.assertTrue(confirmation.update(True))
        self.assertFalse(confirmation.update(False))


if __name__ == "__main__":
    unittest.main()
