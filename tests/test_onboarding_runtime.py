from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest

from voicepilot.config import AppConfig, save_config


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def make_window(tmp_path):
    from voicepilot.onboarding_qt import OnboardingWindow

    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    return OnboardingWindow(path)


def close_window(window, app) -> None:
    window.close()
    app.processEvents()


def test_rapid_back_to_language_stops_runtime_and_hud(tmp_path, qt_app, monkeypatch):
    window = make_window(tmp_path)
    stopped: list[int] = []
    hud_stopped: list[int] = []
    monkeypatch.setattr(window, "_stop_polish_test", lambda: None)
    monkeypatch.setattr(window, "_cancel_dictation_attempt", lambda: None)
    monkeypatch.setattr(window, "_stop_polish_test_runtime", lambda: None)
    monkeypatch.setattr(window, "_stop_dictation_test", lambda: stopped.append(window.index))
    monkeypatch.setattr(window, "_stop_dictation_test_hud", lambda: hud_stopped.append(window.index))
    monkeypatch.setattr(window, "_persist_progress", lambda: None)
    monkeypatch.setattr(window, "_refresh", lambda: None)

    window.index = 4
    for _ in range(4):
        window._back()

    assert window.index == 0
    assert stopped == [1]
    assert hud_stopped == [1]
    close_window(window, qt_app)


def test_close_hides_window_before_runtime_cleanup(tmp_path, qt_app):
    window = make_window(tmp_path)
    visible_during_close: list[bool] = []

    class Runtime:
        def close(self):
            visible_during_close.append(window.window.isVisible())

    window.polish_rewriter = Runtime()
    window.show()
    qt_app.processEvents()
    assert window.window.isVisible()
    window.close()
    assert visible_during_close == [False]
    qt_app.processEvents()


def test_dictation_capture_start_matches_production_order(tmp_path, qt_app, monkeypatch):
    import voicepilot.onboarding_tests as onboarding_tests

    calls: list[str] = []
    started: list[tuple[object, int]] = []

    class ThreadProbe:
        def __init__(self, *, target, args, **_kwargs):
            self.args = args

        def start(self):
            started.append(self.args)

    class Recorder:
        def start(self):
            calls.append("start")

    window = make_window(tmp_path)
    recorder = Recorder()
    window.dictation_runtime_ready = True
    window.dictation_recorder = recorder
    monkeypatch.setattr(onboarding_tests.threading, "Thread", ThreadProbe)
    window._begin_dictation_recording()
    assert calls == ["start"]
    assert started == [(recorder, window.active_dictation_test_generation)]
    assert window.dictation_recording is True
    window.dictation_recorder = None
    close_window(window, qt_app)


def test_stopping_onboarding_cancels_and_joins_dictation_preparation(
    tmp_path, qt_app, monkeypatch
):
    import voicepilot.onboarding_tests as onboarding_tests

    preload_started = threading.Event()
    preload_cancelled = threading.Event()
    recorder_closed = threading.Event()

    class Recorder:
        def warm_up(self):
            raise AssertionError("warm-up must not run after cancellation")

        def close(self):
            recorder_closed.set()

    class Transcriber:
        def __init__(self, *_args, **_kwargs):
            pass

        def mode_config(self, _model):
            return window.config.speech

        def preload_model(self, *_args, **_kwargs):
            preload_started.set()
            assert preload_cancelled.wait(timeout=2.0)

        def cancel(self):
            preload_cancelled.set()

        def close(self):
            preload_cancelled.set()

    monkeypatch.setattr(onboarding_tests, "create_audio_recorder", lambda _config: Recorder())
    monkeypatch.setattr(onboarding_tests, "IsolatedSpeechTranscriber", Transcriber)
    window = make_window(tmp_path)
    window.dictation_runtime_generation = 5
    cancel_event = threading.Event()
    worker = threading.Thread(
        target=window._prepare_dictation_test_runtime,
        args=(window._preview_config(), 5, cancel_event),
    )
    window.dictation_runtime_cancel_event = cancel_event
    window.dictation_runtime_thread = worker
    window.dictation_runtime_preparing = True
    worker.start()
    assert preload_started.wait(timeout=1.0)
    window._stop_dictation_test()
    assert cancel_event.is_set()
    assert preload_cancelled.is_set()
    assert recorder_closed.is_set()
    assert not worker.is_alive()
    close_window(window, qt_app)


