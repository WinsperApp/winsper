from __future__ import annotations

import threading
import ctypes
from unittest.mock import Mock, patch

from voicepilot.app_lifecycle import ListenerLifecycleMixin
from voicepilot.config import AppConfig
from voicepilot.paste import ClipboardSnapshot, TextInserter, UiaSelectionProbe
from voicepilot.selection import SelectionResult, SelectionStatus
from voicepilot.selection_windows import _Input


def _selection_patches(probe: UiaSelectionProbe):
    return (
        patch("voicepilot.paste._target_is_elevated", return_value=False),
        patch("voicepilot.paste._target_is_current", return_value=True),
        patch("voicepilot.paste._probe_uia_selection", return_value=probe),
    )


def test_send_input_structure_matches_windows_abi():
    assert ctypes.sizeof(_Input) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


def test_selection_uses_uia_without_touching_clipboard():
    target, current, probe = _selection_patches(UiaSelectionProbe(True, "selected by accessibility"))
    with target, current, probe, patch("voicepilot.paste._clipboard_modules") as clipboard_modules:
        result = TextInserter(AppConfig().paste).read_selection(window_hwnd=42)

    assert (result.status, result.text, result.method) == (
        SelectionStatus.CAPTURED,
        "selected by accessibility",
        "uia",
    )
    clipboard_modules.assert_not_called()


def test_uia_confirmed_empty_selection_does_not_touch_clipboard():
    target, current, probe = _selection_patches(UiaSelectionProbe(True, ""))
    with target, current, probe, patch("voicepilot.paste._clipboard_modules") as clipboard_modules:
        result = TextInserter(AppConfig().paste).read_selection(window_hwnd=42)

    assert result.status is SelectionStatus.NO_SELECTION
    assert result.method == "uia"
    clipboard_modules.assert_not_called()


def test_unsupported_uia_control_falls_back_to_native_copy_shortcut():
    clipboard = Mock()
    clipboard.paste.return_value = "clipboard selection"
    snapshot = Mock(spec=ClipboardSnapshot)
    snapshot.complete = True
    target, current, probe = _selection_patches(UiaSelectionProbe(False))
    with (
        target,
        current,
        probe,
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, Mock())),
        patch("voicepilot.paste.ClipboardSnapshot.capture", return_value=snapshot),
        patch("voicepilot.paste._send_copy_message", return_value=False),
        patch("voicepilot.paste._send_copy_shortcut", return_value=True),
        patch("voicepilot.paste._clipboard_sequence_number", return_value=7),
    ):
        result = TextInserter(AppConfig().paste).read_selection(window_hwnd=42)

    assert (result.status, result.text, result.method) == (
        SelectionStatus.CAPTURED,
        "clipboard selection",
        "send_input",
    )
    snapshot.restore.assert_called_once_with()


def test_native_copy_message_precedes_keyboard_fallback():
    clipboard = Mock()
    clipboard.paste.return_value = "native selection"
    snapshot = Mock(spec=ClipboardSnapshot)
    snapshot.complete = True
    target, current, probe = _selection_patches(UiaSelectionProbe(False))
    with (
        target,
        current,
        probe,
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, Mock())),
        patch("voicepilot.paste.ClipboardSnapshot.capture", return_value=snapshot),
        patch("voicepilot.paste._send_copy_message", return_value=True),
        patch("voicepilot.paste._send_copy_shortcut") as shortcut,
        patch("voicepilot.paste._clipboard_sequence_number", return_value=9),
    ):
        result = TextInserter(AppConfig().paste).read_selection(window_hwnd=42)

    assert (result.text, result.method) == ("native selection", "wm_copy")
    shortcut.assert_not_called()
    snapshot.restore.assert_called_once_with()


def test_failed_native_copy_injection_is_not_misreported_as_no_selection():
    clipboard = Mock()
    clipboard.paste.return_value = ""
    snapshot = Mock(spec=ClipboardSnapshot)
    snapshot.complete = True
    target, current, probe = _selection_patches(UiaSelectionProbe(False))
    with (
        target,
        current,
        probe,
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, Mock())),
        patch("voicepilot.paste.ClipboardSnapshot.capture", return_value=snapshot),
        patch("voicepilot.paste._send_copy_message", return_value=False),
        patch("voicepilot.paste._send_copy_shortcut", return_value=False),
        patch("voicepilot.paste._clipboard_sequence_number", return_value=11),
    ):
        result = TextInserter(AppConfig().paste).read_selection(window_hwnd=42)

    assert result.status is SelectionStatus.UNAVAILABLE
    assert result.method == "send_input"
    assert "clean Copy shortcut" in result.reason


class _SelectionHarness(ListenerLifecycleMixin):
    pass


def _capture_harness(tmp_path) -> _SelectionHarness:
    harness = _SelectionHarness()
    harness._lock = threading.Lock()
    harness._polish_selection_captures = {}
    harness.inserter = Mock()
    harness.config_path = tmp_path / "config.yaml"
    return harness


def test_polish_selection_capture_snapshots_text_after_hotkey_release(tmp_path):
    harness = _capture_harness(tmp_path)
    harness.inserter.read_selection.return_value = SelectionResult.captured("basic")
    with patch("voicepilot.lifecycle_capture.POLISH_SELECTION_SETTLE_SECONDS", 0):
        harness._start_polish_selection_capture(42)
        result = harness._selection_for_polish_action(42)

    assert result == SelectionResult.captured("basic")
    harness.inserter.read_selection.assert_called_once()


def test_polish_selection_capture_fails_closed_while_hotkey_modifiers_remain_down(tmp_path):
    harness = _capture_harness(tmp_path)
    with (
        patch("voicepilot.lifecycle_capture.POLISH_SELECTION_SETTLE_SECONDS", 0),
        patch("voicepilot.lifecycle_capture._wait_for_hotkey_modifiers_release", return_value=False),
    ):
        harness._start_polish_selection_capture(43)
        result = harness._selection_for_polish_action(43)

    assert result.status is SelectionStatus.UNAVAILABLE
    assert result.method == "modifier_guard"
    harness.inserter.read_selection.assert_not_called()
