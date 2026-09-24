"""Single-owner action state machine for Winsper.

All mutable action state lives here. Nothing outside this module may
write action phase directly; callers go through the coordinator's methods.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import NamedTuple

logger = logging.getLogger(__name__)


class ActionPhase(Enum):
    """Legal phases of the Winsper action lifecycle."""

    IDLE = auto()
    CAPTURING = auto()     # recorder is running
    PROCESSING = auto()    # worker thread: transcribe / rewrite / paste
    PAUSED = auto()        # hotkeys disabled by user
    SHUTTING_DOWN = auto()


class ActionStage(Enum):
    """Fine-grained, user-meaningful work stage inside an action phase."""

    IDLE = auto()
    PREPARING_CAPTURE = auto()
    CAPTURING = auto()
    STOPPING_CAPTURE = auto()
    TRANSCRIBING = auto()
    READING_SELECTION = auto()
    REWRITING = auto()
    INSERTING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()
    PAUSED = auto()
    SHUTTING_DOWN = auto()


# Legal (from_phase, to_phase) pairs.
_LEGAL_TRANSITIONS: frozenset[tuple[ActionPhase, ActionPhase]] = frozenset(
    {
        (ActionPhase.IDLE, ActionPhase.CAPTURING),
        (ActionPhase.IDLE, ActionPhase.PAUSED),
        (ActionPhase.IDLE, ActionPhase.SHUTTING_DOWN),
        (ActionPhase.CAPTURING, ActionPhase.PROCESSING),
        (ActionPhase.CAPTURING, ActionPhase.IDLE),
        (ActionPhase.CAPTURING, ActionPhase.PAUSED),
        (ActionPhase.CAPTURING, ActionPhase.SHUTTING_DOWN),
        (ActionPhase.PROCESSING, ActionPhase.IDLE),
        (ActionPhase.PROCESSING, ActionPhase.PAUSED),
        (ActionPhase.PROCESSING, ActionPhase.SHUTTING_DOWN),
        (ActionPhase.PAUSED, ActionPhase.IDLE),
        (ActionPhase.PAUSED, ActionPhase.SHUTTING_DOWN),
        (ActionPhase.SHUTTING_DOWN, ActionPhase.SHUTTING_DOWN),
    }
)


@dataclass(frozen=True)
class ActionRecord:
    """Immutable identity of a single action."""

    action_id: int
    mode: str           # "dictate" | "polish" | "rewrite"
    started_at: float = field(default_factory=time.perf_counter)


@dataclass(frozen=True)
class ActionDetails:
    context_label: str = ""
    selection_characters: int = 0
    clip_duration_seconds: float = 0.0
    outcome: str = ""
    stage_started_at: float = 0.0


@dataclass(frozen=True)
class ActionEvent:
    action_id: int
    mode: str
    phase: ActionPhase
    stage: ActionStage
    details: ActionDetails
    occurred_at: float = field(default_factory=time.perf_counter)


class CoordinatorState(NamedTuple):
    """Lock-free snapshot, safe to inspect from any thread."""

    phase: ActionPhase
    action: ActionRecord | None
    paused: bool
    pause_requested: bool
    stage: ActionStage
    details: ActionDetails


class CancelOutcome(Enum):
    NOTHING_TO_CANCEL = auto()
    CANCEL_CAPTURING = auto()   # recorder must be stopped by caller
    CANCEL_PROCESSING = auto()  # worker is mid-flight; caller should drain


class PauseOutcome(Enum):
    REJECTED = auto()
    ALREADY_PAUSED = auto()
    PAUSED_IDLE = auto()
    PAUSED_CAPTURING = auto()
    PAUSE_PROCESSING = auto()  # cancel/drain worker, then enter PAUSED


class ActionCoordinator:
    """Single owner of all Winsper action lifecycle state.

    Thread safety: all public methods are safe to call from any thread.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._phase = ActionPhase.IDLE
        self._action: ActionRecord | None = None
        self._counter: int = 0
        self._cancelled: set[int] = set()
        self._pause_requested = False
        self._stage = ActionStage.IDLE
        self._details = ActionDetails(stage_started_at=time.perf_counter())
        self._events: deque[ActionEvent] = deque(maxlen=256)

    # ------------------------------------------------------------------
    # Read-only queries
    # ------------------------------------------------------------------

    def query(self) -> CoordinatorState:
        with self._lock:
            return CoordinatorState(
                phase=self._phase,
                action=self._action,
                paused=self._phase is ActionPhase.PAUSED,
                pause_requested=self._pause_requested,
                stage=self._stage,
                details=self._details,
            )

    def is_cancelled(self, action_id: int) -> bool:
        if not action_id:
            return False
        with self._lock:
            return action_id in self._cancelled

    def is_active_action(self, action_id: int) -> bool:
        """True only while this exact action still owns capture or processing."""
        if not action_id:
            return False
        with self._lock:
            return (
                self._action is not None
                and self._action.action_id == action_id
                and self._phase in (ActionPhase.CAPTURING, ActionPhase.PROCESSING)
            )

    def is_busy(self) -> bool:
        with self._lock:
            return self._phase in (ActionPhase.CAPTURING, ActionPhase.PROCESSING)

    def current_action_id(self) -> int:
        with self._lock:
            return self._action.action_id if self._action is not None else 0

    def current_mode(self) -> str | None:
        with self._lock:
            return self._action.mode if self._action is not None else None

    def drain_events(self) -> tuple[ActionEvent, ...]:
        with self._lock:
            events = tuple(self._events)
            self._events.clear()
            return events

    def latest_event(self) -> ActionEvent | None:
        """Return newest immutable event without consuming diagnostics history."""
        with self._lock:
            return self._events[-1] if self._events else None

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def start_capture(self, mode: str) -> ActionRecord | None:
        """IDLE -> CAPTURING. Returns new ActionRecord or None if illegal."""
        with self._lock:
            if not self._transition(ActionPhase.IDLE, ActionPhase.CAPTURING):
                return None
            self._counter += 1
            self._action = ActionRecord(action_id=self._counter, mode=mode)
            self._stage = ActionStage.PREPARING_CAPTURE
            self._details = ActionDetails(stage_started_at=time.perf_counter())
            self._publish()
            return self._action

    def capture_ready(self, action_id: int) -> bool:
        """Mark capture active after the selected input stream starts successfully."""
        with self._lock:
            if self._phase is not ActionPhase.CAPTURING or not self._matches(action_id):
                return False
            self._stage = ActionStage.CAPTURING
            self._mark_stage_started()
            self._publish()
            return True

    def set_context(self, action_id: int, context_label: str) -> bool:
        with self._lock:
            if not self._matches(action_id):
                return False
            self._details = ActionDetails(
                context_label=context_label,
                selection_characters=self._details.selection_characters,
                clip_duration_seconds=self._details.clip_duration_seconds,
                outcome=self._details.outcome,
                stage_started_at=self._details.stage_started_at,
            )
            self._publish()
            return True

    def set_selection_size(self, action_id: int, characters: int) -> bool:
        return self._update_details(action_id, selection_characters=max(0, characters))

    def set_clip_duration(self, action_id: int, seconds: float) -> bool:
        return self._update_details(action_id, clip_duration_seconds=max(0.0, seconds))

    def set_outcome(self, action_id: int, outcome: str) -> bool:
        return self._update_details(action_id, outcome=outcome.strip())

    def capture_to_processing(self, action_id: int) -> bool:
        """CAPTURING -> PROCESSING for the given action."""
        with self._lock:
            if (
                self._action is None
                or self._action.action_id != action_id
                or self._stage is not ActionStage.CAPTURING
            ):
                return False
            changed = self._transition(ActionPhase.CAPTURING, ActionPhase.PROCESSING)
            if changed:
                self._stage = ActionStage.STOPPING_CAPTURE
                self._mark_stage_started()
                self._publish()
            return changed

    def advance(self, action_id: int, stage: ActionStage) -> bool:
        """Publish a legal processing stage for the active action."""
        with self._lock:
            if self._phase is not ActionPhase.PROCESSING or self._action is None or self._action.action_id != action_id:
                return False
            if stage not in {
                ActionStage.TRANSCRIBING,
                ActionStage.READING_SELECTION,
                ActionStage.REWRITING,
                ActionStage.INSERTING,
            }:
                return False
            self._stage = stage
            self._mark_stage_started()
            self._publish()
            return True

    def complete_action(self, action_id: int) -> bool:
        """Finish one action, honoring a pending pause request."""
        with self._lock:
            if self._action is None or self._action.action_id != action_id:
                self._cancelled.discard(action_id)
                return False
            current = self._phase
            if current not in (ActionPhase.CAPTURING, ActionPhase.PROCESSING):
                self._cancelled.discard(action_id)
                return False
            mode = self._action.mode
            target = ActionPhase.PAUSED if self._pause_requested else ActionPhase.IDLE
            if not self._transition(current, target):
                return False
            was_cancelled = action_id in self._cancelled
            self._action = None
            self._cancelled.discard(action_id)
            self._pause_requested = False
            self._stage = (
                ActionStage.PAUSED
                if target is ActionPhase.PAUSED
                else ActionStage.CANCELLED
                if was_cancelled
                else ActionStage.COMPLETED
            )
            self._details = ActionDetails(
                context_label=self._details.context_label,
                selection_characters=self._details.selection_characters,
                clip_duration_seconds=self._details.clip_duration_seconds,
                outcome=self._details.outcome or (
                    "paused" if target is ActionPhase.PAUSED else "cancelled" if was_cancelled else "completed"
                ),
                stage_started_at=time.perf_counter(),
            )
            self._publish(action_id=action_id, mode=mode)
            return True

    def fail_action(self, action_id: int, outcome: str = "failed") -> bool:
        """Terminal failure; stale failures cannot affect a newer action."""
        with self._lock:
            if self._action is None or self._action.action_id != action_id:
                return False
            if self._phase not in (ActionPhase.CAPTURING, ActionPhase.PROCESSING):
                return False
            mode = self._action.mode
            target = ActionPhase.PAUSED if self._pause_requested else ActionPhase.IDLE
            if not self._transition(self._phase, target):
                return False
            self._action = None
            self._cancelled.discard(action_id)
            self._pause_requested = False
            self._stage = ActionStage.PAUSED if target is ActionPhase.PAUSED else ActionStage.FAILED
            self._set_terminal_details("paused" if target is ActionPhase.PAUSED else outcome)
            self._publish(action_id=action_id, mode=mode)
            return True

    def cancel(self, action_id: int) -> CancelOutcome:
        """Mark action cancelled. Returns what caller must do next."""
        with self._lock:
            if self._action is None or self._action.action_id != action_id:
                return CancelOutcome.NOTHING_TO_CANCEL
            if self._phase is ActionPhase.CAPTURING:
                mode = self._action.mode
                self._transition(ActionPhase.CAPTURING, ActionPhase.IDLE)
                self._action = None
                self._stage = ActionStage.CANCELLED
                self._set_terminal_details("cancelled")
                self._publish(action_id=action_id, mode=mode)
                return CancelOutcome.CANCEL_CAPTURING
            if self._phase is ActionPhase.PROCESSING:
                self._cancelled.add(action_id)
                self._stage = ActionStage.CANCELLED
                self._set_terminal_details("cancelled")
                self._publish()
                return CancelOutcome.CANCEL_PROCESSING
            return CancelOutcome.NOTHING_TO_CANCEL

    def pause(self) -> PauseOutcome:
        """Pause immediately, or request a pause after an active worker drains."""
        with self._lock:
            if self._phase is ActionPhase.SHUTTING_DOWN:
                return PauseOutcome.REJECTED
            if self._phase is ActionPhase.PAUSED:
                return PauseOutcome.ALREADY_PAUSED
            if self._phase is ActionPhase.CAPTURING:
                if not self._transition(ActionPhase.CAPTURING, ActionPhase.PAUSED):
                    return PauseOutcome.REJECTED
                action = self._action
                self._action = None
                self._stage = ActionStage.PAUSED
                self._set_terminal_details("paused")
                self._publish(action_id=action.action_id if action else 0, mode=action.mode if action else "")
                return PauseOutcome.PAUSED_CAPTURING
            if self._phase is ActionPhase.PROCESSING:
                if self._action is not None:
                    self._cancelled.add(self._action.action_id)
                self._pause_requested = True
                self._stage = ActionStage.CANCELLED
                self._publish()
                return PauseOutcome.PAUSE_PROCESSING
            if self._transition(ActionPhase.IDLE, ActionPhase.PAUSED):
                self._stage = ActionStage.PAUSED
                self._publish(action_id=0, mode="")
                return PauseOutcome.PAUSED_IDLE
            return PauseOutcome.REJECTED

    def resume(self) -> bool:
        with self._lock:
            if not self._transition(ActionPhase.PAUSED, ActionPhase.IDLE):
                return False
            self._pause_requested = False
            self._stage = ActionStage.IDLE
            self._publish(action_id=0, mode="")
            return True

    def begin_shutdown(self) -> int:
        """Prevent new actions and cancel any current action. Return its ID."""
        with self._lock:
            if self._phase is ActionPhase.SHUTTING_DOWN:
                return self._action.action_id if self._action is not None else 0
            old = self._phase
            action_id = self._action.action_id if self._action is not None else 0
            if action_id and self._phase is ActionPhase.PROCESSING:
                self._cancelled.add(action_id)
            self._phase = ActionPhase.SHUTTING_DOWN
            self._pause_requested = False
            self._stage = ActionStage.SHUTTING_DOWN
            self._details = ActionDetails(
                context_label=self._details.context_label,
                selection_characters=self._details.selection_characters,
                clip_duration_seconds=self._details.clip_duration_seconds,
                outcome="shutting_down",
                stage_started_at=time.perf_counter(),
            )
            self._publish(action_id=action_id, mode=self._action.mode if self._action else "")
            logger.debug("coordinator: %s -> SHUTTING_DOWN", old.name)
            return action_id

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _matches(self, action_id: int) -> bool:
        return self._action is not None and self._action.action_id == action_id

    def _update_details(self, action_id: int, **changes) -> bool:
        with self._lock:
            if not self._matches(action_id):
                return False
            self._details = ActionDetails(
                context_label=changes.get("context_label", self._details.context_label),
                selection_characters=changes.get("selection_characters", self._details.selection_characters),
                clip_duration_seconds=changes.get("clip_duration_seconds", self._details.clip_duration_seconds),
                outcome=changes.get("outcome", self._details.outcome),
                stage_started_at=changes.get("stage_started_at", self._details.stage_started_at),
            )
            self._publish()
            return True

    def _mark_stage_started(self) -> None:
        self._details = ActionDetails(
            context_label=self._details.context_label,
            selection_characters=self._details.selection_characters,
            clip_duration_seconds=self._details.clip_duration_seconds,
            outcome=self._details.outcome,
            stage_started_at=time.perf_counter(),
        )

    def _set_terminal_details(self, outcome: str) -> None:
        """Record terminal result without requiring an active ActionRecord."""
        self._details = ActionDetails(
            context_label=self._details.context_label,
            selection_characters=self._details.selection_characters,
            clip_duration_seconds=self._details.clip_duration_seconds,
            outcome=outcome,
            stage_started_at=time.perf_counter(),
        )

    def _publish(self, action_id: int | None = None, mode: str | None = None) -> None:
        action = self._action
        self._events.append(
            ActionEvent(
                action_id=action.action_id if action_id is None and action is not None else int(action_id or 0),
                mode=action.mode if mode is None and action is not None else str(mode or ""),
                phase=self._phase,
                stage=self._stage,
                details=self._details,
            )
        )

    def _transition(self, from_phase: ActionPhase, to_phase: ActionPhase) -> bool:
        if self._phase is not from_phase:
            logger.warning(
                "coordinator: illegal transition %s -> %s (current: %s)",
                from_phase.name,
                to_phase.name,
                self._phase.name,
            )
            return False
        if (from_phase, to_phase) not in _LEGAL_TRANSITIONS:
            logger.error(
                "coordinator: undefined transition %s -> %s",
                from_phase.name,
                to_phase.name,
            )
            return False
        logger.debug("coordinator: %s -> %s", from_phase.name, to_phase.name)
        self._phase = to_phase
        return True
