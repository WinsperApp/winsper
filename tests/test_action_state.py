from voicepilot.action_state import (
    ActionCoordinator,
    ActionPhase,
    ActionStage,
    CancelOutcome,
    PauseOutcome,
)
from voicepilot.config import AppConfig


def test_stale_completion_cannot_end_new_action():
    coordinator = ActionCoordinator()
    first = coordinator.start_capture("dictate")
    assert first is not None
    assert coordinator.complete_action(first.action_id)

    second = coordinator.start_capture("polish")
    assert second is not None
    assert not coordinator.complete_action(first.action_id)
    state = coordinator.query()
    assert state.phase is ActionPhase.CAPTURING
    assert state.action == second


def test_processing_stages_are_structured_and_action_scoped():
    coordinator = ActionCoordinator()
    action = coordinator.start_capture("dictate")
    assert action is not None
    assert coordinator.query().stage is ActionStage.PREPARING_CAPTURE
    assert coordinator.capture_ready(action.action_id)
    assert coordinator.query().stage is ActionStage.CAPTURING
    assert coordinator.capture_to_processing(action.action_id)
    assert coordinator.query().stage is ActionStage.STOPPING_CAPTURE
    assert coordinator.advance(action.action_id, ActionStage.TRANSCRIBING)
    assert coordinator.advance(action.action_id, ActionStage.INSERTING)
    assert not coordinator.advance(action.action_id + 1, ActionStage.REWRITING)
    assert coordinator.complete_action(action.action_id)
    assert coordinator.query().stage is ActionStage.COMPLETED


def test_action_details_hold_metadata_without_raw_text_or_audio():
    coordinator = ActionCoordinator()
    action = coordinator.start_capture("polish")
    assert action is not None
    assert coordinator.set_context(action.action_id, "Outlook")
    assert coordinator.set_selection_size(action.action_id, 42)
    assert coordinator.capture_ready(action.action_id)
    assert coordinator.capture_to_processing(action.action_id)
    assert coordinator.set_clip_duration(action.action_id, 1.25)

    details = coordinator.query().details
    assert details.context_label == "Outlook"
    assert details.selection_characters == 42
    assert details.clip_duration_seconds == 1.25
    assert not hasattr(details, "selection_text")
    assert not hasattr(details, "audio")


def test_events_are_ordered_immutable_snapshots_with_terminal_identity():
    coordinator = ActionCoordinator()
    action = coordinator.start_capture("polish")
    assert action is not None
    assert coordinator.capture_ready(action.action_id)
    assert coordinator.capture_to_processing(action.action_id)
    assert coordinator.advance(action.action_id, ActionStage.REWRITING)
    assert coordinator.complete_action(action.action_id)

    events = coordinator.drain_events()
    assert [event.stage for event in events] == [
        ActionStage.PREPARING_CAPTURE,
        ActionStage.CAPTURING,
        ActionStage.STOPPING_CAPTURE,
        ActionStage.REWRITING,
        ActionStage.COMPLETED,
    ]
    assert all(event.action_id == action.action_id for event in events)
    assert all(event.mode == "polish" for event in events)
    assert events[-1].details.outcome == "completed"
    assert coordinator.drain_events() == ()


def test_capture_cancel_and_pause_keep_terminal_action_identity_in_events():
    coordinator = ActionCoordinator()
    cancelled = coordinator.start_capture("dictate")
    assert cancelled is not None
    assert coordinator.cancel(cancelled.action_id) is CancelOutcome.CANCEL_CAPTURING
    cancel_event = coordinator.drain_events()[-1]
    assert (cancel_event.action_id, cancel_event.mode, cancel_event.stage) == (
        cancelled.action_id,
        "dictate",
        ActionStage.CANCELLED,
    )
    assert cancel_event.details.outcome == "cancelled"

    paused = coordinator.start_capture("polish")
    assert paused is not None
    assert coordinator.pause() is PauseOutcome.PAUSED_CAPTURING
    pause_event = coordinator.drain_events()[-1]
    assert (pause_event.action_id, pause_event.mode, pause_event.stage) == (
        paused.action_id,
        "polish",
        ActionStage.PAUSED,
    )
    assert pause_event.details.outcome == "paused"


