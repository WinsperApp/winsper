from pathlib import Path

from voicepilot.action_state import ActionCoordinator
from voicepilot.config import AppConfig, ProfileStyle
from voicepilot.app_context import (
    ForegroundContext,
)


def test_polish_selection_wait_covers_safe_clipboard_read_budget():
    from voicepilot.lifecycle_capture import (
        POLISH_SELECTION_SETTLE_SECONDS,
        POLISH_SELECTION_WAIT_SECONDS,
    )

    assert POLISH_SELECTION_WAIT_SECONDS >= POLISH_SELECTION_SETTLE_SECONDS + 1.5

def test_lifecycle_hold_releases_to_processing_and_quick_tap_locks():
    import threading
    from unittest.mock import patch

    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    class Hud:
        def show(self, *_args):
            pass

    class Harness(ListenerLifecycleMixin):
        pass

    context = object()
    harness = Harness()
    harness.config = AppConfig()
    harness._lock = threading.Lock()
    harness._coordinator = ActionCoordinator()
    harness._active_started_at = 10.0
    harness._action_context = context
    harness._is_toggle = False

    rec = harness._coordinator.start_capture("dictate")
    action_id = rec.action_id
    harness._coordinator.capture_ready(action_id)
    harness.hud = Hud()
    processed = []
    harness._stop_recording_and_process = lambda mode, target, action_id: processed.append((mode, target, action_id))
    harness._resolve_action_context = lambda target, action_id: target

    with patch("voicepilot.lifecycle_capture.time.perf_counter", return_value=11.0):
        harness._on_hotkey_stop("dictate")
    assert processed == [("dictate", context, action_id)]

    harness._coordinator.complete_action(action_id)
    harness._active_started_at = 20.0
    harness._action_context = context
    harness._is_toggle = False

    harness._coordinator.start_capture("dictate")
    processed.clear()
    with patch("voicepilot.lifecycle_capture.time.perf_counter", return_value=20.1):
        harness._on_hotkey_stop("dictate")
    assert processed == []
    assert harness._is_toggle is True


def test_dictate_and_polish_show_listening_immediately_after_stream_starts():
    import threading
    from unittest.mock import patch

    from voicepilot.app_context import WindowInfo
    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    events = []

    class Hud:
        def show(self, title, *_args):
            events.append(f"hud:{title}")

    class Recorder:
        def start(self):
            from voicepilot.audio import AudioStartMetrics

            events.append("recorder:started")
            return AudioStartMetrics(stream_start_ms=2.0, first_frame_ms=0.0, attempts=1)

    class Chime:
        @staticmethod
        def play_start_before_capture(_action_id):
            events.append("chime:ready")

    class Harness(ListenerLifecycleMixin):
        pass

    harness = Harness()
    harness.config = AppConfig()
    harness.config_path = Path("config.yaml")
    harness._lock = threading.Lock()
    harness._coordinator = ActionCoordinator()
    harness._is_toggle = False
    harness._action_context = None
    harness._active_started_at = 0.0
    harness._context_action_id = 0
    harness.hud = Hud()
    harness.recorder = Recorder()
    harness.recording_chime = Chime()
    harness._start_context_refresh = lambda *_args: None
    harness._speech_config_for_mode = lambda _mode: harness.config.speech

    class Timer:
        def __init__(self, _delay, _callback):
            self.daemon = False

        def start(self):
            pass

        def cancel(self):
            pass

    def foreground_window():
        events.append("context:schedule")
        return WindowInfo(123, "notepad.exe", "Notes")

    for mode, title in (("dictate", "Listening"), ("polish", "Listening for polish")):
        events.clear()
        harness._coordinator.cancel(harness._coordinator.current_action_id())
        with (
            patch("voicepilot.lifecycle_capture.threading.Timer", Timer),
            patch("voicepilot.lifecycle_capture.get_foreground_window_details", side_effect=foreground_window),
            patch("voicepilot.lifecycle_capture.polish_setup_issue", return_value=None),
        ):
            harness._on_hotkey_start(mode)

        assert events == ["chime:ready", "recorder:started", f"hud:{title}", "context:schedule"]


def test_polish_setup_problem_blocks_microphone_capture():
    import threading
    from unittest.mock import patch

    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    shown = []

    class Hud:
        def show(self, *args):
            shown.append(args)

    class Recorder:
        def start(self):
            raise AssertionError("Polish setup failure must not open microphone")

    class Harness(ListenerLifecycleMixin):
        pass

    harness = Harness()
    harness.config = AppConfig()
    harness.config_path = Path("config.yaml")
    harness._lock = threading.Lock()
    harness._coordinator = ActionCoordinator()
    harness._is_toggle = False
    harness._action_context = None
    harness.hud = Hud()
    harness.recorder = Recorder()
    harness._speech_config_for_mode = lambda _mode: harness.config.speech

    with patch(
        "voicepilot.lifecycle_capture.polish_setup_issue",
        return_value=(
            "Polish model required",
            "Download or select an AI model in Settings > Polish > Advanced",
        ),
    ):
        harness._on_hotkey_start("polish")

    assert shown == [
        (
            "Polish model required",
            "Download or select an AI model in Settings > Polish > Advanced",
            "warning",
        )
    ]
    assert harness._coordinator.query().phase.name == "IDLE"


