from __future__ import annotations

import os
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock

import pytest

from voicepilot.app_context import detect_browser_page, get_foreground_window_details, is_browser_process
from voicepilot.audio import AudioClip
from voicepilot.audio_factory import create_audio_recorder
from voicepilot.config import BrowserContextConfig, PasteConfig, load_config
from voicepilot.hotkeys import GlobalHoldHotkeys
from voicepilot.paste import ClipboardSnapshot, DeliveryStatus, TextInserter
from voicepilot.selection import SelectionStatus
from voicepilot.speed_lab import score_transcript
from voicepilot.transcribe import FasterWhisperTranscriber


pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(
        os.environ.get("WINSPER_REAL_TESTS") != "1",
        reason="Set WINSPER_REAL_TESTS=1 or run scripts/test-hardware.ps1.",
    ),
    pytest.mark.skipif(not sys.platform.startswith("win"), reason="Real integration tests require Windows."),
]


def _countdown(message: str, seconds: int = 3) -> None:
    print(f"\n{message}", flush=True)
    for remaining in range(seconds, 0, -1):
        print(f"  {remaining}...", flush=True)
        time.sleep(1)


def _activate_test_editor(editor, app, *, timeout_seconds: float = 3.0) -> bool:
    """Focus a Winsper-owned test field using real Windows input as fallback."""
    import ctypes
    from ctypes import wintypes

    from PySide6.QtTest import QTest

    hwnd = int(editor.winId())
    user32 = ctypes.windll.user32
    deadline = time.monotonic() + timeout_seconds
    clicked = False
    original_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_cursor))
    while time.monotonic() < deadline:
        editor.raise_()
        editor.activateWindow()
        editor.setFocus()
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if int(user32.GetForegroundWindow()) == hwnd and editor.hasFocus():
            return True
        if not clicked:
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                user32.SetCursorPos((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
                user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
                user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
                user32.SetCursorPos(original_cursor.x, original_cursor.y)
                clicked = True
        QTest.qWait(100)
        app.processEvents()
    return int(user32.GetForegroundWindow()) == hwnd and editor.hasFocus()


def _record_real_clip(message: str) -> AudioClip:
    config_path = Path(os.environ.get("WINSPER_TEST_CONFIG", "config.yaml"))
    app_config = load_config(config_path)
    audio_config = replace(app_config.audio, min_record_seconds=0.2)
    duration = float(os.environ.get("WINSPER_RECORD_SECONDS", "3"))
    recorder = create_audio_recorder(audio_config)
    _countdown(message)
    recorder.start()
    print(f"  Recording for {duration:.1f}s...", flush=True)
    try:
        time.sleep(duration)
        return recorder.stop()
    finally:
        recorder.close()


def test_real_microphone_captures_audible_audio() -> None:
    import numpy as np

    clip = _record_real_clip("Speak normally into the configured microphone.")
    peak = float(np.max(np.abs(clip.samples)))
    rms = float(np.sqrt(np.mean(np.square(clip.samples))))
    minimum_rms = float(os.environ.get("WINSPER_MIN_MIC_RMS", "0.0001"))

    print(f"  Captured {clip.duration_seconds:.2f}s; peak={peak:.5f}, rms={rms:.5f}", flush=True)
    assert len(clip.samples) > 0
    assert clip.duration_seconds >= 0.2
    assert peak > minimum_rms
    assert rms > minimum_rms


def test_real_microphone_repeated_starts_meet_release_gate() -> None:
    config_path = Path(os.environ.get("WINSPER_TEST_CONFIG", "config.yaml"))
    app_config = load_config(config_path)
    audio_config = replace(app_config.audio, min_record_seconds=0)
    cycles = int(os.environ.get("WINSPER_MIC_START_CYCLES", "12"))
    maximum_start_ms = float(os.environ.get("WINSPER_MAX_MIC_START_MS", "100"))
    maximum_first_frame_ms = float(os.environ.get("WINSPER_MAX_FIRST_FRAME_MS", "100"))
    idle_seconds = float(os.environ.get("WINSPER_MIC_IDLE_SECONDS", "0"))
    idle_between_cycles = float(os.environ.get("WINSPER_MIC_IDLE_BETWEEN_CYCLES_SECONDS", "0"))
    minimum_success_rate = float(os.environ.get("WINSPER_MIN_MIC_SUCCESS_RATE", "0.998"))
    recorder = create_audio_recorder(audio_config)
    timings: list[float] = []
    first_frame_timings: list[float] = []
    attempts: list[int] = []
    failures: list[str] = []

    try:
        assert recorder.warm_up()
        for index in range(cycles):
            if idle_between_cycles > 0 and index > 0:
                time.sleep(idle_between_cycles)
            try:
                first_frame_started_at = time.perf_counter()
                metrics = recorder.start()
                if not recorder.wait_for_first_frame(maximum_first_frame_ms / 1000):
                    raise AssertionError(
                        f"Microphone delivered no first packet within {maximum_first_frame_ms:.0f}ms."
                    )
                observed_first_frame_ms = (time.perf_counter() - first_frame_started_at) * 1000
                time.sleep(0.15)
                clip = recorder.stop()
                if clip.duration_seconds <= 0:
                    raise AssertionError("Microphone delivered an empty clip.")
                timings.append(metrics.stream_start_ms)
                first_frame_timings.append(observed_first_frame_ms)
                attempts.append(metrics.attempts)
            except Exception as exc:
                failures.append(f"cycle {index + 1}: {type(exc).__name__}: {exc}")
            time.sleep(0.05)
        if idle_seconds > 0:
            time.sleep(idle_seconds)
        resumed_started_at = time.perf_counter()
        resumed = recorder.start()
        assert recorder.wait_for_first_frame(maximum_first_frame_ms / 1000)
        resumed_first_frame_ms = (time.perf_counter() - resumed_started_at) * 1000
        time.sleep(0.15)
        assert recorder.stop().duration_seconds > 0
    finally:
        recorder.close()

    if len(timings) < 2:
        pytest.fail(f"Too few successful microphone cycles: {failures[:3]}")
    start_p95 = statistics.quantiles(timings, n=100, method="inclusive")[94]
    first_frame_p95 = statistics.quantiles(first_frame_timings, n=100, method="inclusive")[94]
    success_rate = len(timings) / cycles
    recovery_rate = sum(attempt <= 2 for attempt in attempts) / max(1, len(attempts))
    outliers = [round(value, 1) for value in timings if value >= maximum_start_ms]
    print(
        "  Microphone certification: "
        f"{len(timings)}/{cycles} successful; start p95={start_p95:.1f}ms; "
        f"first-frame p95={first_frame_p95:.1f}ms; "
        f"start max={max(timings):.1f}ms; first-frame max={max(first_frame_timings):.1f}ms; "
        f"idle first-frame={resumed_first_frame_ms:.1f}ms; "
        f"outliers={outliers[:10]}; failures={failures[:3]}",
        flush=True,
    )
    assert success_rate >= minimum_success_rate
    assert recovery_rate == 1.0
    assert start_p95 < maximum_start_ms
    assert first_frame_p95 < maximum_first_frame_ms
    assert resumed.attempts <= 2


def test_real_clipboard_paste_and_restore() -> None:
    import pyperclip
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit

    app = QApplication.instance() or QApplication([])
    editor = QLineEdit()
    inserted = f"Winsper clipboard integration {time.time_ns()}"
    previous = ClipboardSnapshot.capture()
    if not previous.complete:
        pytest.skip("Current clipboard contains an unsupported format and cannot be restored safely.")
    sentinel = f"Winsper clipboard sentinel {time.time_ns()}"
    pyperclip.copy(sentinel)

    try:
        editor.resize(640, 60)
        editor.show()
        app.processEvents()
        hwnd = int(editor.winId())
        if not _activate_test_editor(editor, app):
            pytest.skip("Interactive Windows desktop did not grant the test field foreground focus.")

        result = TextInserter(PasteConfig(restore_clipboard=True, paste_delay_ms=150)).paste_text(
            inserted,
            window_hwnd=hwnd,
        )
        QTest.qWait(300)
        app.processEvents()

        assert result.inserted
        assert editor.text() == inserted
        assert pyperclip.paste() == sentinel
    finally:
        previous.restore()
        editor.close()


def test_real_rich_clipboard_paste_and_restore() -> None:
    from PySide6.QtCore import QMimeData
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit

    app = QApplication.instance() or QApplication([])
    clipboard = app.clipboard()
    previous = ClipboardSnapshot.capture()
    if not previous.complete:
        pytest.skip("Current clipboard contains an unsupported format and cannot be restored safely.")
    editor = QLineEdit()
    sentinel_text = "Winsper rich clipboard sentinel"
    sentinel_html = "<p><strong>Winsper</strong> rich clipboard sentinel</p>"
    mime = QMimeData()
    mime.setText(sentinel_text)
    mime.setHtml(sentinel_html)
    clipboard.setMimeData(mime)

    try:
        editor.resize(640, 60)
        editor.show()
        app.processEvents()
        hwnd = int(editor.winId())
        if not _activate_test_editor(editor, app):
            pytest.skip("Interactive Windows desktop did not grant the test field foreground focus.")

        result = TextInserter(PasteConfig(restore_clipboard=True, paste_delay_ms=150)).paste_text(
            "Winsper rich delivery",
            window_hwnd=hwnd,
        )
        QTest.qWait(300)
        app.processEvents()
        restored = clipboard.mimeData()

        assert result.inserted
        assert editor.text() == "Winsper rich delivery"
        assert restored.text() == sentinel_text
        assert restored.hasHtml()
        assert "<strong>Winsper</strong>" in restored.html()
    finally:
        previous.restore()
        editor.close()


def test_real_target_change_never_pastes_into_new_window() -> None:
    import pyperclip
    from PySide6.QtWidgets import QApplication, QLineEdit

    app = QApplication.instance() or QApplication([])
    original_target = QLineEdit("original target")
    new_target = QLineEdit("new target")
    previous = ClipboardSnapshot.capture()
    if not previous.complete:
        pytest.skip("Current clipboard contains an unsupported format and cannot be restored safely.")
    try:
        original_target.resize(640, 60)
        original_target.show()
        app.processEvents()
        original_hwnd = int(original_target.winId())
        assert _activate_test_editor(original_target, app)

        new_target.resize(640, 60)
        new_target.show()
        app.processEvents()
        assert _activate_test_editor(new_target, app)

        result = TextInserter(PasteConfig(restore_clipboard=False)).paste_text(
            "recoverable result",
            window_hwnd=original_hwnd,
        )

        assert result.delivery is DeliveryStatus.TARGET_CHANGED
        assert original_target.text() == "original target"
        assert new_target.text() == "new target"
        assert pyperclip.paste() == "recoverable result"
    finally:
        previous.restore()
        original_target.close()
        new_target.close()


def test_real_polish_selection_snapshot_captures_focused_text(tmp_path) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QLineEdit

    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    class Harness(ListenerLifecycleMixin):
        pass

    app = QApplication.instance() or QApplication([])
    editor = QLineEdit("basic")
    previous = ClipboardSnapshot.capture()
    if not previous.complete:
        pytest.skip("Current clipboard contains an unsupported format and cannot be restored safely.")
    try:
        editor.resize(640, 60)
        editor.show()
        app.processEvents()
        if not _activate_test_editor(editor, app):
            pytest.skip("Interactive Windows desktop did not grant the test field foreground focus.")

        editor.selectAll()
        app.processEvents()
        harness = Harness()
        harness._lock = Lock()
        harness._polish_selection_captures = {}
        harness.config_path = tmp_path / "config.yaml"
        harness.inserter = TextInserter(PasteConfig(restore_clipboard=True, copy_delay_ms=150))
        harness._start_polish_selection_capture(1)

        # QLineEdit belongs to this test process. Run a real nested event loop
        # while the background capture thread sends Ctrl+C, matching a target
        # app that remains responsive during production capture.
        capture = harness._polish_selection_captures[1]
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(20)
        poll.timeout.connect(lambda: loop.quit() if capture.ready.is_set() else None)
        poll.start()
        QTimer.singleShot(1500, loop.quit)
        loop.exec()
        poll.stop()

        selection = harness._selection_for_polish_action(1)
        assert selection.status is SelectionStatus.CAPTURED
        assert selection.text == "basic"
        assert editor.selectedText() == "basic"
    finally:
        previous.restore()
        editor.close()


def test_real_registered_hotkey_receives_system_events() -> None:
    from pynput import keyboard

    raw_seen = Event()
    started = Event()
    stopped = Event()
    modes: list[tuple[str, str]] = []
    raw_listener = keyboard.Listener(on_press=lambda key: raw_seen.set())
    hotkeys = GlobalHoldHotkeys(
        dictate_combo="ctrl+alt+9",
        polish_combo="",
        rewrite_combo="",
        on_start=lambda mode: (modes.append(("start", mode)), started.set()),
        on_stop=lambda mode: (modes.append(("stop", mode)), stopped.set()),
    )
    controller = keyboard.Controller()
    keys = [keyboard.Key.ctrl_l, keyboard.Key.alt_l, "9"]

    raw_listener.start()
    hotkeys.start()
    try:
        if hasattr(raw_listener, "wait"):
            raw_listener.wait()
        time.sleep(0.2)
        controller.press("8")
        controller.release("8")
        if not raw_seen.wait(1.0):
            pytest.skip("Interactive Windows desktop did not deliver synthetic global keyboard events.")

        for key in keys:
            controller.press(key)
        assert started.wait(2), "The registered Windows hotkey did not receive the press."
        for key in reversed(keys):
            controller.release(key)
        assert stopped.wait(2), "The Windows release monitor did not receive the release."
        assert modes == [("start", "dictate"), ("stop", "dictate")]
    finally:
        for key in reversed(keys):
            try:
                controller.release(key)
            except Exception:
                pass
        hotkeys.stop()
        raw_listener.stop()
        raw_listener.join(timeout=1.0)


def test_real_microphone_to_local_stt() -> None:
    expected = os.environ.get("WINSPER_EXPECTED_PHRASE", "Winsper real speech test")
    clip = _record_real_clip(f'Say clearly: "{expected}"')
    config_path = Path(os.environ.get("WINSPER_TEST_CONFIG", "config.yaml"))
    app_config = load_config(config_path)
    model = os.environ.get("WINSPER_TEST_MODEL", app_config.speech.model)
    speech_config = replace(app_config.speech, model=model, language="en")

    transcript = FasterWhisperTranscriber(speech_config, app_config.vocabulary).transcribe(clip)
    score = score_transcript(transcript, expected)
    minimum_similarity = float(os.environ.get("WINSPER_MIN_STT_SIMILARITY", "0.55"))
    print(f'  Transcript: "{transcript}"', flush=True)

    assert transcript.strip()
    assert score is not None
    assert score.similarity >= minimum_similarity


def test_real_browser_foreground_uia_address_bar() -> None:
    expected = os.environ.get("WINSPER_EXPECTED_BROWSER_DOMAIN", "").strip().lower()
    if not expected:
        pytest.skip("Set WINSPER_EXPECTED_BROWSER_DOMAIN to the domain open in the browser.")

    _countdown(f"Focus a browser tab whose address contains: {expected}", seconds=5)
    window = get_foreground_window_details()
    config = BrowserContextConfig(enabled=True, timeout_ms=1000)
    page = detect_browser_page(window, config)

    print(
        f"  Foreground process={window.process_name!r}, title={window.window_title!r}, domain={page.domain!r}",
        flush=True,
    )
    assert is_browser_process(window.process_name, config.browser_processes)
    assert page.domain
    assert page.domain == expected or page.domain.endswith(f".{expected}")
