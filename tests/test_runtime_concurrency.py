from __future__ import annotations

import threading
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from voicepilot.audio import AudioCaptureDiagnostics
from voicepilot.config import AppConfig
from voicepilot.hotkeys import GlobalHoldHotkeys
from voicepilot.isolated_audio import IsolatedAudioRecorder
from voicepilot.isolated_transcribe import IsolatedSpeechTranscriber, SpeechWorkerInterrupted


def _isolated_audio_harness() -> IsolatedAudioRecorder:
    recorder = IsolatedAudioRecorder.__new__(IsolatedAudioRecorder)
    recorder.config = AppConfig().audio
    recorder._process = Mock()
    recorder._process.is_alive.return_value = True
    recorder._requests = object()
    recorder._responses = object()
    recorder._state_lock = threading.RLock()
    recorder._request_lock = threading.Lock()
    recorder._warnings_lock = threading.Lock()
    recorder._generation = 1
    recorder._closed = False
    recorder._cached_warnings = []
    recorder._first_frame = threading.Event()
    recorder._first_frame_latency_ms = 0.0
    recorder._start_attempts = 0
    recorder._last_capture_diagnostics = AudioCaptureDiagnostics()
    return recorder


def test_isolated_audio_forced_disposal_never_waits_for_queue_feeders():
    process = Mock()
    process.is_alive.side_effect = (True, True, False, False)
    requests = Mock()
    responses = Mock()

    IsolatedAudioRecorder._dispose_process(
        process,
        requests,
        responses,
        graceful=False,
    )

    process.terminate.assert_called_once_with()
    for channel in (requests, responses):
        channel.cancel_join_thread.assert_called_once_with()
        channel.close.assert_called_once_with()
        channel.join_thread.assert_not_called()


def test_app_startup_prepares_inactive_microphone_before_enabling_hotkeys(tmp_path):
    from voicepilot.app import WinsperApp

    events = []
    hud_messages = []

    class HUD:
        def start(self) -> None:
            events.append("hud")

        def show(self, *args) -> None:
            events.append(f"show:{args[0]}")
            hud_messages.append(args)

    class Hotkeys:
        def start(self) -> None:
            events.append("hotkeys")

    class Recorder:
        def warm_up(self) -> bool:
            events.append("audio")
            return True

    app = WinsperApp.__new__(WinsperApp)
    app.config = AppConfig()
    app.config.speech.preload_on_startup = True
    app.config_path = tmp_path / "config.yaml"
    app.hud = HUD()
    app.tray = Mock()
    app.tray.start.side_effect = lambda: events.append("tray")
    app.recorder = Recorder()
    app.history = Mock()
    app.history.prune.side_effect = lambda: events.append("history")
    app._stop_event = threading.Event()
    app._create_hotkeys = lambda: Hotkeys()
    app._write_runtime_state = lambda *_args: events.append("runtime")
    app._prepare_dictation_for_startup = lambda: events.append("dictation") or True
    app._queue_or_start_rewrite_preload = lambda: events.append("polish")
    app.shutdown = lambda: events.append("shutdown")

    app._stop_event.set()
    app.run()

    assert events.index("show:Preparing Winsper") < events.index("dictation")
    assert events.index("dictation") < events.index("audio")
    assert events.index("audio") < events.index("hotkeys")
    assert events.index("hotkeys") < events.index("show:Ready")
    assert events.index("hotkeys") < events.index("tray")
    assert events.index("hotkeys") < events.index("history")
    assert events.index("hotkeys") < events.index("polish")
    assert hud_messages == [
        ("Preparing Winsper", "Getting things ready", "preparing"),
        ("Ready", "Hold the hotkey to speak", "idle"),
    ]
    assert events[-1] == "shutdown"