def test_cancel_dictation_attempt_interrupts_active_transcription(tmp_path, qt_app):
    window = make_window(tmp_path)
    cancelled: list[bool] = []

    class Transcriber:
        def cancel(self):
            cancelled.append(True)

        def close(self):
            pass

    window.dictation_transcriber = Transcriber()
    window.dictation_test_running = True
    window.dictation_recording = False
    window._cancel_dictation_attempt()
    assert cancelled == [True]
    window.dictation_transcriber = None
    close_window(window, qt_app)


def test_dictation_ready_registers_hotkey_before_practice(tmp_path, qt_app, monkeypatch):
    window = make_window(tmp_path)
    calls: list[str] = []

    class Resource:
        def close(self):
            pass

    window.index = 1
    window.dictation_runtime_generation = 8
    window.dictation_runtime_preparing = True
    monkeypatch.setattr(window, "_restart_onboarding_hotkeys", lambda: calls.append("register"))
    window.dictation_runtime_events.put(
        (8, "ready", (Resource(), Resource(), window.config.speech, True))
    )
    window._poll_dictation_runtime()
    assert window.dictation_runtime_ready
    assert calls == ["register"]
    close_window(window, qt_app)


def test_hotkey_prepares_hidden_hud_when_polish_page_opens_directly(tmp_path, qt_app, monkeypatch):
    from PySide6.QtGui import QGuiApplication

    import voicepilot.onboarding_shortcuts as onboarding_shortcuts

    window = make_window(tmp_path)
    calls: list[str] = []

    class Hotkeys:
        def __init__(self, *_args, **_kwargs):
            calls.append("created")

        def start(self):
            calls.append("started")

        def stop(self):
            calls.append("stopped")

    def prepare_hud():
        calls.append("hud")
        window.dictation_test_hud = object()

    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.setattr(onboarding_shortcuts, "GlobalHoldHotkeys", Hotkeys)
    monkeypatch.setattr(window, "_prepare_dictation_test_hud", prepare_hud)
    window.index = 2
    window._restart_onboarding_hotkeys()
    assert calls == []
    window.dictation_runtime_ready = True
    window._restart_onboarding_hotkeys()
    assert calls == ["hud"]
    window.dictation_test_hud_ready.set()
    window._restart_onboarding_hotkeys()
    assert calls == ["hud", "created", "started"]
    window._restart_onboarding_hotkeys()
    assert calls == ["hud", "created", "started"]
    window.index = 4
    window._restart_onboarding_hotkeys()
    assert calls == ["hud", "created", "started", "stopped"]
    close_window(window, qt_app)


def test_selected_polish_hotkey_shows_hud_while_model_is_preparing(tmp_path, qt_app, monkeypatch):
    window = make_window(tmp_path)
    messages: list[tuple[str, str, str]] = []
    selected = next(
        button
        for button in window.polish_mode_group.buttons()
        if button.property("mode_id") == "selected"
    )
    selected.setChecked(True)
    window.index = 2
    window.dictation_runtime_ready = True
    window.dictation_transcriber = SimpleNamespace(close=lambda: None)
    window.polish_rewriter = None
    monkeypatch.setattr(window, "_polish_support_ready", lambda: True)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: True)
    monkeypatch.setattr(window, "_ensure_polish_test_runtime", lambda: None)
    monkeypatch.setattr(window, "_show_dictation_test_hud", lambda *message: messages.append(message))

    window._begin_polish_recording()

    assert messages == [("Preparing Polish", "Getting writing support ready", "preparing")]
    close_window(window, qt_app)

