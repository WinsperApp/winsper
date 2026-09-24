from unittest.mock import patch

from voicepilot.app_context import ForegroundContext, WindowInfo
from voicepilot.app_pipeline import DictationPipelineMixin
from voicepilot.config import ProfileStyle


def test_target_guard_rejects_focus_change():
    context = ForegroundContext(
        process_name="notepad.exe",
        window_title="Notes",
        profile_name="general",
        profile=ProfileStyle(label="General"),
        window_hwnd=100,
    )
    with patch(
        "voicepilot.app_pipeline.get_foreground_window_details",
        return_value=WindowInfo(hwnd=100, process_name="notepad.exe", window_title="Notes"),
    ):
        assert DictationPipelineMixin._target_is_current(context)
    with patch(
        "voicepilot.app_pipeline.get_foreground_window_details",
        return_value=WindowInfo(hwnd=200, process_name="chrome.exe", window_title="Browser"),
    ):
        assert not DictationPipelineMixin._target_is_current(context)