def test_app_startup_preserves_console_hud_fallback_and_shutdown(tmp_path):
    from voicepilot.app import WinsperApp
    events = []

    class FailingHUD:
        def start(self) -> None:
            events.append("hud-failed")
            raise RuntimeError("Qt unavailable")

    class FallbackHUD:
        def start(self) -> None:
            events.append("fallback-started")

        def show(self, *_args) -> None:
            events.append("fallback-shown")

    app = WinsperApp.__new__(WinsperApp)
    app.config = AppConfig()
    app.config_path = tmp_path / "config.yaml"
    app.config.speech.preload_on_startup = False
    app.hud = FailingHUD()
    app.tray = Mock()
    app.history = Mock()
    app.recorder = Mock()
    app.recorder.warm_up.return_value = True
    app._stop_event = threading.Event()
    app._stop_event.set()
    app._create_hotkeys = Mock(return_value=Mock())
    app._write_runtime_state = Mock()
    app.shutdown = lambda: events.append("shutdown")

    with (
        patch("voicepilot.app.ConsoleHUD", FallbackHUD),
        patch("voicepilot.app.log_runtime_error"),
    ):
        app.run()

    assert events == ["hud-failed", "fallback-started", "fallback-shown", "shutdown"]
    app.hotkeys.start.assert_called_once_with()
    app.tray.start.assert_called_once_with()
    app.history.prune.assert_called_once_with()


def test_isolated_transcriber_foreground_transcription_preempts_background_preload():
    transcriber = IsolatedSpeechTranscriber(AppConfig().speech, [])
    preload_config = replace(transcriber.config, model="base.en")
    foreground_config = replace(transcriber.config, model="small.en")
    preload_started = threading.Event()
    transcription_sent = threading.Event()
    request_kinds: dict[str, str] = {}
    request_epochs: dict[str, int] = {}
    results = {}
    errors = []
    session = (Mock(), Mock(), Mock(), 1)

    def send(payload, *, request_epoch):
        request_kinds[payload["id"]] = payload["kind"]
        request_epochs[payload["id"]] = request_epoch
        if payload["kind"] == "warm_up_model":
            with transcriber._state_lock:
                transcriber._requests, transcriber._responses, transcriber._process, _ = session
            preload_started.set()
        else:
            transcription_sent.set()
        return session

    def receive(request_id, _session):
        if request_kinds[request_id] == "warm_up_model":
            while request_epochs[request_id] == transcriber._cancel_epoch:
                threading.Event().wait(0.005)
            raise SpeechWorkerInterrupted("preload worker replaced")
        return {"kind": "result", "text": "captured"}

    transcriber._send = send
    transcriber._receive = receive
    transcriber._dispose_process = Mock()

    def preload():
        try:
            results["preload"] = transcriber.preload_model(preload_config)
        except Exception as exc:
            errors.append(exc)

    def transcribe():
        try:
            results["transcription"] = transcriber.transcribe(Mock(), config=foreground_config)
        except Exception as exc:
            errors.append(exc)

    preload_thread = threading.Thread(target=preload, daemon=True)
    transcription_thread = threading.Thread(target=transcribe, daemon=True)
    preload_thread.start()
    assert preload_started.wait(1)
    transcription_thread.start()

    assert transcription_sent.wait(1)
    preload_thread.join(timeout=1)
    transcription_thread.join(timeout=1)

    assert not preload_thread.is_alive()
    assert not transcription_thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], SpeechWorkerInterrupted)
    assert results == {"transcription": "captured"}
    transcriber._dispose_process.assert_called_once()


def test_isolated_transcriber_foreground_reuses_same_runtime_preload():
    transcriber = IsolatedSpeechTranscriber(AppConfig().speech, [])
    preload_started = threading.Event()
    release_preload = threading.Event()
    transcription_sent = threading.Event()
    request_kinds: dict[str, str] = {}
    results = {}
    errors = []
    session = (Mock(), Mock(), Mock(), 1)

    def send(payload, **_kwargs):
        request_kinds[payload["id"]] = payload["kind"]
        if payload["kind"] == "warm_up_model":
            preload_started.set()
        else:
            transcription_sent.set()
        return session

    def receive(request_id, _session):
        if request_kinds[request_id] == "warm_up_model":
            assert release_preload.wait(1)
            return {"kind": "result", "text": ""}
        return {"kind": "result", "text": "captured"}

    transcriber._send = send
    transcriber._receive = receive
    transcriber._dispose_process = Mock()

    def preload():
        try:
            results["preload"] = transcriber.preload_model()
        except Exception as exc:
            errors.append(exc)

    def transcribe():
        try:
            results["transcription"] = transcriber.transcribe(Mock())
        except Exception as exc:
            errors.append(exc)

    preload_thread = threading.Thread(target=preload, daemon=True)
    transcription_thread = threading.Thread(target=transcribe, daemon=True)
    preload_thread.start()
    assert preload_started.wait(1)
    transcription_thread.start()

    assert not transcription_sent.wait(0.05)
    release_preload.set()
    preload_thread.join(timeout=1)
    transcription_thread.join(timeout=1)

    assert not errors
    assert results == {"preload": True, "transcription": "captured"}
    transcriber._dispose_process.assert_not_called()


