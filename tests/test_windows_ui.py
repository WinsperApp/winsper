from types import SimpleNamespace
from unittest.mock import patch

import pytest

from voicepilot.windows_ui import (
    DWMWA_BORDER_COLOR,
    DWMWA_CAPTION_COLOR,
    DWMWA_TEXT_COLOR,
    DWMWA_USE_IMMERSIVE_DARK_MODE,
    DWMWA_WINDOW_CORNER_PREFERENCE,
    DWMWCP_ROUND,
    PREFERRED_APP_MODE_FORCE_DARK,
    PREFERRED_APP_MODE_FORCE_LIGHT,
    apply_native_window_style,
    animate_progress_value,
    colorref,
    prefers_high_contrast,
    prefers_reduced_motion,
    preferred_app_mode,
)
from voicepilot.theme import HIGH_CONTRAST_DARK, HIGH_CONTRAST_LIGHT, get_palette


def test_colorref_uses_windows_bgr_layout():
    assert colorref("#123456") == 0x563412
    with pytest.raises(ValueError):
        colorref("#123")


def test_native_menu_mode_follows_explicit_theme():
    assert preferred_app_mode("dark") == PREFERRED_APP_MODE_FORCE_DARK
    assert preferred_app_mode("light") == PREFERRED_APP_MODE_FORCE_LIGHT


def test_reduced_motion_environment_override(monkeypatch):
    monkeypatch.setenv("WINSPER_REDUCE_MOTION", "true")
    prefers_reduced_motion.cache_clear()
    assert prefers_reduced_motion()
    monkeypatch.setenv("WINSPER_REDUCE_MOTION", "false")
    prefers_reduced_motion.cache_clear()
    assert not prefers_reduced_motion()
    prefers_reduced_motion.cache_clear()


def test_high_contrast_environment_override_selects_accessible_palette(monkeypatch):
    monkeypatch.setenv("WINSPER_HIGH_CONTRAST", "true")
    prefers_high_contrast.cache_clear()
    assert prefers_high_contrast()
    assert get_palette("dark") == HIGH_CONTRAST_DARK
    assert get_palette("light") == HIGH_CONTRAST_LIGHT
    monkeypatch.setenv("WINSPER_HIGH_CONTRAST", "false")
    prefers_high_contrast.cache_clear()
    assert not prefers_high_contrast()
    prefers_high_contrast.cache_clear()


def test_native_style_preserves_frame_and_sets_dwm_attributes():
    window = SimpleNamespace(winId=lambda: 99)
    palette = SimpleNamespace(
        mode="dark",
        border="#112233",
        bg="#010203",
        text="#f0e0d0",
    )
    calls = []

    def record(_hwnd, attribute, value):
        calls.append((attribute, value))
        return True

    with (
        patch("voicepilot.windows_ui.sys.platform", "win32"),
        patch("voicepilot.windows_ui.prefers_high_contrast", return_value=False),
        patch("voicepilot.windows_ui._set_dwm_attribute", side_effect=record),
    ):
        assert apply_native_window_style(window, palette)

    assert (DWMWA_USE_IMMERSIVE_DARK_MODE, 1) in calls
    assert (DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND) in calls
    assert (DWMWA_BORDER_COLOR, colorref(palette.border)) in calls
    assert (DWMWA_CAPTION_COLOR, colorref(palette.bg)) in calls
    assert (DWMWA_TEXT_COLOR, colorref(palette.text)) in calls


def test_native_style_does_not_override_high_contrast_frame_colors():
    window = SimpleNamespace(winId=lambda: 99)
    palette = SimpleNamespace(mode="dark", border="#112233", bg="#010203", text="#f0e0d0")
    calls = []

    with (
        patch("voicepilot.windows_ui.sys.platform", "win32"),
        patch("voicepilot.windows_ui.prefers_high_contrast", return_value=True),
        patch(
            "voicepilot.windows_ui._set_dwm_attribute",
            side_effect=lambda _hwnd, attribute, value: calls.append((attribute, value)) or True,
        ),
    ):
        assert apply_native_window_style(window, palette)

    assert calls == [(DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)]


def test_progress_updates_immediately_with_reduced_motion():
    progress = SimpleNamespace(
        minimum=lambda: 0,
        maximum=lambda: 100,
        setValue=lambda value: setattr(progress, "value_set", value),
    )
    with patch("voicepilot.windows_ui.motion_enabled", return_value=False):
        animate_progress_value(progress, 130)
    assert progress.value_set == 100
