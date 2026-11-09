import unittest
from unittest.mock import patch

from config import KEY_D, KEY_W, VK_CONTROL, VK_MENU, VK_P, VK_SHIFT
from game_input import is_pause_hotkey_down, sync_keys


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


class SyncKeysTests(unittest.TestCase):
    def test_presses_new_movement_keys_and_releases_keys_no_longer_desired(self) -> None:
        with (
            patch("game_input.key_up", return_value=True) as key_up,
            patch("game_input.key_down", return_value=True) as key_down,
        ):
            held_keys = sync_keys({KEY_W}, (KEY_D,))

        key_up.assert_called_once_with(KEY_W)
        key_down.assert_called_once_with(KEY_D)
        self.assertEqual(held_keys, {KEY_D})


if __name__ == "__main__":
    unittest.main()