def test_pause_during_capture_cancels_that_capture_immediately():
    coordinator = ActionCoordinator()
    action = coordinator.start_capture("dictate")
    assert action is not None

    assert coordinator.pause() is PauseOutcome.PAUSED_CAPTURING
    state = coordinator.query()
    assert state.phase is ActionPhase.PAUSED
    assert state.action is None
    assert not coordinator.is_cancelled(action.action_id)
    assert coordinator.resume()
    assert coordinator.query().phase is ActionPhase.IDLE


def test_pause_during_processing_drains_then_pauses():
    coordinator = ActionCoordinator()
    action = coordinator.start_capture("polish")
    assert action is not None
    assert coordinator.capture_ready(action.action_id)
    assert coordinator.capture_to_processing(action.action_id)

    assert coordinator.pause() is PauseOutcome.PAUSE_PROCESSING
    state = coordinator.query()
    assert state.phase is ActionPhase.PROCESSING
    assert state.pause_requested
    assert coordinator.is_cancelled(action.action_id)

    assert coordinator.complete_action(action.action_id)
    state = coordinator.query()
    assert state.phase is ActionPhase.PAUSED
    assert state.action is None
    assert not state.pause_requested
    assert coordinator.resume()
    assert coordinator.query().phase is ActionPhase.IDLE


def test_cancel_processing_keeps_action_until_worker_completes():
    coordinator = ActionCoordinator()
    action = coordinator.start_capture("dictate")
    assert action is not None
    assert coordinator.capture_ready(action.action_id)
    assert coordinator.capture_to_processing(action.action_id)

    assert coordinator.cancel(action.action_id) is CancelOutcome.CANCEL_PROCESSING
    assert coordinator.query().phase is ActionPhase.PROCESSING
    assert coordinator.complete_action(action.action_id)
    assert coordinator.query().phase is ActionPhase.IDLE


def test_capture_cancellation_does_not_leave_a_dead_cancel_marker():
    coordinator = ActionCoordinator()
    action = coordinator.start_capture("dictate")
    assert action is not None

    assert coordinator.cancel(action.action_id) is CancelOutcome.CANCEL_CAPTURING
    assert coordinator.query().phase is ActionPhase.IDLE
    assert not coordinator.is_cancelled(action.action_id)


def test_failure_and_cancelled_completion_never_report_completed():
    coordinator = ActionCoordinator()
    failed = coordinator.start_capture("dictate")
    assert failed is not None
    assert coordinator.fail_action(failed.action_id, "microphone_error")
    state = coordinator.query()
    assert state.stage is ActionStage.FAILED
    assert state.details.outcome == "microphone_error"

    cancelled = coordinator.start_capture("polish")
    assert cancelled is not None
    assert coordinator.capture_ready(cancelled.action_id)
    assert coordinator.capture_to_processing(cancelled.action_id)
    assert coordinator.cancel(cancelled.action_id) is CancelOutcome.CANCEL_PROCESSING
    assert coordinator.complete_action(cancelled.action_id)
    state = coordinator.query()
    assert state.stage is ActionStage.CANCELLED
    assert state.details.outcome == "cancelled"


def test_completed_action_cannot_become_live_again_for_a_late_callback():
    coordinator = ActionCoordinator()
    first = coordinator.start_capture("dictate")
    assert first is not None
    assert coordinator.capture_ready(first.action_id)
    assert coordinator.capture_to_processing(first.action_id)
    assert coordinator.is_active_action(first.action_id)
    assert coordinator.complete_action(first.action_id)

    second = coordinator.start_capture("polish")
    assert second is not None
    assert not coordinator.is_active_action(first.action_id)
    assert coordinator.is_active_action(second.action_id)


