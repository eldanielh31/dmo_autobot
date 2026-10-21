from dataclasses import dataclass
from enum import Enum

from config import (
    ATTACK_KEY_INTERVAL,
    DRAG_STEP_INTERVAL,
    MIN_HP_RED_PIXELS,
    TAB_COOLDOWN,
    ZERO_HP_FINISHER_DELAY,
)
from target_detection import TargetStatus


class CombatState(str, Enum):
    SEARCHING = "BUSCANDO (TAB)"
    ROTATING = "ROTANDO CÁMARA (CLIC DER.)"
    ATTACKING = "ATACANDO (VIDA > 0%)"


@dataclass(frozen=True)
class CombatActions:
    press_tab: bool = False
    attack: bool = False
    start_rotation: bool = False
    stop_rotation: bool = False
    drag_camera: bool = False


class CombatController:
    def __init__(self) -> None:
        self.state = CombatState.SEARCHING
        self.tab_attempts = 0
        self.zero_hp_since: float | None = None
        self.last_attack_time = 0.0
        self.last_tab_time = 0.0
        self.last_drag_time = 0.0

    def reset_search(self) -> None:
        self.state = CombatState.SEARCHING
        self.tab_attempts = 0
        self.zero_hp_since = None

    def update(self, target: TargetStatus, now: float) -> CombatActions:
        if self.state is CombatState.SEARCHING:
            return self._search(target, now)
        if self.state is CombatState.ROTATING:
            return self._rotate(target, now)
        return self._attack(target, now)

    def _search(self, target: TargetStatus, now: float) -> CombatActions:
        if target.has_life:
            self.state = CombatState.ATTACKING
            self.tab_attempts = 0
            self.zero_hp_since = None
            self.last_attack_time = now
            return CombatActions(attack=True)

        press_tab = now - self.last_tab_time >= TAB_COOLDOWN
        if press_tab:
            self.last_tab_time = now
            self.tab_attempts += 1
        if self.tab_attempts >= 2:
            self.state = CombatState.ROTATING
            self.last_drag_time = now
            return CombatActions(
                press_tab=press_tab,
                start_rotation=True,
                drag_camera=True,
            )
        return CombatActions(press_tab=press_tab)

    def _rotate(self, target: TargetStatus, now: float) -> CombatActions:
        if target.has_life:
            self.state = CombatState.ATTACKING
            self.zero_hp_since = None
            self.last_attack_time = now
            return CombatActions(stop_rotation=True, attack=True)

        press_tab = now - self.last_tab_time >= TAB_COOLDOWN
        if press_tab:
            self.last_tab_time = now
        drag_camera = now - self.last_drag_time >= DRAG_STEP_INTERVAL
        if drag_camera:
            self.last_drag_time = now
        return CombatActions(press_tab=press_tab, drag_camera=drag_camera)

    def _attack(self, target: TargetStatus, now: float) -> CombatActions:
        if not target.banner_visible:
            self.reset_search()
            self.last_tab_time = now - TAB_COOLDOWN
            return CombatActions(press_tab=True)

        if target.red_pixels < MIN_HP_RED_PIXELS:
            if self.zero_hp_since is None:
                self.zero_hp_since = now
                self.last_attack_time = now
                return CombatActions(attack=True)
            if now - self.zero_hp_since >= ZERO_HP_FINISHER_DELAY:
                self.reset_search()
                self.last_tab_time = now - TAB_COOLDOWN
                return CombatActions(press_tab=True)
            return CombatActions()

        self.zero_hp_since = None
        if now - self.last_attack_time >= ATTACK_KEY_INTERVAL:
            self.last_attack_time = now
            return CombatActions(attack=True)
        return CombatActions()
