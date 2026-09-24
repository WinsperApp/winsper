from __future__ import annotations

import os

import pytest

from voicepilot.config import AppConfig, load_config, save_config


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def make_window(tmp_path, *, config: AppConfig | None = None):
    from voicepilot.onboarding_qt import OnboardingWindow

    path = tmp_path / "config.yaml"
    save_config(config or AppConfig(), path)
    return path, OnboardingWindow(path)


def close_window(window, app) -> None:
    window.close()
    app.processEvents()


def test_onboarding_is_human_readable_keyboard_ready_and_scroll_safe(tmp_path, qt_app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea

    _path, window = make_window(tmp_path)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: True)
    window._refresh()
    assert window.stack.count() == 5
    assert len(window.step_labels) == 5
    assert all(isinstance(window.stack.widget(index), QScrollArea) for index in range(window.stack.count()))
    assert all(
        window.stack.widget(index).horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        for index in range(window.stack.count())
    )

    labels = [label.text() for label in window.window.findChildren(QLabel)]
    buttons = [button.text() for button in window.window.findChildren(QPushButton)]
    visible_copy = "\n".join([*labels, *buttons]).casefold()
    for forbidden in (
        "ramble",
        "float16",
        "int8",
        "parakeet-tdt-0.6b",
        "large-v3",
        "llama",
        "ollama",
        "cuda",
        "runtime",
        "quantization",
        "hugging face",
        "no setup button",
        "actual global shortcut",
        "same dictation model",
        "setup test",
    ):
        assert forbidden not in visible_copy
    assert "dictate" in visible_copy
    assert "which language do you speak" in visible_copy
    assert "dictate something now" in visible_copy
    assert "launch winsper" in visible_copy
    assert "free trial" not in visible_copy
    assert "purchase" not in visible_copy
    for removed_copy in (
        "speech stays on this pc",
        "setup choices stay on this pc",
        "private speech processing",
        "private dictation setup",
    ):
        assert removed_copy not in visible_copy
    assert "exit setup" in visible_copy
    assert window.next_button.isDefault()
    assert window.language_combo.accessibleName()
    close_window(window, qt_app)


def test_onboarding_resumes_last_step_and_saved_choices(tmp_path, qt_app):
    path, window = make_window(tmp_path)
    window.index = 2
    hindi = window.language_combo.findData("hi")
    assert hindi >= 0
    window.language_combo.setCurrentIndex(hindi)
    precise = next(button for button in window.speed_group.buttons() if button.property("profile_id") == "precise")
    precise.setChecked(True)
    assert window._persist_progress()
    close_window(window, qt_app)

    saved = load_config(path)
    assert saved.onboarding.completed is False
    assert saved.onboarding.current_step == 2
    assert saved.onboarding.quality_profile == "precise"
    assert saved.speech.language == "hi"

    from voicepilot.onboarding_qt import OnboardingWindow

    resumed = OnboardingWindow(path)
    assert resumed.index == 2
    assert resumed.language_combo.currentData() == "hi"
    assert resumed.speed_group.checkedButton().property("profile_id") == "precise"
    close_window(resumed, qt_app)