def test_isolated_transcriber_background_preload_yields_to_queued_foreground_request():
    transcriber = IsolatedSpeechTranscriber(AppConfig().speech, [])
    foreground_started = threading.Event()
    transcription_sent = threading.Event()
    results = {}
    errors = []
    session = (Mock(), Mock(), Mock(), 1)
    transcriber._request_lock.acquire()

    def send(payload, **_kwargs):
        transcription_sent.set()
        return session

    transcriber._send = send
    transcriber._receive = Mock(return_value={"kind": "result", "text": "captured"})

    def transcribe():
        foreground_started.set()
        results["transcription"] = transcriber.transcribe(Mock())

    foreground_thread = threading.Thread(target=transcribe, daemon=True)
    foreground_thread.start()
    assert foreground_started.wait(1)
    while transcriber._foreground_waiters == 0:
        threading.Event().wait(0.005)

    try:
        transcriber.preload_model()
    except Exception as exc:
        errors.append(exc)
    finally:
        transcriber._request_lock.release()

    foreground_thread.join(timeout=1)
    assert not foreground_thread.is_alive()
    assert transcription_sent.is_set()
    assert results == {"transcription": "captured"}
    assert len(errors) == 1
    assert isinstance(errors[0], SpeechWorkerInterrupted)
    assert "yielded" in str(errors[0])


def test_isolated_transcriber_close_prevents_queued_preload_from_respawning():
    transcriber = IsolatedSpeechTranscriber(AppConfig().speech, [])
    errors = []
    started = threading.Event()
    transcriber._request_lock.acquire()

    def preload():
        started.set()
        try:
            transcriber.load_model()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=preload, daemon=True)
    thread.start()
    assert started.wait(1)
    transcriber.close()
    transcriber._request_lock.release()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert transcriber._process is None
    assert len(errors) == 1
    assert isinstance(errors[0], SpeechWorkerInterrupted)
    with pytest.raises(SpeechWorkerInterrupted, match="closed"):
        transcriber._ensure_process()


def test_isolated_transcriber_handles_process_handle_close_during_receive():
    transcriber = IsolatedSpeechTranscriber(AppConfig().speech, [])
    process = Mock()
    process.is_alive.side_effect = ValueError("process object is closed")
    transcriber._process = process
    transcriber._generation = 3
    session = (Mock(), Mock(), process, 3)

    with pytest.raises(SpeechWorkerInterrupted, match="closed"):
        transcriber._receive("request", session)


def test_isolated_transcriber_cancel_invalidates_request_queued_behind_preload():
    transcriber = IsolatedSpeechTranscriber(AppConfig().speech, [])
    errors = []
    transcriber._request_lock.acquire()

    def transcribe():
        try:
            transcriber.transcribe(Mock())
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=transcribe, daemon=True)
    thread.start()
    for _attempt in range(100):
        if transcriber._foreground_waiters:
            break
        threading.Event().wait(0.01)
    assert transcriber._foreground_waiters == 1

    transcriber.cancel()
    transcriber._request_lock.release()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert transcriber._process is None
    assert len(errors) == 1
    assert isinstance(errors[0], SpeechWorkerInterrupted)
    assert "cancelled before it started" in str(errors[0])


def test_async_stop_waits_for_slow_start_without_blocking_keyboard_input():
    start_entered = threading.Event()
    release_start = threading.Event()
    stop_called = threading.Event()

    def on_start(_mode: str) -> None:
        start_entered.set()
        release_start.wait(timeout=1)

    hotkeys = GlobalHoldHotkeys(
        "ctrl+space",
        "",
        "",
        on_start,
        lambda _mode: stop_called.set(),
        asynchronous_callbacks=True,
    )
    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("space", now=1.1)
    assert start_entered.wait(timeout=1)

    hotkeys._handle_release("space", now=1.2)
    assert not stop_called.wait(timeout=0.05)
    release_start.set()
    assert stop_called.wait(timeout=1)


