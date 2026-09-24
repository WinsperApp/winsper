from __future__ import annotations

import os

import pytest

from voicepilot.config import AppConfig, load_config, save_config


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def make_window(tmp_path, config: AppConfig | None = None):
    from voicepilot.onboarding_qt import OnboardingWindow

    path = tmp_path / "config.yaml"
    save_config(config or AppConfig(), path)
    return path, OnboardingWindow(path)


def test_first_step_blocks_a_dead_end_without_speech_support(tmp_path, qt_app, monkeypatch):
    path, window = make_window(tmp_path)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: False)
    window.index = 0
    window._refresh()

    assert not window.next_button.isEnabled()
    window._next()
    assert window.index == 0
    assert not load_config(path).onboarding.completed
    window.close()
    qt_app.processEvents()


def test_finish_cannot_claim_ready_without_speech_support(tmp_path, qt_app, monkeypatch):
    path, window = make_window(tmp_path)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: False)
    window.index = 4
    window._refresh()

    assert window.finish_title.text() == "Speech support still needed"
    assert not window.finish_button.isEnabled()
    window._finish()
    assert window.index == 0
    assert not load_config(path).onboarding.completed
    window.close()
    qt_app.processEvents()


def test_reopened_setup_preserves_an_existing_polish_provider(tmp_path, qt_app):
    config = AppConfig()
    config.onboarding.started_at = "2026-08-01T10:00:00+00:00"
    config.rewrite.provider = "ollama"
    config.rewrite.model = "owner/custom-model"
    path, window = make_window(tmp_path, config)

    assert window._persist_progress()
    saved = load_config(path)
    assert saved.rewrite.provider == "ollama"
    assert saved.rewrite.model == "owner/custom-model"
    window.close()
    qt_app.processEvents()


def test_cancel_controls_clear_pause_and_request_cleanup(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    window.download_running = True
    window.download_paused = True
    window.download_pause_event.set()
    window._cancel_speech_download()
    assert window.download_cancel_event.is_set()
    assert not window.download_pause_event.is_set()

    window.polish_setup_running = True
    window.polish_setup_paused = True
    window.polish_setup_pause_event.set()
    window._cancel_polish_setup()
    assert window.polish_setup_cancel_event.is_set()
    assert not window.polish_setup_pause_event.is_set()
    window.download_running = False
    window.polish_setup_running = False
    window.close()
    qt_app.processEvents()

def test_onboarding_hud_style_uses_settings_picker_and_persists(tmp_path, qt_app):
    path, window = make_window(tmp_path)
    assert [window.hud_style_combo.itemText(index) for index in range(window.hud_style_combo.count())] == [
        "Full HUD",
        "Compact HUD",
    ]
    full_index = window.hud_style_combo.findData("standard")
    window.hud_style_combo.setCurrentIndex(full_index)
    assert window._preview_config().hud.mode == "standard"
    assert window._persist_progress()
    window.close()
    qt_app.processEvents()
    assert load_config(path).hud.mode == "standard"


def test_onboarding_brand_mark_is_rendered_once_at_native_size(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    assert window.brand_logo.size().width() == 36
    assert window.brand_logo.size().height() == 36
    assert window.brand_logo.pixmap().width() == 36
    assert window.brand_logo.pixmap().height() == 36
    window.close()
    qt_app.processEvents()
