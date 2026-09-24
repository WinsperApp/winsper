from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from voicepilot.config import PasteConfig
from voicepilot.paste import DeliveryStatus, TextInserter, _clipboard_format_is_safe, _open_clipboard
from voicepilot.selection import SelectionStatus


class FakeClipboard:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def copy(self, text: str) -> None:
        self.text = text

    def paste(self) -> str:
        return self.text


class FakeAutomation:
    PAUSE = 0.0

    def __init__(self) -> None:
        self.hotkeys: list[tuple[str, ...]] = []
        self.keys: list[str] = []

    def hotkey(self, *keys: str) -> None:
        self.hotkeys.append(tuple(keys))

    def press(self, key: str, **_kwargs) -> None:
        self.keys.append(key)


@pytest.mark.parametrize(
    "text",
    [
        "Plain multiline\nsecond paragraph\n\nlast line",
        "हिन्दी और English",
        "مرحبا بالعالم",
        "Emoji 👋🏽 · café · naïve",
        "Column one\tColumn two",
    ],
)
def test_unicode_multiline_and_rtl_paste_restore_original_clipboard(text: str):
    clipboard = FakeClipboard("original clipboard")
    automation = FakeAutomation()
    config = PasteConfig(restore_clipboard=True, restore_delay_ms=0, paste_delay_ms=0)

    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, automation)),
        patch("voicepilot.paste._is_windows", return_value=False),
        patch("voicepilot.paste._pump_local_qt_events", return_value=False),
    ):
        result = TextInserter(config).paste_text(text)

    assert result.delivery is DeliveryStatus.SENT
    assert result.verified is False
    assert automation.hotkeys == [("ctrl", "v")]
    assert clipboard.text == "original clipboard"


def test_focus_change_after_copy_never_sends_paste_and_keeps_recovery_copy():
    clipboard = FakeClipboard("original")
    automation = FakeAutomation()
    config = PasteConfig(restore_clipboard=False, paste_delay_ms=0)

    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, automation)),
        patch("voicepilot.paste._target_is_elevated", return_value=False),
        patch("voicepilot.paste._target_is_current", side_effect=[True, True, False]),
    ):
        result = TextInserter(config).paste_text("recoverable result", window_hwnd=42)

    assert result.delivery is DeliveryStatus.TARGET_CHANGED
    assert result.copied
    assert clipboard.text == "recoverable result"
    assert automation.hotkeys == []


def test_clipboard_restore_failure_keeps_sent_result_truthful_and_recoverable():
    clipboard = FakeClipboard("original")
    automation = FakeAutomation()

    def fail_restore() -> None:
        raise OSError("clipboard busy")

    snapshot = SimpleNamespace(complete=True, restore=fail_restore)

    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, automation)),
        patch("voicepilot.paste.ClipboardSnapshot.capture", return_value=snapshot),
        patch("voicepilot.paste._clipboard_sequence_number", return_value=11),
        patch("voicepilot.paste._pump_local_qt_events", return_value=False),
    ):
        result = TextInserter(
            PasteConfig(restore_clipboard=True, restore_delay_ms=0, paste_delay_ms=0)
        ).paste_text("recoverable result")

    assert result.delivery is DeliveryStatus.SENT
    assert result.sent and result.copied
    assert "could not be restored" in result.reason
    assert clipboard.text == "recoverable result"


def test_selection_focus_change_before_copy_shortcut_restores_clipboard():
    clipboard = FakeClipboard("original")
    automation = FakeAutomation()
    snapshot = SimpleNamespace(complete=True, restore=lambda: clipboard.copy("original"))

    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, automation)),
        patch("voicepilot.paste.ClipboardSnapshot.capture", return_value=snapshot),
        patch("voicepilot.paste._target_is_elevated", return_value=False),
        patch("voicepilot.paste._target_is_current", side_effect=[True, True, True, False]),
        patch("voicepilot.paste._clipboard_sequence_number", return_value=10),
    ):
        result = TextInserter(PasteConfig(restore_clipboard=False)).read_selection(window_hwnd=42)

    assert result.status is SelectionStatus.TARGET_CHANGED
    assert automation.hotkeys == []
    assert clipboard.text == "original"