def test_async_cancel_never_blocks_the_keyboard_callback_thread():
    cancel_entered = threading.Event()
    release_cancel = threading.Event()
    cancel_finished = threading.Event()
    callback_thread_ids = []

    def on_start(mode: str) -> None:
        if mode != "cancel":
            return
        callback_thread_ids.append(threading.get_ident())
        cancel_entered.set()
        release_cancel.wait(timeout=1)
        cancel_finished.set()

    hotkeys = GlobalHoldHotkeys(
        "ctrl+space",
        "",
        "",
        on_start,
        lambda _mode: None,
        cancel_combo="ctrl+win+esc",
        asynchronous_callbacks=True,
    )
    keyboard_thread_id = threading.get_ident()

    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("win", now=1.1)
    hotkeys._handle_press("esc", now=1.2)

    assert cancel_entered.wait(timeout=1)
    assert callback_thread_ids != [keyboard_thread_id]
    assert not cancel_finished.is_set()
    release_cancel.set()
    assert cancel_finished.wait(timeout=1)


def test_async_cancel_preserves_start_cancel_next_start_order():
    first_start_entered = threading.Event()
    release_first_start = threading.Event()
    cancel_entered = threading.Event()
    release_cancel = threading.Event()
    next_start_entered = threading.Event()
    events = []
    starts = 0

    def on_start(mode: str) -> None:
        nonlocal starts
        if mode == "dictate":
            starts += 1
            if starts == 1:
                events.append("first-start")
                first_start_entered.set()
                release_first_start.wait(timeout=1)
                events.append("first-start-done")
            else:
                events.append("next-start")
                next_start_entered.set()
            return
        events.append("cancel")
        cancel_entered.set()
        release_cancel.wait(timeout=1)
        events.append("cancel-done")

    hotkeys = GlobalHoldHotkeys(
        "ctrl+win+space",
        "",
        "",
        on_start,
        lambda _mode: None,
        cancel_combo="ctrl+win+esc",
        asynchronous_callbacks=True,
    )
    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("win", now=1.1)
    hotkeys._handle_press("space", now=1.2)
    assert first_start_entered.wait(timeout=1)

    hotkeys._handle_press("esc", now=1.3)
    hotkeys._handle_release("esc", now=1.31)
    hotkeys._handle_press("space", now=1.4)

    assert not cancel_entered.is_set()
    assert not next_start_entered.is_set()
    release_first_start.set()
    assert cancel_entered.wait(timeout=1)
    assert not next_start_entered.is_set()
    release_cancel.set()
    assert next_start_entered.wait(timeout=1)
    assert events == ["first-start", "first-start-done", "cancel", "cancel-done", "next-start"]


def test_elevated_registered_cancel_dispatches_off_wm_hotkey_thread():
    cancel_entered = threading.Event()
    release_cancel = threading.Event()
    cancel_finished = threading.Event()
    callback_thread_ids = []

    def on_start(mode: str) -> None:
        if mode == "cancel":
            callback_thread_ids.append(threading.get_ident())
            cancel_entered.set()
            release_cancel.wait(timeout=1)
            cancel_finished.set()

    hotkeys = GlobalHoldHotkeys(
        "ctrl+space",
        "",
        "",
        on_start,
        lambda _mode: None,
        cancel_combo="ctrl+win+esc",
        asynchronous_callbacks=True,
    )
    wm_hotkey_thread_id = threading.get_ident()

    with patch("voicepilot.hotkeys._foreground_target_is_elevated", return_value=True):
        hotkeys._on_registered_press("cancel")

    assert cancel_entered.wait(timeout=1)
    assert callback_thread_ids != [wm_hotkey_thread_id]
    release_cancel.set()
    assert cancel_finished.wait(timeout=1)


def test_hotkey_stop_invalidates_callbacks_queued_behind_active_start():
    start_entered = threading.Event()
    release_start = threading.Event()
    stop_called = threading.Event()

    def on_start(_mode: str) -> None:
        start_entered.set()
        release_start.wait(timeout=1)

    hotkeys = GlobalHoldHotkeys(
        "ctrl+space",
        "",
        "",
        on_start,
        lambda _mode: stop_called.set(),
        asynchronous_callbacks=True,
    )
    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("space", now=1.1)
    assert start_entered.wait(timeout=1)
    hotkeys._handle_release("space", now=1.2)

    hotkeys.stop()
    release_start.set()
    assert not stop_called.wait(timeout=0.1)