def test_native_capture_does_not_claim_listening_before_first_packet():
    import threading
    import time
    from unittest.mock import patch

    from voicepilot.app_context import WindowInfo
    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    first_packet = threading.Event()
    listening = threading.Event()
    shown = []

    class Hud:
        def show(self, title, subtitle, kind):
            shown.append((title, subtitle, kind))
            if title == "Listening":
                listening.set()

    class Recorder:
        def start(self):
            from voicepilot.audio import AudioStartMetrics

            return AudioStartMetrics(stream_start_ms=3.0, first_frame_ms=0.0, attempts=1)

        def wait_for_first_frame(self, timeout):
            return first_packet.wait(timeout)

    class Harness(ListenerLifecycleMixin):
        pass

    harness = Harness()
    harness.config = AppConfig()
    harness.config_path = Path("config.yaml")
    harness._lock = threading.Lock()
    harness._coordinator = ActionCoordinator()
    harness._is_toggle = False
    harness._action_context = None
    harness._active_started_at = 0.0
    harness._context_action_id = 0
    harness.hud = Hud()
    harness.recorder = Recorder()
    harness._start_context_refresh = lambda *_args: None

    with patch(
        "voicepilot.lifecycle_capture.get_foreground_window_details",
        return_value=WindowInfo(123, "notepad.exe", "Notes"),
    ):
        harness._on_hotkey_start("dictate")

    time.sleep(0.02)
    assert all(title != "Listening" for title, _subtitle, _kind in shown)
    first_packet.set()
    assert listening.wait(0.5)


def test_starting_hud_path_is_removed():
    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    assert not hasattr(ListenerLifecycleMixin, "_schedule_starting_hud")


def test_context_detection_updates_listening_hud_asynchronously(tmp_path):
    import threading

    from voicepilot.app_context import WindowInfo
    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    fast_context = ForegroundContext(
        process_name="chrome.exe",
        window_title="Inbox",
        profile_name="general",
        profile=ProfileStyle(label="General"),
        window_hwnd=123,
    )
    refined_context = ForegroundContext(
        process_name="chrome.exe",
        window_title="Inbox",
        profile_name="email",
        profile=ProfileStyle(label="Email"),
        browser_domain="mail.google.com",
        browser_label="Gmail",
        window_hwnd=123,
    )
    hud_updates = []

    class Hud:
        def show(self, title, subtitle, kind):
            hud_updates.append((title, subtitle, kind))

    class ContextDetector:
        def detect_fast(self, _window):
            return fast_context

        def refresh_window(self, _window):
            return refined_context

    class Harness(ListenerLifecycleMixin):
        pass

    harness = Harness()
    harness.config_path = tmp_path / "config.yaml"
    harness._lock = threading.Lock()
    harness._coordinator = ActionCoordinator()
    rec = harness._coordinator.start_capture("dictate")
    action_id = rec.action_id
    harness._context_action_id = action_id
    harness._context_result = None
    assert harness._coordinator.current_mode() == "dictate"
    harness._action_context = None
    harness.context_detector = ContextDetector()
    harness.hud = Hud()

    harness._refresh_action_context(
        WindowInfo(123, "chrome.exe", "Inbox"),
        "dictate",
        action_id,
        microphone_ms=4.2,
        listening_queued_ms=4.5,
        stream_start_ms=1.2,
        first_frame_ms=3.8,
        audio_attempts=1,
    )

    assert harness._context_result is refined_context
    assert harness._action_context is refined_context
    assert [update[1] for update in hud_updates] == [
        "Chrome — release to insert",
        "Gmail — release to insert",
    ]
    timing_log = (tmp_path / "voicepilot.log").read_text(encoding="utf-8")
    assert "microphone=4.2ms" in timing_log
    assert "stream_start=1.2ms" in timing_log
    assert "first_frame=3.8ms" in timing_log
    assert "audio_attempts=1" in timing_log
    assert "context_fast=" in timing_log
    assert "context_full=" in timing_log