def test_first_release_follows_production_start_then_stop_order(tmp_path, qt_app, monkeypatch):
    window = make_window(tmp_path)
    processing_done = threading.Event()
    calls: list[str] = []

    class Recorder:
        def start(self):
            calls.append("start")

        def wait_for_first_frame(self, _timeout):
            return True

        def stop(self):
            calls.append("stop")
            return SimpleNamespace(duration_seconds=1.0)

    window.dictation_runtime_ready = True
    window.dictation_recorder = Recorder()
    window.dictation_transcriber = object()
    window.dictation_speech_config = window.config.speech
    monkeypatch.setattr(window, "_run_dictation_test", lambda *_args: processing_done.set())
    window._begin_dictation_recording()
    assert calls == ["start"]
    window._finish_dictation_recording()
    assert processing_done.wait(1.0)
    assert calls == ["start", "stop"]
    window.dictation_recorder = None
    window.dictation_transcriber = None
    close_window(window, qt_app)


def test_first_hud_message_waits_for_startup_instead_of_being_dropped(
    tmp_path, qt_app, monkeypatch
):
    from PySide6.QtGui import QGuiApplication

    import voicepilot.hud_ui as hud_ui

    window = make_window(tmp_path)
    startup_entered = threading.Event()
    allow_startup = threading.Event()

    class HudProbe:
        def __init__(self):
            self.messages = []

        def start(self):
            startup_entered.set()
            assert allow_startup.wait(timeout=2.0)

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

        def stop(self):
            pass

    probe = HudProbe()
    window.index = 1
    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.setattr(hud_ui, "create_status_hud", lambda _config: probe)
    window._show_dictation_test_hud(
        "Preparing Winsper", "Getting things ready", "preparing"
    )
    assert startup_entered.wait(timeout=1.0)
    assert probe.messages == []
    allow_startup.set()
    window.dictation_test_hud_thread.join(timeout=2.0)
    assert probe.messages == [
        ("Preparing Winsper", "Getting things ready", "preparing")
    ]
    close_window(window, qt_app)


def test_runtime_preparation_publishes_preparing_hud_before_worker_start(
    tmp_path, qt_app, monkeypatch
):
    from PySide6.QtGui import QGuiApplication

    import voicepilot.onboarding_tests as onboarding_tests

    window = make_window(tmp_path)
    window.index = 1
    calls: list[object] = []

    class ThreadProbe:
        def __init__(self, *, target, args, **_kwargs):
            self.target = target
            self.args = args

        def start(self):
            calls.append("worker")

    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.setattr(window, "_show_dictation_test_hud", lambda *message: calls.append(message))
    monkeypatch.setattr(onboarding_tests.threading, "Thread", ThreadProbe)
    window._ensure_dictation_test_runtime()
    assert calls == [
        ("Preparing Winsper", "Getting things ready", "preparing"),
        "worker",
    ]
    close_window(window, qt_app)


def test_first_page_prestarts_hud_without_showing_readiness_message(
    tmp_path, qt_app, monkeypatch
):
    from PySide6.QtGui import QGuiApplication

    import voicepilot.onboarding_tests as onboarding_tests

    window = make_window(tmp_path)
    calls: list[object] = []

    class ThreadProbe:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            calls.append("worker")

    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.setattr(window, "_prepare_dictation_test_hud", lambda: calls.append("hud-start"))
    monkeypatch.setattr(window, "_show_dictation_test_hud", lambda *message: calls.append(message))
    monkeypatch.setattr(onboarding_tests.threading, "Thread", ThreadProbe)
    window.index = 0
    window._ensure_dictation_test_runtime()
    assert calls == ["hud-start", "worker"]
    close_window(window, qt_app)