def test_thousand_action_cycles_do_not_poison_later_actions():
    coordinator = ActionCoordinator()
    for index in range(1_000):
        action = coordinator.start_capture("dictate" if index % 2 else "polish")
        assert action is not None
        if index % 3 == 0:
            assert coordinator.cancel(action.action_id) is CancelOutcome.CANCEL_CAPTURING
        else:
            assert coordinator.capture_ready(action.action_id)
            assert coordinator.capture_to_processing(action.action_id)
            assert coordinator.advance(action.action_id, ActionStage.TRANSCRIBING)
            if index % 5 == 0:
                assert coordinator.cancel(action.action_id) is CancelOutcome.CANCEL_PROCESSING
            assert coordinator.complete_action(action.action_id)
        assert coordinator.query().phase is ActionPhase.IDLE


def test_concurrent_cancel_and_completion_never_poison_next_action():
    import threading

    coordinator = ActionCoordinator()
    for _ in range(250):
        action = coordinator.start_capture("dictate")
        assert action is not None
        assert coordinator.capture_ready(action.action_id)
        assert coordinator.capture_to_processing(action.action_id)
        gate = threading.Barrier(3)

        def cancel() -> None:
            gate.wait()
            coordinator.cancel(action.action_id)

        def complete() -> None:
            gate.wait()
            coordinator.complete_action(action.action_id)

        cancel_thread = threading.Thread(target=cancel)
        complete_thread = threading.Thread(target=complete)
        cancel_thread.start()
        complete_thread.start()
        gate.wait()
        cancel_thread.join()
        complete_thread.join()

        if coordinator.query().phase is ActionPhase.PROCESSING:
            assert coordinator.complete_action(action.action_id)
        assert coordinator.query().phase is ActionPhase.IDLE
        next_action = coordinator.start_capture("polish")
        assert next_action is not None
        assert not coordinator.complete_action(action.action_id)
        assert coordinator.cancel(next_action.action_id) is CancelOutcome.CANCEL_CAPTURING


def test_latest_event_is_non_consuming_authoritative_snapshot():
    coordinator = ActionCoordinator()
    action = coordinator.start_capture("dictate")
    assert action is not None
    assert coordinator.capture_ready(action.action_id)

    latest = coordinator.latest_event()
    assert latest is not None
    assert latest.action_id == action.action_id
    assert latest.stage is ActionStage.CAPTURING
    assert coordinator.latest_event() == latest
    assert coordinator.drain_events()[-1] == latest


def test_pause_and_shutdown_are_defined_for_every_active_stage():
    capture_stages = [ActionStage.PREPARING_CAPTURE, ActionStage.CAPTURING]
    processing_stages = [
        ActionStage.STOPPING_CAPTURE,
        ActionStage.TRANSCRIBING,
        ActionStage.READING_SELECTION,
        ActionStage.REWRITING,
        ActionStage.INSERTING,
    ]
    for stage in [*capture_stages, *processing_stages]:
        coordinator = ActionCoordinator()
        action = coordinator.start_capture("polish")
        assert action is not None
        if stage is not ActionStage.PREPARING_CAPTURE:
            assert coordinator.capture_ready(action.action_id)
        if stage in processing_stages:
            assert coordinator.capture_to_processing(action.action_id)
            if stage is not ActionStage.STOPPING_CAPTURE:
                assert coordinator.advance(action.action_id, stage)

        if stage in capture_stages:
            assert coordinator.pause() is PauseOutcome.PAUSED_CAPTURING
        else:
            assert coordinator.pause() is PauseOutcome.PAUSE_PROCESSING
            assert coordinator.complete_action(action.action_id)
        assert coordinator.query().phase is ActionPhase.PAUSED

        assert coordinator.resume()
        next_action = coordinator.start_capture("dictate")
        assert next_action is not None
        assert coordinator.begin_shutdown() == next_action.action_id
        assert coordinator.query().phase is ActionPhase.SHUTTING_DOWN
        assert coordinator.start_capture("dictate") is None