def test_brand_new_setup_starts_with_fast_dictation_and_polish(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    assert window.speed_group.checkedButton().property("profile_id") == "instant"
    assert window.recommended_polish_model.tier == "fast"
    close_window(window, qt_app)

def test_reopening_completed_setup_does_not_make_it_incomplete(tmp_path, qt_app):
    config = AppConfig()
    config.onboarding.completed = True
    config.onboarding.completed_at = "2026-07-13T10:00:00+00:00"
    path, window = make_window(tmp_path, config=config)
    assert window.index == 0
    window.index = 2
    close_window(window, qt_app)
    saved = load_config(path)
    assert saved.onboarding.completed is True
    assert saved.onboarding.completed_at == "2026-07-13T10:00:00+00:00"


def test_language_and_quality_drive_the_download_target(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    hindi = window.language_combo.findData("hi")
    window.language_combo.setCurrentIndex(hindi)
    window._refresh_model_status()
    assert not window.recommended.model.endswith(".en")
    requested: list[str] = []
    window._launch_download = requested.append
    window._download_selected_speech_support()
    assert requested == [window.recommended.model]
    assert "download" in window.model_download_button.text().casefold() or not window.model_download_button.isEnabled()
    close_window(window, qt_app)


def test_download_failure_is_recoverable_and_keeps_choices(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    window.download_running = True
    window.download_events.put(("error", "Check your internet connection, then try again."))
    window._poll_download()
    assert window.download_running is False
    assert window.model_download_button.isEnabled()
    assert window.model_download_button.text() == "Try download again"
    assert "download failed" in window.model_status.text().casefold()
    close_window(window, qt_app)


def test_stale_dictation_result_cannot_overwrite_a_new_test(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    window.active_dictation_test_generation = 2
    window.dictation_test_running = True
    window.dictation_status.setText("Current test")
    window.dictation_test_events.put((1, "error", "old failure"))
    window._poll_dictation_test()
    assert window.dictation_test_running is True
    assert window.dictation_status.text() == "Current test"
    close_window(window, qt_app)


def test_optional_polish_can_be_skipped_without_installing_anything(tmp_path, qt_app, monkeypatch):
    import voicepilot.onboarding_downloads as onboarding_tests

    calls: list[str] = []
    monkeypatch.setattr(onboarding_tests, "install_runtime", lambda *_args, **_kwargs: calls.append("runtime"))
    monkeypatch.setattr(onboarding_tests, "install_polish_model", lambda *_args, **_kwargs: calls.append("model"))
    path, window = make_window(tmp_path)
    window._skip_polish_setup()
    assert calls == []
    saved = load_config(path)
    assert saved.onboarding.polish_skipped is True
    assert saved.dictation.polish_enabled is False
    assert window.polish_setup_status.text() == "Polish skipped. Dictation is ready."
    close_window(window, qt_app)


def test_optional_polish_setup_combines_runtime_and_model_download(tmp_path, qt_app, monkeypatch):
    import voicepilot.onboarding_downloads as onboarding_tests
    from voicepilot.ai_catalog import RuntimeBundle
    from voicepilot.ai_runtime import RuntimeProgress

    accelerated = RuntimeBundle("test-gpu", "vulkan", "x64", ())
    baseline = RuntimeBundle("test-cpu", "cpu", "x64", ())
    state = {"runtime": False, "model": False}
    calls: list[str] = []

    monkeypatch.setattr(
        onboarding_tests,
        "runtime_candidates",
        lambda _hardware: [accelerated, baseline],
    )
    monkeypatch.setattr(onboarding_tests, "bundled_llama_server_available", lambda: False)
    monkeypatch.setattr(
        onboarding_tests,
        "runtime_is_installed",
        lambda bundle: state.get(bundle.id, False),
    )
    monkeypatch.setattr(onboarding_tests, "model_is_installed", lambda _model: state["model"])

    def install_runtime(bundle, progress_callback, **_kwargs):
        calls.append(bundle.id)
        progress_callback(RuntimeProgress("test", "Downloading", 50, 100))
        state[bundle.id] = True

    def install_model(_model, progress_callback, **_kwargs):
        calls.append("model")
        progress_callback(RuntimeProgress("test", "Downloading", 100, 100))
        state["model"] = True

    monkeypatch.setattr(onboarding_tests, "install_runtime", install_runtime)
    monkeypatch.setattr(onboarding_tests, "install_polish_model", install_model)
    monkeypatch.setattr(onboarding_tests, "verify_completion_backend", lambda *_args, **_kwargs: None)
    _path, window = make_window(tmp_path)
    model = window.recommended_polish_model
    window.polish_setup_running = True
    window._run_polish_setup([accelerated, baseline], model)
    window._poll_polish_setup()
    assert calls == ["test-cpu", "test-gpu", "model"]
    assert window.polish_setup_running is False
    assert window.polish_setup_progress.value() == 100
    assert window.polish_setup_status.isHidden()
    assert window.polish_test_button is None
    assert window.polish_app_group.checkedButton() is not None
    close_window(window, qt_app)


def test_polish_setup_keeps_cpu_fallback_when_acceleration_install_fails(
    tmp_path, qt_app, monkeypatch
):
    import voicepilot.onboarding_downloads as onboarding_tests
    from voicepilot.ai_catalog import RuntimeBundle

    accelerated = RuntimeBundle("test-gpu", "vulkan", "x64", ())
    baseline = RuntimeBundle("test-cpu", "cpu", "x64", ())
    installed: set[str] = set()

    monkeypatch.setattr(onboarding_tests, "bundled_llama_server_available", lambda: False)
    monkeypatch.setattr(
        onboarding_tests,
        "runtime_candidates",
        lambda _hardware: [accelerated, baseline],
    )
    monkeypatch.setattr(
        onboarding_tests,
        "runtime_is_installed",
        lambda bundle: bundle.id in installed,
    )
    state = {"model": False}
    monkeypatch.setattr(onboarding_tests, "model_is_installed", lambda _model: state["model"])

    def install_runtime(bundle, **_kwargs):
        if bundle.backend != "cpu":
            raise RuntimeError("GPU unavailable")
        installed.add(bundle.id)

    monkeypatch.setattr(onboarding_tests, "install_runtime", install_runtime)
    monkeypatch.setattr(
        onboarding_tests,
        "install_polish_model",
        lambda *_args, **_kwargs: state.update(model=True),
    )
    monkeypatch.setattr(onboarding_tests, "verify_completion_backend", lambda *_args, **_kwargs: None)
    _path, window = make_window(tmp_path)
    window.polish_setup_running = True
    window._run_polish_setup([accelerated, baseline], window.recommended_polish_model)
    window._poll_polish_setup()

    assert "compatible option" in window.polish_setup_status.text().casefold()
    assert not window.polish_setup_status.isHidden()
    close_window(window, qt_app)


def test_try_step_never_starts_an_unapproved_download(tmp_path, qt_app, monkeypatch):
    import voicepilot.onboarding_downloads as onboarding_tests

    downloads: list[str] = []
    monkeypatch.setattr(onboarding_tests, "download_model", lambda model, **_kwargs: downloads.append(model))
    _path, window = make_window(tmp_path)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: False)
    window.index = 1
    window._refresh()
    assert downloads == []
    assert "speech support is not ready" in window.dictation_status.text().casefold()
    assert "download the selected model" in window.dictation_result.text().casefold()
    assert window.dictation_test_button is None
    assert window.dictate_shortcut_recorder.value()
    close_window(window, qt_app)


def test_completed_download_rechecks_the_current_language_choice(tmp_path, qt_app, monkeypatch):
    _path, window = make_window(tmp_path)
    refreshed: list[bool] = []

    def refresh_current_choice():
        refreshed.append(True)
        window.model_status.setText("Current choice still needs a download.")

    monkeypatch.setattr(window, "_refresh_model_status", refresh_current_choice)
    window.download_running = True
    window.download_events.put(("done", "old choice ready"))
    window._poll_download()
    assert refreshed == [True]
    assert window.model_status.text() == "Current choice still needs a download."
    close_window(window, qt_app)


def test_removed_setup_action_is_not_exposed_in_settings(tmp_path, qt_app):
    from PySide6.QtWidgets import QPushButton
    from voicepilot.settings_qt import SettingsWindow

    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    window = SettingsWindow(path)
    buttons = [button.text() for button in window.window.findChildren(QPushButton)]
    assert "Run setup again" not in buttons
    window.close()
    qt_app.processEvents()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_onboarding_uses_same_structure_in_light_and_dark(tmp_path, qt_app, theme):
    config = AppConfig()
    config.hud.theme = theme
    _path, window = make_window(tmp_path / theme, config=config)
    assert window.palette.mode == theme
    assert window.stack.count() == 5
    assert window.window.minimumWidth() <= window.window.width()
    assert window.window.minimumHeight() <= window.window.height()
    close_window(window, qt_app)


def test_onboarding_dark_is_charcoal_with_the_light_brand_accents(tmp_path, qt_app):
    from voicepilot.theme import DARK, LIGHT

    config = AppConfig()
    config.hud.theme = "dark"
    _path, window = make_window(tmp_path, config=config)
    assert window.palette.mode == "dark"
    assert window.palette.bg == DARK.bg
    assert window.palette.surface == DARK.surface
    assert window.palette.sidebar == DARK.sidebar
    assert window.palette.accent == LIGHT.accent
    assert window.palette.accent_2 == LIGHT.accent_2
    assert window.palette.on_accent == LIGHT.on_accent
    stylesheet = window.window.styleSheet()
    assert f"QProgressBar#SetupProgress::chunk {{ background: {LIGHT.accent}" in stylesheet
    assert f"border-left: 3px solid {LIGHT.accent}" in stylesheet
    assert f"stop:0 {LIGHT.accent}, stop:1 {LIGHT.accent_2}" in stylesheet
    close_window(window, qt_app)


def test_onboarding_does_not_recolor_windows_high_contrast_dark(monkeypatch):
    import voicepilot.windows_ui as windows_ui
    from voicepilot.theme import HIGH_CONTRAST_DARK, get_palette

    monkeypatch.setattr(windows_ui, "prefers_high_contrast", lambda: True)
    assert get_palette("dark") == HIGH_CONTRAST_DARK


def test_onboarding_reuses_settings_shell_controls_and_cursor_language(tmp_path, qt_app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFrame

    _path, window = make_window(tmp_path)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: True)
    window._refresh()
    assert window.window.centralWidget().objectName() == "AppCanvas"
    assert window.window.findChild(QFrame, "ContentPanel") is not None
    assert len(window.window.findChildren(QFrame, "StepItem")) == 5
    assert window.window.findChild(QFrame, "PrivacyPill") is None
    assert window.window.findChild(QFrame, "LocalBadgeCard") is None
    assert window.language_combo.objectName() == "SettingsCombo"
    assert window.next_button.cursor().shape() == Qt.PointingHandCursor
    assert window.setup_progress.minimum() == 1
    assert window.setup_progress.maximum() == window.stack.count()
    close_window(window, qt_app)


def test_default_theme_follows_the_system_and_dark_mode_is_supported(tmp_path, qt_app, monkeypatch):
    import voicepilot.theme as theme

    monkeypatch.setattr(theme, "system_theme", lambda: "dark")
    config = AppConfig()
    assert config.hud.theme == "system"
    _path, window = make_window(tmp_path, config=config)
    assert window.palette.mode == "dark"
    close_window(window, qt_app)


def test_dictation_test_drives_the_real_hud_contract(tmp_path, qt_app):
    _path, window = make_window(tmp_path)

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    probe = HudProbe()
    window.index = 1
    window.dictation_test_hud = probe
    window._show_dictation_test_hud("Listening", "Setup test", "record")
    assert probe.messages == [("Listening", "Setup test", "record")]
    window.dictation_test_hud = None
    close_window(window, qt_app)


def test_finish_summary_reflects_real_choices_instead_of_hardcoded_defaults(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    hindi = window.language_combo.findData("hi")
    window.language_combo.setCurrentIndex(hindi)
    precise = next(button for button in window.speed_group.buttons() if button.property("profile_id") == "precise")
    precise.setChecked(True)
    window.polish_check.setChecked(False)
    window.index = 4
    window._refresh()
    assert window.finish_language_value.text() == window.language_combo.currentText()
    assert window.finish_quality_value.text() == "Best quality"
    assert window.finish_polish_value.text() == "Dictation only"
    assert window.next_button.isHidden()
    assert window.defer_button.isHidden()
    assert window.finish_button.text() == "Launch Winsper"
    assert not window.finish_button.isHidden()
    close_window(window, qt_app)


def test_finish_page_has_no_purchase_action(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    assert not hasattr(window, "purchase_button")
    assert not hasattr(window, "purchase_status")
    close_window(window, qt_app)


def test_finish_action_completes_setup_and_launches_without_a_trial(tmp_path, qt_app, monkeypatch):
    path, window = make_window(tmp_path)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: True)
    window.index = 4
    window._refresh()
    window.finish_button.click()
    qt_app.processEvents()
    saved = load_config(path)
    assert saved.onboarding.completed is True
    assert saved.onboarding.current_step == 0


def test_shortcut_confirmation_and_hidden_safety_choices_are_truthful(tmp_path, qt_app):
    config = AppConfig()
    config.speech.preload_on_startup = False
    config.dictation.polish_fallback_to_ramble = False
    path, window = make_window(tmp_path, config=config)
    window.dictate_shortcut_recorder.setValue("ctrl+alt+d")
    window.dictate_shortcut_recorder.shortcutChanged.emit("ctrl+alt+d")
    assert window.hotkey_check_status.text() == ""
    assert window.hotkey_check_status.isHidden()
    assert window.dictation_practice_shortcut_chip.accessibleDescription() == "Ctrl  +  Alt  +  D"
    assert window._persist_progress()
    saved = load_config(path)
    assert saved.hotkeys.dictate == "ctrl+alt+d"
    assert saved.speech.preload_on_startup is False
    assert saved.dictation.polish_fallback_to_ramble is False
    close_window(window, qt_app)


def test_sidebar_uses_icons_and_theme_toggle_is_compact(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    assert all(not label.text() and label.pixmap() is not None for label in window.step_numbers)
    assert window.theme_toggle.width() == 32
    starting_mode = window.palette.mode
    window.theme_toggle.click()
    assert window.palette.mode != starting_mode
    assert window.config.hud.theme in {"light", "dark"}
    close_window(window, qt_app)


def test_setup_exercises_use_real_shortcuts_not_test_buttons(tmp_path, qt_app):
    from PySide6.QtWidgets import QLabel, QPushButton, QToolButton

    from voicepilot.hud_icons import record_icon_pixmap
    from voicepilot.settings_widgets import format_shortcut

    _path, window = make_window(tmp_path)
    buttons = [button.text() for button in window.window.findChildren(QPushButton)]
    assert "Hold to speak" not in buttons
    assert "Try Polish" not in buttons
    assert window.dictate_shortcut_recorder.value() == window.config.hotkeys.dictate
    assert window.polish_shortcut_recorder.value() == window.config.hotkeys.polish
    copy = "\n".join(label.text() for label in window.window.findChildren(QLabel))
    assert "Try Dictate mode" in copy
    assert "Try your Dictate shortcut" not in copy
    assert "Practice Dictate" not in copy
    assert "Shortcut ready" not in copy
    assert window.dictation_state_icon is None
    assert window.dictation_state_hint is None
    assert window.dictation_practice_shortcut_chip.accessibleDescription() == format_shortcut(
        window.config.hotkeys.dictate
    )
    mic = window.window.findChild(QLabel, "DictatePracticeMic")
    assert mic is not None
    assert mic.pixmap().toImage() == record_icon_pixmap(38).toImage()
    app_buttons = window.window.findChildren(QToolButton, "AppChoice")
    assert [button.text() for button in app_buttons] == [
        "Outlook",
        "Slack",
        "ChatGPT",
        "VS Code",
        "Windows Terminal",
    ]
    assert all(not button.icon().isNull() for button in app_buttons)
    close_window(window, qt_app)


def test_shortcut_events_route_to_the_correct_live_exercise(tmp_path, qt_app, monkeypatch):
    _path, window = make_window(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(window, "_begin_dictation_recording", lambda: calls.append("dictate-start"))
    monkeypatch.setattr(window, "_finish_dictation_recording", lambda: calls.append("dictate-stop"))
    monkeypatch.setattr(window, "_begin_polish_recording", lambda: calls.append("polish-start"))
    monkeypatch.setattr(window, "_finish_polish_recording", lambda: calls.append("polish-stop"))
    window.index = 1
    window._handle_onboarding_hotkey_event("start", "dictate")
    window._handle_onboarding_hotkey_event("stop", "dictate")
    window.index = 2
    window._handle_onboarding_hotkey_event("start", "polish")
    window._handle_onboarding_hotkey_event("stop", "polish")
    window.index = 3
    window._handle_onboarding_hotkey_event("start", "dictate")
    window._handle_onboarding_hotkey_event("stop", "dictate")
    assert calls == [
        "dictate-start",
        "dictate-stop",
        "polish-start",
        "polish-stop",
        "dictate-start",
        "dictate-stop",
    ]
    close_window(window, qt_app)


def test_polish_demo_distinguishes_free_speech_and_selected_text(tmp_path, qt_app):
    from PySide6.QtGui import QTextCursor

    _path, window = make_window(tmp_path)
    window.window.show()
    window.index = 2
    window._refresh()
    window.polish_check.setChecked(True)
    selected_mode = next(
        button
        for button in window.polish_mode_group.buttons()
        if button.property("mode_id") == "selected"
    )
    selected_mode.click()
    window.polish_selection_editor.setFocus()
    cursor = window.polish_selection_editor.textCursor()
    cursor.select(QTextCursor.Document)
    window.polish_selection_editor.setTextCursor(cursor)
    qt_app.processEvents()
    selected_text = window._current_selected_demo_text().casefold()
    assert "checkout timeout" in selected_text
    assert "dont change the public api" in selected_text
    window.polish_selection_editor.clearFocus()
    assert "checkout timeout" in window._current_selected_demo_text().casefold()
    close_window(window, qt_app)


def test_dictation_setup_prepares_exact_selected_runtime_and_microphone(
    tmp_path, qt_app, monkeypatch
):
    import voicepilot.onboarding_tests as onboarding_tests

    calls: dict[str, object] = {}

    class Recorder:
        def warm_up(self):
            calls["microphone_warm"] = True
            return True

        def close(self):
            calls["recorder_closed"] = True

    class Transcriber:
        def __init__(self, speech, vocabulary, on_device_fallback=None):
            calls["speech"] = speech
            calls["vocabulary"] = vocabulary
            calls["fallback_callback"] = on_device_fallback

        def mode_config(self, model):
            calls["model"] = model
            return window._preview_config().speech

        def preload_model(self, speech_config, progress_callback=None):
            calls["preloaded"] = speech_config
            del progress_callback
            return True

        def close(self):
            calls["transcriber_closed"] = True

    monkeypatch.setattr(onboarding_tests, "create_audio_recorder", lambda _config: Recorder())
    monkeypatch.setattr(onboarding_tests, "IsolatedSpeechTranscriber", Transcriber)
    _path, window = make_window(tmp_path)
    config = window._preview_config()
    window.dictation_runtime_generation = 7
    window._prepare_dictation_test_runtime(config, 7)
    generation, event, payload = window.dictation_runtime_events.get_nowait()
    recorder, transcriber, speech_config, microphone_ready = payload
    assert (generation, event, microphone_ready) == (7, "ready", True)
    assert calls["model"] == config.dictation.ramble_model
    assert calls["preloaded"] == speech_config
    assert speech_config.purpose == "dictation"
    assert calls["microphone_warm"] is True
    assert callable(calls["fallback_callback"])
    recorder.close()
    transcriber.close()
    close_window(window, qt_app)


def test_dictation_setup_reuses_warm_recorder_and_transcriber_for_attempt(tmp_path, qt_app):
    from types import SimpleNamespace

    _path, window = make_window(tmp_path)

    class Recorder:
        closed = False

        def stop(self):
            return SimpleNamespace(duration_seconds=1.0)

        def close(self):
            self.closed = True

    class Transcriber:
        def transcribe(self, _clip, **_kwargs):
            return "hello world"

    recorder = Recorder()
    transcriber = Transcriber()
    config = window._preview_config()
    window.active_dictation_test_generation = 3
    window._stop_dictation_capture(config, recorder, transcriber, config.speech, 3)
    events = []
    while not window.dictation_test_events.empty():
        events.append(window.dictation_test_events.get_nowait()[1])
    assert events[-1] == "done"
    assert recorder.closed is False
    close_window(window, qt_app)


def test_silent_dictation_matches_production_nothing_heard_state(tmp_path, qt_app):
    _path, window = make_window(tmp_path)

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    probe = HudProbe()
    window.dictation_test_hud = probe
    window.active_dictation_test_generation = 4
    window.dictation_test_running = True
    window.dictation_test_events.put((4, "silent", ""))
    window._poll_dictation_test()
    assert window.dictation_status.text() == "Nothing heard"
    assert window.dictation_result.text() == "No speech was detected. Hold Dictate and try again."
    assert probe.messages[-1] == ("Nothing heard", "No speech was detected", "warning")
    window.dictation_test_hud = None
    close_window(window, qt_app)

def test_silence_exception_never_uses_error_hud(tmp_path, qt_app):
    _path, window = make_window(tmp_path)

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    probe = HudProbe()
    window.dictation_test_hud = probe
    window.active_dictation_test_generation = 6
    window.dictation_test_events.put((6, "error", "Only silence was captured."))
    window._poll_dictation_test()
    assert window.dictation_status.text() == "Nothing heard"
    assert window.dictation_result.text() == "No speech was detected. Hold Dictate and try again."
    assert probe.messages[-1] == ("Nothing heard", "No speech was detected", "warning")
    window.dictation_test_hud = None
    close_window(window, qt_app)


def test_quality_controls_are_circular_and_downloaded_models_show_ticks(
    tmp_path, qt_app, monkeypatch
):
    import voicepilot.onboarding_tests as onboarding_tests
    from types import SimpleNamespace

    _path, window = make_window(tmp_path)
    assert all(not button.icon().isNull() for button in window.speed_group.buttons())
    from PySide6.QtWidgets import QRadioButton

    assert "QRadioButton#QualityChoiceControl" not in window.window.styleSheet()
    assert not window.window.findChildren(QRadioButton)

    monkeypatch.setattr(
        onboarding_tests,
        "installed_status",
        lambda *_args, **_kwargs: SimpleNamespace(installed=True),
    )
    monkeypatch.setattr(onboarding_tests, "engine_runtime_available", lambda _engine: True)
    window._refresh_model_status()
    assert all(tick.isVisibleTo(window.window) for _label, tick in window.speech_quality_models.values())
    assert window.model_download_button.isHidden()
    assert window.model_download_button.text() != "Speech support ready"
    close_window(window, qt_app)


def test_polish_quality_has_three_models_and_persists_the_selected_model(tmp_path, qt_app, monkeypatch):
    from voicepilot.ai_catalog import POLISH_MODELS
    import voicepilot.onboarding_pages as onboarding_pages

    fast = next(model for model in POLISH_MODELS if model.tier == "fast")
    monkeypatch.setattr(onboarding_pages, "compatible_polish_models", lambda _hardware: (fast,))
    _path, window = make_window(tmp_path)
    buttons = window.polish_quality_group.buttons()
    assert len(buttons) == 3
    assert not window.polish_quality_choices.isHidden()
    assert window.polish_quality_change_button is None
    enabled = [button for button in buttons if button.isEnabled()]
    assert enabled
    target = enabled[-1]
    target.setChecked(True)
    assert window._persist_progress()
    assert window.config.rewrite.provider == "embedded"
    assert window.config.rewrite.llama_model_id == target.property("model_id")
    saved = load_config(_path)
    assert saved.rewrite.llama_model_id == target.property("model_id")
    assert window.recommended_polish_model.id == target.property("model_id")
    assert window.polish_setup_button.text()
    close_window(window, qt_app)


def test_waiting_and_download_states_never_use_a_marquee(tmp_path, qt_app):
    from voicepilot.models import DownloadProgress

    _path, window = make_window(tmp_path)
    progress = DownloadProgress("model", "example/model", "Checking files")
    window._apply_download_progress(progress, window.model_status, window.model_download_progress)
    assert window.model_download_progress.isHidden()
    assert window.model_download_progress.minimum() == 0
    assert window.model_download_progress.maximum() == 100
    close_window(window, qt_app)


def test_internal_dictation_errors_are_sanitized_and_no_speech_is_warning(tmp_path, qt_app):
    from voicepilot.onboarding_helpers import friendly_setup_error

    _path, window = make_window(tmp_path)
    assert friendly_setup_error(RuntimeError("OnboardingTestsMixin._run_dictation_test failed")) == (
        "Something interrupted the test. Try again."
    )
    window.active_dictation_test_generation = 8
    window.dictation_test_events.put((8, "error", "almost no speech energy"))
    window._poll_dictation_test()
    assert window.dictation_status.text() == "Nothing heard"
    assert "no speech was detected" in window.dictation_result.text().casefold()
    close_window(window, qt_app)


def test_polish_no_speech_uses_the_same_warning_contract(tmp_path, qt_app):
    _path, window = make_window(tmp_path)

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    probe = HudProbe()
    window.dictation_test_hud = probe
    window.polish_test_events.put(("error", "No speech was detected."))
    window._poll_live_polish()
    assert window.polish_free_state_title.text() == "Nothing heard"
    assert window.polish_test_result.text() == "No speech was detected."
    assert probe.messages[-1] == ("Nothing heard", "No speech was detected", "warning")
    window.dictation_test_hud = None
    close_window(window, qt_app)