def test_hud_start_waits_for_native_window_readiness():
    from unittest.mock import patch

    from voicepilot.hud_qt import HUD_FRAME_INTERVAL_MS, HUD_READY_TIMEOUT_SECONDS, QtStatusHUD

    calls = []

    class Event:
        def wait(self, timeout):
            calls.append(("wait", timeout))
            return True

    class Process:
        def __init__(self, **kwargs):
            calls.append(("process", kwargs["args"]))

        def is_alive(self):
            return False

        def start(self):
            calls.append(("start",))

    class Context:
        def Queue(self):
            return object()

        def Event(self):
            return Event()

        def Process(self, **kwargs):
            return Process(**kwargs)

    with patch("voicepilot.hud_qt.mp.get_context", return_value=Context()):
        hud = QtStatusHUD(AppConfig().hud)
        hud.start()

    assert HUD_FRAME_INTERVAL_MS <= 16
    assert calls[-1] == ("wait", HUD_READY_TIMEOUT_SECONDS)


def test_audio_warmup_stream_is_reused_and_proven_by_first_capture():
    import sys
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

    streams = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback
            self.started = 0
            self.stopped = 0
            self.closed = 0

        def start(self):
            self.started += 1
            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            self.stopped += 1

        def close(self):
            self.closed += 1

    class SoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            stream = Stream(kwargs["callback"])
            streams.append(stream)
            return stream

    config = AppConfig().audio
    config.input_device = 3
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        recorder.warm_up()
        assert len(streams) == 1
        assert streams[0].started == 0
        metrics = recorder.start()
        clip = recorder.stop()
        second_metrics = recorder.start()
        second_clip = recorder.stop()
        assert len(streams) == 1
        assert streams[0].started == 2
        assert streams[0].stopped == 2
        assert streams[0].closed == 0
        assert metrics.attempts == 1
        assert metrics.first_frame_received
        assert metrics.first_frame_ms >= 0
        assert clip.samples.size == 320
        assert second_metrics.attempts == 1
        assert second_metrics.first_frame_received
        assert second_clip.samples.size == 320
        recorder.close()

    assert streams[0].closed == 1


def test_audio_missing_first_frame_reports_unavailable_at_stop():
    import sys
    from unittest.mock import patch

    import pytest

    from voicepilot.audio import AudioRecorder, MicrophoneUnavailable

    streams = []

    class Stream:
        def __init__(self):
            self.stopped = 0
            self.closed = 0

        def start(self):
            pass

        def stop(self):
            self.stopped += 1

        def close(self):
            self.closed += 1

    class SoundDevice:
        @staticmethod
        def InputStream(**_kwargs):
            stream = Stream()
            streams.append(stream)
            return stream

    with patch.dict(sys.modules, {"sounddevice": SoundDevice}), patch(
        "voicepilot.audio.STOP_FIRST_FRAME_GRACE_SECONDS", 0.01
    ):
        config = AppConfig().audio
        config.min_record_seconds = 0
        recorder = AudioRecorder(config)
        metrics = recorder.start()
        assert not metrics.first_frame_received
        with pytest.raises(MicrophoneUnavailable, match="delivered no audio"):
            recorder.stop()
        recorder.close()

    assert len(streams) == 1
    assert all(stream.closed == 1 for stream in streams)


def test_single_instance_mutex_is_shared_across_config_paths(tmp_path):
    from voicepilot.instance import (
        SingleInstanceGuard,
        WINSPER_INSTANCE_MUTEX,
        _instance_lock_path,
    )

    first = SingleInstanceGuard(tmp_path / "first.yaml")
    second = SingleInstanceGuard(tmp_path / "second.yaml")

    assert first.name == WINSPER_INSTANCE_MUTEX
    assert second.name == WINSPER_INSTANCE_MUTEX
    assert _instance_lock_path().name == "winsper.instance.lock"

def test_capture_start_feedback_shows_only_while_audio_is_not_ready(monkeypatch):
    from types import SimpleNamespace

    from voicepilot.action_presentation import prepare_capture_feedback

    callbacks = []
    shown = []

    class Timer:
        def __init__(self, delay, callback):
            assert delay == 0.10
            callbacks.append(callback)
            self.daemon = False

        def start(self):
            pass

    owner = SimpleNamespace(
        _capture_is_active=lambda _action_id: True,
        _first_audio_ready=lambda _timeout: False,
        _show_action_message=lambda *message: shown.append(message),
        recording_chime=SimpleNamespace(play_start_before_capture=object()),
    )
    monkeypatch.setattr("voicepilot.action_presentation.threading.Timer", Timer)

    chime = prepare_capture_feedback(owner, 8)
    callbacks.pop()()

    assert chime is owner.recording_chime.play_start_before_capture
    assert shown == [(8, "Preparing Winsper", "Getting microphone ready", "preparing")]

    owner._first_audio_ready = lambda _timeout: True
    prepare_capture_feedback(owner, 9)
    callbacks.pop()()
    assert len(shown) == 1