from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import HudConfig


HUD_WIDTH = 336
HUD_HEIGHT = 80
COMPACT_HUD_WIDTH = 120
COMPACT_HUD_HEIGHT = 40
WARNING_HIDE_SECONDS = 2.5
ERROR_HIDE_SECONDS = 4.0
PAUSED_HIDE_SECONDS = 2.5


class ConsoleHUD:
    def __init__(self) -> None:
        self._latest_action_id = 0
        self._latest_terminal_action_id = 0

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def show(self, title: str, subtitle: str = "", kind: str = "idle") -> None:
        line = f"[{kind}] {title}"
        if subtitle:
            line += f" - {subtitle}"
        print(line)

    def show_action_event(self, event) -> None:
        from .action_state import ActionStage
        from .hud_events import message_for_action_event

        if event.action_id and (
            event.action_id < self._latest_action_id
            or (
                event.action_id <= self._latest_terminal_action_id
                and event.stage not in {ActionStage.COMPLETED, ActionStage.CANCELLED, ActionStage.FAILED}
            )
        ):
            return
        self._latest_action_id = max(self._latest_action_id, event.action_id)
        if event.stage in {ActionStage.COMPLETED, ActionStage.CANCELLED, ActionStage.FAILED}:
            self._latest_terminal_action_id = max(self._latest_terminal_action_id, event.action_id)
        message = message_for_action_event(event)
        if message is not None:
            self.show(message.title, message.subtitle, message.kind)

    def show_action_message(self, action_id: int, title: str, subtitle: str = "", kind: str = "idle") -> None:
        if action_id < self._latest_action_id or action_id <= self._latest_terminal_action_id:
            return
        self._latest_action_id = max(self._latest_action_id, action_id)
        self.show(title, subtitle, kind)

@dataclass(frozen=True)
class HudMessage:
    title: str
    subtitle: str
    kind: str
    queued_at: float = field(default_factory=time.perf_counter, compare=False, repr=False)


def hide_deadline(kind: str, config: HudConfig) -> float:
    if config.show_idle:
        return 0.0
    delay = {
        "success": config.auto_hide_seconds,
        "warning": WARNING_HIDE_SECONDS,
        "error": ERROR_HIDE_SECONDS,
        "paused": PAUSED_HIDE_SECONDS,
        "cancelled": WARNING_HIDE_SECONDS,
    }.get(kind)
    if delay is not None:
        return time.monotonic() + delay
    return 0.0


def status_microcopy(kind: str) -> str:
    return {
        "success": "Ready for the next thought",
        "warning": "Nothing changed",
        "error": "Check the tray menu",
        "idle": "",
    }.get(kind, "")
