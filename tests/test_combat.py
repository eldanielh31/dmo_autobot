import unittest

from combat import CombatController, CombatState
from target_detection import TargetStatus


class CombatControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = CombatController()

    def test_searches_then_rotates_when_two_tabs_find_no_live_target(self) -> None:
        first = self.controller.update(TargetStatus(False, 0), 10.0)
        second = self.controller.update(TargetStatus(False, 0), 10.25)

        self.assertTrue(first.press_tab)
        self.assertFalse(first.start_rotation)
        self.assertTrue(second.press_tab)
        self.assertTrue(second.start_rotation)
        self.assertTrue(second.drag_camera)
        self.assertEqual(self.controller.state, CombatState.ROTATING)

    def test_search_starts_attack_when_a_small_amount_of_red_is_detected(self) -> None:
        actions = self.controller.update(TargetStatus(True, 1), 10.0)

        self.assertTrue(actions.attack)
        self.assertFalse(actions.press_tab)
        self.assertFalse(actions.start_rotation)
        self.assertEqual(self.controller.state, CombatState.ATTACKING)

    def test_stops_rotation_and_attacks_as_soon_as_life_is_detected(self) -> None:
        self.controller.state = CombatState.ROTATING

        actions = self.controller.update(TargetStatus(True, 120), 10.0)

        self.assertTrue(actions.stop_rotation)
        self.assertTrue(actions.attack)
        self.assertFalse(actions.press_tab)
        self.assertEqual(self.controller.state, CombatState.ATTACKING)

    def test_keeps_attacking_until_red_bar_is_empty(self) -> None:
        self.controller.state = CombatState.ATTACKING
        self.controller.last_attack_time = 9.0

        actions = self.controller.update(TargetStatus(True, 1), 10.0)

        self.assertTrue(actions.attack)
        self.assertFalse(actions.press_tab)
        self.assertEqual(self.controller.state, CombatState.ATTACKING)

    def test_empty_bar_gets_finisher_then_returns_to_tab_search(self) -> None:
        self.controller.state = CombatState.ATTACKING

        finisher = self.controller.update(TargetStatus(True, 0), 10.0)
        waiting = self.controller.update(TargetStatus(True, 0), 10.1)
        search = self.controller.update(TargetStatus(True, 0), 10.21)

        self.assertTrue(finisher.attack)
        self.assertFalse(finisher.press_tab)
        self.assertFalse(waiting.attack)
        self.assertFalse(waiting.press_tab)
        self.assertTrue(search.press_tab)
        self.assertEqual(self.controller.state, CombatState.SEARCHING)

    def test_missing_banner_returns_to_search_immediately(self) -> None:
        self.controller.state = CombatState.ATTACKING

        actions = self.controller.update(TargetStatus(False, 500), 10.0)

        self.assertTrue(actions.press_tab)
        self.assertFalse(actions.attack)
        self.assertEqual(self.controller.state, CombatState.SEARCHING)

    def test_missing_banner_keeps_tabbing_then_rotates_until_target_is_found(self) -> None:
        self.controller.state = CombatState.ATTACKING

        lost_target = self.controller.update(TargetStatus(False, 70), 10.0)
        first_search = self.controller.update(TargetStatus(False, 70), 10.01)
        second_search = self.controller.update(TargetStatus(False, 70), 10.26)

        self.assertTrue(lost_target.press_tab)
        self.assertTrue(first_search.press_tab)
        self.assertFalse(first_search.start_rotation)
        self.assertTrue(second_search.press_tab)
        self.assertTrue(second_search.start_rotation)
        self.assertTrue(second_search.drag_camera)
        self.assertEqual(self.controller.state, CombatState.ROTATING)

    def test_empty_bar_while_searching_does_not_start_attack(self) -> None:
        actions = self.controller.update(TargetStatus(True, 0), 10.0)

        self.assertTrue(actions.press_tab)
        self.assertFalse(actions.attack)
        self.assertEqual(self.controller.state, CombatState.SEARCHING)


if __name__ == "__main__":
    unittest.main()
