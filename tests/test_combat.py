import unittest

from combat import CombatController, CombatState
from config import (
    CAMERA_SEARCH_TURN_DURATION,
    KEY_A,
    KEY_D,
    KEY_S,
    KEY_W,
    TAB_COOLDOWN,
    TARGET_NAME_CONFIRMATION_TIMEOUT,
    TARGET_SELECTION_SETTLE_DELAY,
    WALK_SEARCH_DURATION,
    WALK_SEARCH_STEP_DURATION,
)
from target_detection import TargetStatus


class CombatControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = CombatController()

    def test_searches_then_rotates_when_two_tabs_find_no_live_target(self) -> None:
        first = self.controller.update(TargetStatus(False, 0), 10.0)
        second = self.controller.update(TargetStatus(False, 0), 10.0 + TAB_COOLDOWN)

        self.assertTrue(first.press_tab)
        self.assertFalse(first.start_rotation)
        self.assertTrue(second.press_tab)
        self.assertTrue(second.start_rotation)
        self.assertTrue(second.drag_camera)
        self.assertEqual(self.controller.state, CombatState.ROTATING)

    def test_walks_a_wider_loop_after_one_full_camera_turn(self) -> None:
        self.controller.update(TargetStatus(False, 0), 10.0)
        self.controller.update(
            TargetStatus(False, 0),
            10.0 + TAB_COOLDOWN,
        )

        walk_started_at = 10.0 + TAB_COOLDOWN + CAMERA_SEARCH_TURN_DURATION
        start_walking = self.controller.update(
            TargetStatus(False, 0),
            walk_started_at,
        )

        self.assertFalse(start_walking.stop_rotation)
        self.assertTrue(start_walking.drag_camera)
        self.assertEqual(start_walking.movement_keys, (KEY_W, KEY_D))
        self.assertEqual(self.controller.state, CombatState.WALKING)
        self.assertEqual(WALK_SEARCH_DURATION, 16.0)
        self.assertEqual(WALK_SEARCH_STEP_DURATION, 2.0)

        second_direction = self.controller.update(
            TargetStatus(False, 0),
            walk_started_at + WALK_SEARCH_STEP_DURATION,
        )
        self.assertEqual(second_direction.movement_keys, (KEY_S, KEY_D))
        self.assertTrue(second_direction.drag_camera)

        third_direction = self.controller.update(
            TargetStatus(False, 0),
            walk_started_at + 2 * WALK_SEARCH_STEP_DURATION,
        )
        self.assertEqual(third_direction.movement_keys, (KEY_S, KEY_A))

        fourth_direction = self.controller.update(
            TargetStatus(False, 0),
            walk_started_at + 3 * WALK_SEARCH_STEP_DURATION,
        )
        self.assertEqual(fourth_direction.movement_keys, (KEY_W, KEY_A))

        resume_rotation = self.controller.update(
            TargetStatus(False, 0),
            walk_started_at + WALK_SEARCH_DURATION,
        )
        self.assertFalse(resume_rotation.start_rotation)
        self.assertTrue(resume_rotation.drag_camera)
        self.assertEqual(resume_rotation.movement_keys, ())
        self.assertEqual(self.controller.state, CombatState.ROTATING)

    def test_waits_for_visible_banner_life_check_before_tabbing_again(self) -> None:
        first = self.controller.update(TargetStatus(True, 0), 10.0)
        waiting = self.controller.update(
            TargetStatus(True, 0),
            10.0 + TARGET_SELECTION_SETTLE_DELAY / 2,
        )
        next_target = self.controller.update(
            TargetStatus(True, 0),
            10.0 + TARGET_SELECTION_SETTLE_DELAY,
        )

        self.assertFalse(first.press_tab)
        self.assertFalse(waiting.press_tab)
        self.assertTrue(next_target.press_tab)

    def test_keeps_tabbing_at_cooldown_when_banner_is_absent(self) -> None:
        waiting_on_banner = self.controller.update(TargetStatus(True, 0), 10.0)
        first_tab_without_banner = self.controller.update(
            TargetStatus(False, 0),
            10.01,
        )
        second_tab_without_banner = self.controller.update(
            TargetStatus(False, 0),
            10.01 + TAB_COOLDOWN,
        )

        self.assertFalse(waiting_on_banner.press_tab)
        self.assertTrue(first_tab_without_banner.press_tab)
        self.assertTrue(second_tab_without_banner.press_tab)

    def test_waits_longer_for_current_name_ocr_before_tabbing(self) -> None:
        target = TargetStatus(
            True,
            150,
            name_matches=None,
            require_name_match=True,
        )
        waiting = self.controller.update(target, 10.0)
        still_waiting = self.controller.update(
            target,
            10.0 + TARGET_NAME_CONFIRMATION_TIMEOUT / 2,
        )
        timed_out = self.controller.update(
            target,
            10.0 + TARGET_NAME_CONFIRMATION_TIMEOUT,
        )

        self.assertFalse(waiting.attack)
        self.assertFalse(waiting.press_tab)
        self.assertFalse(still_waiting.press_tab)
        self.assertTrue(timed_out.press_tab)

    def test_attacks_only_after_the_required_name_matches(self) -> None:
        pending_name = TargetStatus(
            True,
            150,
            name_matches=None,
            require_name_match=True,
        )
        waiting = self.controller.update(pending_name, 10.0)
        confirmed = self.controller.update(
            TargetStatus(True, 150, name_matches=True, require_name_match=True),
            10.1,
        )

        self.assertFalse(waiting.attack)
        self.assertFalse(waiting.press_tab)
        self.assertTrue(confirmed.attack)
        self.assertEqual(self.controller.state, CombatState.ATTACKING)

    def test_stops_walking_immediately_when_a_live_target_is_found(self) -> None:
        self.controller.state = CombatState.WALKING
        self.controller.walking_started_at = 10.0

        actions = self.controller.update(TargetStatus(True, 300), 10.1)

        self.assertTrue(actions.attack)
        self.assertTrue(actions.stop_rotation)
        self.assertEqual(actions.movement_keys, ())
        self.assertEqual(self.controller.state, CombatState.ATTACKING)

    def test_search_starts_attack_when_enough_red_pixels_are_detected(self) -> None:
        actions = self.controller.update(TargetStatus(True, 120), 10.0)

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

        actions = self.controller.update(TargetStatus(True, 120), 10.0)

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

        no_duplicate_tab = self.controller.update(TargetStatus(False, 0), 10.22)
        next_search = self.controller.update(TargetStatus(False, 0), 11.22)

        self.assertFalse(no_duplicate_tab.press_tab)
        self.assertTrue(next_search.press_tab)
        self.assertTrue(next_search.start_rotation)
        self.assertEqual(self.controller.state, CombatState.ROTATING)

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
        second_search = self.controller.update(
            TargetStatus(False, 70),
            10.0 + TAB_COOLDOWN,
        )

        self.assertTrue(lost_target.press_tab)
        self.assertFalse(first_search.press_tab)
        self.assertTrue(second_search.press_tab)
        self.assertTrue(second_search.start_rotation)
        self.assertTrue(second_search.drag_camera)
        self.assertEqual(self.controller.state, CombatState.ROTATING)

    def test_banner_without_red_life_is_not_valid_for_attack(self) -> None:
        first = self.controller.update(TargetStatus(True, 0), 10.0)
        actions = self.controller.update(
            TargetStatus(True, 0),
            10.0 + TARGET_SELECTION_SETTLE_DELAY,
        )

        self.assertFalse(first.attack)
        self.assertFalse(first.press_tab)
        self.assertTrue(actions.press_tab)
        self.assertFalse(actions.attack)
        self.assertEqual(self.controller.state, CombatState.SEARCHING)

    def test_non_matching_name_stops_attack_without_finisher(self) -> None:
        self.controller.state = CombatState.ATTACKING

        actions = self.controller.update(
            TargetStatus(True, 0, name_matches=False),
            10.0,
        )

        self.assertTrue(actions.press_tab)
        self.assertFalse(actions.attack)
        self.assertEqual(self.controller.state, CombatState.SEARCHING)


if __name__ == "__main__":
    unittest.main()
