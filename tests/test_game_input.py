import unittest
from unittest.mock import patch

from config import VK_CONTROL, VK_MENU, VK_P, VK_SHIFT
from game_input import is_pause_hotkey_down


class PauseHotkeyTests(unittest.TestCase):
    def test_pause_hotkey_accepts_ctrl_alt_p(self) -> None:
        pressed_keys = {VK_CONTROL, VK_MENU, VK_P}
        with patch("game_input.is_key_down", side_effect=pressed_keys.__contains__):
            self.assertTrue(is_pause_hotkey_down())

    def test_pause_hotkey_accepts_ctrl_shift_p(self) -> None:
        pressed_keys = {VK_CONTROL, VK_SHIFT, VK_P}
        with patch("game_input.is_key_down", side_effect=pressed_keys.__contains__):
            self.assertTrue(is_pause_hotkey_down())

    def test_pause_hotkey_rejects_ctrl_p_without_modifier(self) -> None:
        pressed_keys = {VK_CONTROL, VK_P}
        with patch("game_input.is_key_down", side_effect=pressed_keys.__contains__):
            self.assertFalse(is_pause_hotkey_down())


if __name__ == "__main__":
    unittest.main()