def test_second_page_shows_preparing_with_prestarted_hud(tmp_path, qt_app, monkeypatch):
    window = make_window(tmp_path)
    calls: list[tuple[str, str, str]] = []
    preview = window._preview_config()
    window.index = 1
    window.dictation_runtime_preparing = True
    window.dictation_runtime_signature = (
        preview.dictation.ramble_model,
        preview.speech.language,
    )
    window.dictation_test_hud = object()
    monkeypatch.setattr(window, "_show_dictation_test_hud", lambda *message: calls.append(message))
    window._ensure_dictation_test_runtime()
    assert calls == [("Preparing Winsper", "Getting things ready", "preparing")]
    window.dictation_test_hud = None
    close_window(window, qt_app)


def test_first_page_ready_event_stays_quiet(tmp_path, qt_app, monkeypatch):
    window = make_window(tmp_path)
    calls: list[object] = []

    class Resource:
        def close(self):
            pass

    window.index = 0
    window.dictation_runtime_generation = 5
    monkeypatch.setattr(window, "_show_dictation_test_hud", lambda *message: calls.append(message))
    monkeypatch.setattr(window, "_restart_onboarding_hotkeys", lambda: None)
    window.dictation_runtime_events.put(
        (5, "ready", (Resource(), Resource(), window.config.speech, True))
    )
    window._poll_dictation_runtime()
    assert window.dictation_runtime_ready is True
    assert calls == []
    close_window(window, qt_app)


def test_hud_readiness_enables_shortcut_from_existing_poller(tmp_path, qt_app, monkeypatch):
    window = make_window(tmp_path)
    calls: list[str] = []
    window.index = 1
    window.dictation_runtime_ready = True
    window.dictation_test_hud = object()
    window.dictation_test_hud_ready.set()
    monkeypatch.setattr(window, "_restart_onboarding_hotkeys", lambda: calls.append("hotkeys"))
    window._poll_dictation_test()
    assert calls == ["hotkeys"]
    window.dictation_test_hud = None
    close_window(window, qt_app)


def test_transcription_worker_failure_is_logged_and_uses_warning_hud(
    tmp_path, qt_app, monkeypatch
):
    import voicepilot.onboarding_tests as onboarding_tests

    window = make_window(tmp_path)

    class Transcriber:
        def transcribe(self, *_args, **_kwargs):
            raise RuntimeError("speech worker closed unexpectedly")

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    probe = HudProbe()
    monkeypatch.setattr(onboarding_tests, "clip_has_speech_activity", lambda _clip: True)
    window.dictation_test_hud = probe
    window.active_dictation_test_generation = 11
    window._run_dictation_test(
        window._preview_config(), object(), 11, Transcriber(), window.config.speech
    )
    window._poll_dictation_test()
    assert window.dictation_status.text() == "Try Dictate again"
    assert probe.messages[-1] == (
        "Try Dictate again",
        "Nothing was inserted",
        "warning",
    )
    log_text = (window.config_path.parent / "voicepilot.log").read_text(encoding="utf-8")
    assert "onboarding Dictate transcription failure" in log_text
    assert "speech worker closed unexpectedly" in log_text
    window.dictation_test_hud = None
    close_window(window, qt_app)


def test_polish_release_uses_production_transcribing_hud(tmp_path, qt_app, monkeypatch):
    import voicepilot.onboarding_shortcuts as onboarding_shortcuts

    window = make_window(tmp_path)

    class Recorder:
        def stop(self):
            return object()

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    class ThreadProbe:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    probe = HudProbe()
    window.polish_recording = True
    window.polish_recorder = Recorder()
    window.polish_active_app = {"label": "Outlook", "process": "outlook.exe", "profile": "email"}
    window.dictation_transcriber = object()
    window.polish_rewriter = object()
    window.dictation_test_hud = probe
    monkeypatch.setattr(onboarding_shortcuts.threading, "Thread", ThreadProbe)
    window._finish_polish_recording()
    assert probe.messages[-1] == ("Transcribing", "Outlook", "process")
    window.dictation_transcriber = None
    window.polish_rewriter = None
    window.dictation_test_hud = None
    close_window(window, qt_app)