def test_insert_below_focus_change_copies_result_without_keypress():
    clipboard = FakeClipboard("original")
    automation = FakeAutomation()

    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, automation)),
        patch("voicepilot.paste._target_is_elevated", return_value=False),
        patch("voicepilot.paste._target_is_current", return_value=False),
    ):
        result = TextInserter(PasteConfig()).insert_below_selection("replacement", window_hwnd=42)

    assert result.delivery is DeliveryStatus.TARGET_CHANGED
    assert clipboard.text == "replacement"
    assert automation.keys == []


@pytest.mark.parametrize(
    ("process_name", "window_title"),
    [
        ("EXCEL.EXE", "Budget.xlsx - Excel"),
        ("chrome.exe", "Quarterly plan - Google Sheets"),
    ],
)
def test_insert_below_spreadsheet_copies_without_moving_cells(process_name: str, window_title: str):
    clipboard = FakeClipboard("original")
    automation = FakeAutomation()

    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, automation)),
        patch("voicepilot.paste._target_is_elevated", return_value=False),
        patch("voicepilot.paste._target_is_current", return_value=True),
    ):
        result = TextInserter(PasteConfig()).insert_below_selection(
            "replacement",
            process_name=process_name,
            window_title=window_title,
            window_hwnd=42,
        )

    assert result.delivery is DeliveryStatus.COPIED
    assert "not safe in spreadsheets" in result.reason
    assert clipboard.text == "replacement"
    assert automation.keys == []
    assert automation.hotkeys == []


def test_insert_below_uses_explicit_browser_destination_when_title_is_ambiguous():
    clipboard = FakeClipboard("original")
    automation = FakeAutomation()

    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, automation)),
        patch("voicepilot.paste._target_is_elevated", return_value=False),
        patch("voicepilot.paste._target_is_current", return_value=True),
    ):
        result = TextInserter(PasteConfig()).insert_below_selection(
            "replacement",
            process_name="chrome.exe",
            window_title="Quarterly plan",
            window_hwnd=42,
            destination_kind="spreadsheet",
        )

    assert result.delivery is DeliveryStatus.COPIED
    assert automation.keys == []


def test_clipboard_open_retry_outlasts_old_two_hundred_millisecond_limit():
    class User32:
        attempts = 0

        def OpenClipboard(self, _owner):
            self.attempts += 1
            return self.attempts == 12

    user32 = User32()
    with patch("voicepilot.paste.time.sleep"):
        _open_clipboard(user32)

    assert user32.attempts == 12


def test_clipboard_open_retry_stops_at_deadline():
    class User32:
        attempts = 0

        def OpenClipboard(self, _owner):
            self.attempts += 1
            return False

    user32 = User32()
    with patch("voicepilot.paste.time.monotonic", side_effect=[10.0, 10.6]):
        with pytest.raises(OSError, match="clipboard is busy"):
            _open_clipboard(user32)

    assert user32.attempts == 1


def test_thousand_simulated_insertions_have_truthful_sent_outcomes():
    clipboard = FakeClipboard()
    automation = FakeAutomation()
    inserter = TextInserter(PasteConfig(restore_clipboard=False, paste_delay_ms=0))

    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, automation)),
        patch("voicepilot.paste._target_is_current", return_value=True),
    ):
        results = [inserter.paste_text(f"result {index}") for index in range(1_000)]

    assert all(result.delivery is DeliveryStatus.SENT for result in results)
    assert all(not result.verified for result in results)
    assert len(automation.hotkeys) == 1_000
    assert clipboard.text == "result 999"


@pytest.mark.parametrize("name", ["HTML Format", "Rich Text Format", "PNG", "text/rtf"])
def test_supported_rich_clipboard_formats_are_explicitly_allowlisted(name: str):
    class User32:
        @staticmethod
        def GetClipboardFormatNameW(_format_id, buffer, _length):
            buffer.value = name
            return len(name)

    assert _clipboard_format_is_safe(User32(), 0xC123)


def test_unknown_rich_clipboard_format_fails_closed():
    class User32:
        @staticmethod
        def GetClipboardFormatNameW(_format_id, buffer, _length):
            buffer.value = "Untrusted App Object"
            return len(buffer.value)

    assert not _clipboard_format_is_safe(User32(), 0xC123)