def test_shutdown_prevents_new_actions_and_marks_active_action_cancelled():
    coordinator = ActionCoordinator()
    action = coordinator.start_capture("dictate")
    assert action is not None
    assert coordinator.capture_ready(action.action_id)
    assert coordinator.capture_to_processing(action.action_id)

    assert coordinator.begin_shutdown() == action.action_id
    assert coordinator.query().phase is ActionPhase.SHUTTING_DOWN
    assert coordinator.is_cancelled(action.action_id)
    assert coordinator.start_capture("dictate") is None
    assert not coordinator.complete_action(action.action_id)


def test_processing_pause_cancels_backend_then_enters_paused_state():
    import threading

    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    class Hud:
        def __init__(self):
            self.events = []

        def show(self, *args):
            self.events.append(args)

    class Tray:
        def __init__(self):
            self.paused = []

        def set_paused(self, value):
            self.paused.append(value)

    class Worker:
        def __init__(self):
            self.discarded = False

        def discard_pending(self, _predicate):
            self.discarded = True
            return False

    class Transcriber:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    class Harness(ListenerLifecycleMixin):
        pass

    harness = Harness()
    harness._lock = threading.Lock()
    harness._coordinator = ActionCoordinator()
    action = harness._coordinator.start_capture("dictate")
    assert action is not None
    assert harness._coordinator.capture_ready(action.action_id)
    assert harness._coordinator.capture_to_processing(action.action_id)
    harness._action_context = object()
    harness._polish_selection_captures = {}
    harness.tray = Tray()
    harness.hud = Hud()
    harness.transcriber = Transcriber()
    harness._action_worker = Worker()
    runtime = []
    harness._write_runtime_state = lambda *args, **kwargs: runtime.append((args, kwargs))
    recovery = []
    harness._schedule_cancel_recovery = lambda action_id, worker: recovery.append((action_id, worker))

    harness.pause_listening()

    state = harness._coordinator.query()
    assert state.phase is ActionPhase.PROCESSING
    assert state.pause_requested
    assert harness._action_worker.discarded
    assert harness.transcriber.cancelled
    assert recovery == [(action.action_id, harness._action_worker)]
    assert harness.hud.events[-1][0] == "Pausing"

    harness._set_idle(action.action_id)
    assert harness._coordinator.query().phase is ActionPhase.PAUSED
    assert harness.hud.events[-1][0] == "Paused"
    assert harness.tray.paused == [True, True]
    assert runtime[-1][0][0] == "paused"


def test_tray_reload_uses_coordinator_pause_state_without_legacy_flag():
    import threading

    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    class Tray:
        def __init__(self):
            self.config = None
            self.paused = []

        def set_paused(self, value):
            self.paused.append(value)

    class Harness(ListenerLifecycleMixin):
        pass

    config = AppConfig()
    harness = Harness()
    harness._lock = threading.Lock()
    harness._coordinator = ActionCoordinator()
    harness.tray = Tray()

    harness._reload_tray(config, config)
    harness._coordinator.pause()
    harness._reload_tray(config, config)

    assert harness.tray.paused == [False, True]
    assert not hasattr(harness, "_paused")


def test_toggle_release_after_processing_starts_is_a_safe_noop():
    import threading

    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    class Harness(ListenerLifecycleMixin):
        pass

    harness = Harness()
    harness._lock = threading.Lock()
    harness._coordinator = ActionCoordinator()
    action = harness._coordinator.start_capture("dictate")
    assert action is not None
    assert harness._coordinator.capture_ready(action.action_id)
    assert harness._coordinator.capture_to_processing(action.action_id)
    harness.config = AppConfig()
    harness._active_started_at = 0.0
    harness._action_context = None
    harness._is_toggle = False

    harness._on_hotkey_stop("dictate")

    state = harness._coordinator.query()
    assert state.phase is ActionPhase.PROCESSING
    assert state.action == action
