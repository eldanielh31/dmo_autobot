from dataclasses import dataclass
from enum import Enum

from config import (
    ATTACK_KEY_INTERVAL,
    CAMERA_SEARCH_TURN_DURATION,
    DRAG_STEP_INTERVAL,
    KEY_A,
    KEY_D,
    KEY_S,
    KEY_W,
    MIN_HP_RED_PIXELS,
    TAB_COOLDOWN,
    TARGET_NAME_CONFIRMATION_TIMEOUT,
    TARGET_SELECTION_SETTLE_DELAY,
    WALK_SEARCH_DURATION,
    WALK_SEARCH_STEP_DURATION,
    ZERO_HP_FINISHER_DELAY,
)
from target_detection import TargetStatus


class CombatState(str, Enum):
    SEARCHING = "BUSCANDO (TAB)"
    ROTATING = "ROTANDO CÁMARA (CLIC DER.)"
    WALKING = "BUSCANDO CON WASD"
    ATTACKING = "ATACANDO (VIDA > 0%)"


@dataclass(frozen=True)
class CombatActions:
    press_tab: bool = False
    attack: bool = False
    start_rotation: bool = False
    stop_rotation: bool = False
    drag_camera: bool = False
    movement_keys: tuple[int, ...] = ()


class CombatController:
    def __init__(self) -> None:
        self.state = CombatState.SEARCHING
        self.tab_attempts = 0
        self.zero_hp_since: float | None = None
        self.last_attack_time = 0.0
        self.last_tab_time = 0.0
        self.last_drag_time = 0.0
        self.rotation_started_at = 0.0
        self.walking_started_at = 0.0
        self.target_banner_seen_at: float | None = None

    def reset_search(self) -> None:
        self.state = CombatState.SEARCHING
        self.tab_attempts = 0
        self.zero_hp_since = None
        self.rotation_started_at = 0.0
        self.walking_started_at = 0.0
        self.target_banner_seen_at = None

    def update(self, target: TargetStatus, now: float) -> CombatActions:
        should_validate_target = self.state is not CombatState.ATTACKING or (
            target.require_name_match
            and target.banner_visible
            and target.name_matches is None
        )
        if should_validate_target:
            if self._wait_for_target_validation(target, now):
                return CombatActions()
            if (
                target.require_name_match
                and target.banner_visible
                and target.name_matches is None
            ):
                target = TargetStatus(
                    banner_visible=target.banner_visible,
                    red_pixels=target.red_pixels,
                    name_matches=False,
                    require_name_match=True,
                )
        if self.state is CombatState.SEARCHING:
            return self._search(target, now)
        if self.state is CombatState.ROTATING:
            return self._rotate(target, now)
        if self.state is CombatState.WALKING:
            return self._walk(target, now)
        return self._attack(target, now)

    def _wait_for_target_validation(self, target: TargetStatus, now: float) -> bool:
        if not target.banner_visible or target.has_life or target.name_matches is False:
            self.target_banner_seen_at = None
            return False
        if self.target_banner_seen_at is None:
            self.target_banner_seen_at = now

        timeout = (
            TARGET_NAME_CONFIRMATION_TIMEOUT
            if target.require_name_match and target.name_matches is None
            else TARGET_SELECTION_SETTLE_DELAY
        )
        return now - self.target_banner_seen_at < timeout

    def _search(self, target: TargetStatus, now: float) -> CombatActions:
        if target.has_life:
            self.state = CombatState.ATTACKING
            self.target_banner_seen_at = None
            self.tab_attempts = 0
            self.zero_hp_since = None
            self.last_attack_time = now
            return CombatActions(attack=True)

        press_tab = now - self.last_tab_time >= TAB_COOLDOWN
        if press_tab:
            self.last_tab_time = now
            self.target_banner_seen_at = None
            self.tab_attempts += 1
        if self.tab_attempts >= 2:
            self.state = CombatState.ROTATING
            self.last_drag_time = now
            self.rotation_started_at = now
            return CombatActions(
                press_tab=press_tab,
                start_rotation=True,
                drag_camera=True,
            )
        return CombatActions(press_tab=press_tab)

    def _rotate(self, target: TargetStatus, now: float) -> CombatActions:
        if target.has_life:
            self.state = CombatState.ATTACKING
            self.target_banner_seen_at = None
            self.zero_hp_since = None
            self.last_attack_time = now
            return CombatActions(stop_rotation=True, attack=True)

        press_tab = now - self.last_tab_time >= TAB_COOLDOWN
        if press_tab:
            self.last_tab_time = now
            self.target_banner_seen_at = None
        if now - self.rotation_started_at >= CAMERA_SEARCH_TURN_DURATION:
            self.state = CombatState.WALKING
            self.walking_started_at = now
            self.last_drag_time = now
            return CombatActions(
                press_tab=press_tab,
                drag_camera=True,
                movement_keys=(KEY_W, KEY_D),
            )
        drag_camera = now - self.last_drag_time >= DRAG_STEP_INTERVAL
        if drag_camera:
            self.last_drag_time = now
        return CombatActions(press_tab=press_tab, drag_camera=drag_camera)

    def _walk(self, target: TargetStatus, now: float) -> CombatActions:
        if target.has_life:
            self.state = CombatState.ATTACKING
            self.target_banner_seen_at = None
            self.zero_hp_since = None
            self.last_attack_time = now
            return CombatActions(stop_rotation=True, attack=True)

        press_tab = now - self.last_tab_time >= TAB_COOLDOWN
        if press_tab:
            self.last_tab_time = now
            self.target_banner_seen_at = None
        if now - self.walking_started_at >= WALK_SEARCH_DURATION:
            self.state = CombatState.ROTATING
            self.rotation_started_at = now
            self.last_drag_time = now
            return CombatActions(
                press_tab=press_tab,
                drag_camera=True,
            )

        movement_cycle = (
            (KEY_W, KEY_D),
            (KEY_S, KEY_D),
            (KEY_S, KEY_A),
            (KEY_W, KEY_A),
        )
        step = int((now - self.walking_started_at) / WALK_SEARCH_STEP_DURATION)
        drag_camera = now - self.last_drag_time >= DRAG_STEP_INTERVAL
        if drag_camera:
            self.last_drag_time = now
        return CombatActions(
            press_tab=press_tab,
            drag_camera=drag_camera,
            movement_keys=movement_cycle[step % len(movement_cycle)],
        )

    def _attack(self, target: TargetStatus, now: float) -> CombatActions:
        if (
            not target.banner_visible
            or target.name_matches is False
        ):
            self.reset_search()
            self.last_tab_time = now
            self.tab_attempts = 1
            return CombatActions(press_tab=True)

        if target.red_pixels < MIN_HP_RED_PIXELS:
            if self.zero_hp_since is None:
                self.zero_hp_since = now
                self.last_attack_time = now
                return CombatActions(attack=True)
            if now - self.zero_hp_since >= ZERO_HP_FINISHER_DELAY:
                self.reset_search()
                self.last_tab_time = now
                self.tab_attempts = 1
                return CombatActions(press_tab=True)
            return CombatActions()

        self.zero_hp_since = None
        if now - self.last_attack_time >= ATTACK_KEY_INTERVAL:
            self.last_attack_time = now
            return CombatActions(attack=True)
        return CombatActions()
