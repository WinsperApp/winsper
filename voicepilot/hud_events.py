"""Translate authoritative action events into HUD presentation messages.

This is deliberately a one-way adapter: action code never imports Qt or HUD
implementation details, and the HUD never guesses action state from strings.
"""

from __future__ import annotations

from .action_state import ActionEvent, ActionStage
from .hud_core import HudMessage


def message_for_action_event(event: ActionEvent) -> HudMessage | None:
    """Return HUD copy for an action stage, or None when it must stay hidden."""
    context = event.details.context_label or "General"
    mode = event.mode
    stage = event.stage
    if stage is ActionStage.PREPARING_CAPTURE:
        # Stream activation owns readiness; PREPARING remains internal so the
        # user never sees a transient "Starting" state.
        return None
    if stage is ActionStage.CAPTURING:
        if mode == "dictate":
            return HudMessage("Listening", f"{context} — release to insert", "record")
        return HudMessage("Listening for polish", f"{context} — release to polish", "rewrite")
    if stage is ActionStage.STOPPING_CAPTURE:
        return HudMessage("Transcribing", context, "process")
    if stage is ActionStage.TRANSCRIBING:
        return HudMessage("Transcribing", context, "process")
    if stage is ActionStage.READING_SELECTION:
        return HudMessage("Reading selection", context, "process")
    if stage is ActionStage.REWRITING:
        return HudMessage("Polishing text", "Improving clarity", "rewrite")
    if stage is ActionStage.INSERTING:
        return HudMessage("Inserting", context, "process")
    if stage is ActionStage.CANCELLED:
        if event.phase.name == "PROCESSING":
            return HudMessage("Cancelling", "Finishing current model step", "warning")
        return HudMessage("Cancelled", "Nothing was inserted", "cancelled")
    if stage is ActionStage.FAILED:
        outcome = event.details.outcome
        if outcome == "too_short":
            return HudMessage("Too short", "Hold a little longer and try again", "warning")
        if outcome == "microphone_muted":
            return HudMessage("Microphone muted", "Unmute it in Windows and try again", "warning")
        if outcome in {"microphone_error", "microphone_unavailable"}:
            return HudMessage("Microphone error", "Check your mic and try again", "error")
        if outcome == "worker_unavailable":
            return HudMessage("Still finishing", "Wait for the current action, then try again", "warning")
        return HudMessage("Something went wrong", "Nothing was inserted. Please try again.", "error")
    if stage is ActionStage.PAUSED:
        return HudMessage("Paused", "Resume from tray or Settings", "paused")
    return None
