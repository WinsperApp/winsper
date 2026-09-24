from __future__ import annotations

import threading


def prepare_capture_feedback(owner, action_id: int, delay_seconds: float = 0.10):
    """Schedule truthful slow-start HUD feedback and return the start chime."""

    def publish() -> None:
        if owner._capture_is_active(action_id) and not owner._first_audio_ready(0):
            owner._show_action_message(
                action_id,
                "Preparing Winsper",
                "Getting microphone ready",
                "preparing",
            )

    timer = threading.Timer(delay_seconds, publish)
    timer.daemon = True
    timer.start()
    return getattr(getattr(owner, "recording_chime", None), "play_start_before_capture", None)

def rewrite_delivery_message(
    action: str,
    *,
    reason: str,
    warning: str,
    context_label: str,
    word_count: int,
) -> tuple[str, str, str]:
    """Return truthful selected-text delivery copy for the HUD."""
    statuses = {
        "copy": "Polish copied",
        "copy_target_changed": "Target changed — rewrite copied",
        "copy_elevated": "Copied",
        "copy_blocked": "Paste blocked — rewrite copied",
        "saved_blocked": "Paste blocked — rewrite saved",
        "insert_below": "Change sent below",
        "replace": "Change sent",
    }
    blocked = {"copy_target_changed", "copy_elevated", "copy_blocked", "saved_blocked"}
    if warning:
        return "Change sent", warning, "warning"
    if action == "copy_elevated":
        detail = reason
    elif action == "replace":
        detail = "Selection change sent"
    else:
        detail = f"{context_label} - {word_count} words"
    return statuses.get(action, "Change sent"), detail, "warning" if action in blocked else "success"


class ActionPresentationMixin:
    """Action-scoped HUD delivery shared by lifecycle and pipeline code."""

    def _publish_latest_action_event(self, action_id: int) -> None:
        event = self._coordinator.latest_event()
        show_event = getattr(getattr(self, "hud", None), "show_action_event", None)
        if event is None or event.action_id != action_id:
            return
        if callable(show_event):
            show_event(event)
            return
        from .hud_events import message_for_action_event

        message = message_for_action_event(event)
        if message is not None:
            self.hud.show(message.title, message.subtitle, message.kind)

    def _show_action_message(
        self,
        action_id: int,
        title: str,
        subtitle: str = "",
        kind: str = "idle",
    ) -> None:
        """Show detail without allowing a stale worker to overwrite HUD."""
        if not action_id:
            self.hud.show(title, subtitle, kind)
            return
        show_message = getattr(getattr(self, "hud", None), "show_action_message", None)
        if callable(show_message):
            show_message(action_id, title, subtitle, kind)
            return
        coordinator = getattr(self, "_coordinator", None)
        if coordinator is None or coordinator.is_active_action(action_id):
            self.hud.show(title, subtitle, kind)
