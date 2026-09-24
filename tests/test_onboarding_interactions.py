from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from voicepilot.config import AppConfig, save_config


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


def test_polish_modes_and_voice_triggers_are_explicit(tmp_path, qt_app):
    from PySide6.QtWidgets import QLabel, QPushButton

    _path, window = make_window(tmp_path)
    assert len(window.polish_mode_group.buttons()) == 2
    copy = "\n".join(
        [
            *(label.text() for label in window.window.findChildren(QLabel)),
            *(button.text() for button in window.window.findChildren(QPushButton)),
        ]
    ).casefold()
    for expected in (
        "nothing selected",
        "text selected",
        "press enter",
        "today's date",
        "format while you speak",
    ):
        assert expected in copy
    for removed in ("change selected text", "turn it into bullets", "undo last paste"):
        assert removed not in copy
    window.index = 3
    window._refresh()
    assert window.step_labels[3].text() == "Optional voice triggers"
    close_window(window, qt_app)


def test_quality_row_is_clickable_with_pointing_cursor(tmp_path, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    _path, window = make_window(tmp_path)
    target = next(button for button in window.speed_group.buttons() if not button.isChecked())
    row = target.parentWidget()
    window.window.show()
    qt_app.processEvents()
    assert row.cursor().shape() == Qt.PointingHandCursor
    QTest.mouseClick(row, Qt.LeftButton, pos=row.rect().center())
    assert target.isChecked()
    close_window(window, qt_app)


def test_polish_toggle_hides_options_and_ready_buttons(tmp_path, qt_app, monkeypatch):
    _path, window = make_window(tmp_path)
    window.window.show()
    window.index = 2
    window._refresh()
    window.polish_check.setChecked(False)
    assert window.polish_options_container.isHidden()
    assert window.polish_disabled_state.isVisibleTo(window.window)
    window.polish_check.setChecked(True)
    assert not window.polish_options_container.isHidden()
    assert window.polish_disabled_state.isHidden()
    assert window.polish_skip_button is None
    monkeypatch.setattr(window, "_polish_support_ready", lambda: True)
    window._refresh_polish_setup_status()
    assert window.polish_setup_button.isHidden()
    assert window.polish_setup_status.isHidden()
    assert window.polish_setup_button.text() != "Polish ready"
    assert window.polish_disabled_state.minimumHeight() == 0
    from PySide6.QtWidgets import QFrame

    assert window.polish_disabled_state.findChild(QFrame, "PolishDisabledFeature") is None
    close_window(window, qt_app)


def test_polish_mode_buttons_show_only_the_chosen_exercise(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    window.polish_check.setChecked(True)
    free = next(
        button for button in window.polish_mode_group.buttons() if button.property("mode_id") == "free"
    )
    selected = next(
        button
        for button in window.polish_mode_group.buttons()
        if button.property("mode_id") == "selected"
    )
    assert free.isChecked()
    assert all(not button.icon().isNull() for button in window.polish_mode_group.buttons())
    assert not window.polish_free_speech_card.isHidden()
    assert not window.polish_free_prompt_card.isHidden()
    assert window.polish_selected_text_card.isHidden()
    selected.click()
    assert window.polish_free_speech_card.isHidden()
    assert window.polish_free_prompt_card.isHidden()
    assert not window.polish_selected_text_card.isHidden()
    close_window(window, qt_app)


def test_trigger_practice_uses_production_recognition_without_editors(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    window.window.show()
    window.index = 3
    window._refresh()
    assert not hasattr(window, "spoken_enter_phrase")
    assert not hasattr(window, "trigger_test_input")
    window.config.spoken_actions.enabled = True
    assert not window._evaluate_trigger_dictation("Hello team, the update is ready")
    assert window.trigger_test_stage == "formatting"
    transcript = "Project update\nDesign is approved\n\nEngineering starts Monday press enter"
    assert window._evaluate_trigger_dictation(transcript)
    assert window.trigger_test_stage == "date"
    qt_app.processEvents()
    assert "\n\n" in window.trigger_format_result.text()
    assert "enter will be pressed" in window.trigger_format_result.text().casefold()
    assert window.trigger_format_card.property("taskComplete") is True
    assert window.trigger_format_card.property("activeTask") is False
    assert window.trigger_date_card.property("activeTask") is True
    assert window.trigger_date_panel.hasFocus()
    assert window._evaluate_trigger_dictation("today's date")
    assert window.trigger_test_stage == "complete"
    assert window.trigger_date_result.text()
    assert window.trigger_date_card.property("taskComplete") is True
    assert window.trigger_date_card.property("activeTask") is False
    assert window.next_button.hasFocus()
    close_window(window, qt_app)


def test_trigger_page_gives_a_visible_read_aloud_script(tmp_path, qt_app):
    from PySide6.QtWidgets import QLabel

    _path, window = make_window(tmp_path)
    copy = "\n".join(label.text() for label in window.window.findChildren(QLabel)).casefold()
    assert "project update new line design is approved" in copy
    assert "new paragraph engineering starts monday press enter" in copy
    assert "line break, paragraph break, and enter action" in copy
    close_window(window, qt_app)


def test_polish_exercise_uses_app_consequential_constraints(tmp_path, qt_app):
    from PySide6.QtWidgets import QLabel, QTextEdit

    _path, window = make_window(tmp_path)
    copy = "\n".join(label.text() for label in window.window.findChildren(QLabel)).casefold()
    selected = "\n".join(
        editor.toPlainText() for editor in window.window.findChildren(QTextEdit)
    ).casefold()
    for expected in ("hey alex", "quarterly results", "regards, jordan"):
        assert expected in copy
    for expected in ("30 seconds", "retries", "public api", "release friday"):
        assert expected in selected
    assert "clear release checklist" in copy
    assert "transformed text" in copy
    assert "say this rough thought" not in copy
    assert "now choose where it is going" not in copy
    close_window(window, qt_app)


def test_polish_teaches_speech_then_app_choice_then_result(tmp_path, qt_app):
    from PySide6.QtCore import QPoint
    from voicepilot.destination import infer_destination
    from voicepilot.app_icons import app_icon_path
    from voicepilot.polish_prompts import no_selection_operation

    _path, window = make_window(tmp_path)
    window.window.show()
    window.index = 2
    window.polish_check.setChecked(True)
    window._refresh()
    qt_app.processEvents()
    prompt_y = window.polish_free_prompt_card.mapTo(
        window.polish_options_container, QPoint(0, 0)
    ).y()
    result_y = window.polish_free_speech_card.mapTo(
        window.polish_options_container, QPoint(0, 0)
    ).y()
    assert prompt_y < result_y
    examples = {
        button.text(): str(button.property("spoken_example"))
        for button in window.polish_app_group.buttons()
    }
    shared_marks = {
        app_id: app_icon_path(app_id)
        for app_id in ("outlook", "slack", "chatgpt", "vscode", "terminal")
    }
    assert all(path is not None for path in shared_marks.values())
    assert all("voicepilot/assets/apps" in path.as_posix() for path in shared_marks.values())
    assert len(set(examples.values())) == len(examples)
    row_buttons = [
        window.polish_app_layout.itemAt(index).widget()
        for index in range(window.polish_app_layout.count())
        if window.polish_app_layout.itemAt(index).widget() is not None
    ]
    assert row_buttons == window.polish_app_group.buttons()
    assert next(
        button.text() for button in window.polish_mode_group.buttons()
        if button.property("mode_id") == "free"
    ) == "Nothing selected — app-aware"
    assert "regards, jordan" in examples["Outlook"].casefold()
    assert "tests are still running" in examples["Slack"].casefold()
    assert "recommend one" in examples["ChatGPT"].casefold()
    assert "create a json object" in examples["VS Code"].casefold()
    assert examples["Windows Terminal"] == "CD into Documents."
    routes = {
        button.text(): (button.property("process_name"), button.property("profile_name"))
        for button in window.polish_app_group.buttons()
    }
    assert routes["ChatGPT"] == ("chatgpt.exe", "prompt")
    assert routes["Windows Terminal"] == ("windowsterminal.exe", "terminal")
    terminal_destination = infer_destination(
        "windowsterminal.exe", "Terminal", "terminal", "Windows Terminal"
    )
    assert no_selection_operation(examples["Windows Terminal"], terminal_destination) == "command"
    for button in window.polish_app_group.buttons():
        button.click()
        assert window.polish_free_prompt_text.text() == examples[button.text()]
    close_window(window, qt_app)


def test_non_dictate_steps_do_not_publish_an_idle_hud(tmp_path, qt_app, monkeypatch):
    _path, window = make_window(tmp_path)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: True)
    messages: list[tuple[str, str, str]] = []
    monkeypatch.setattr(window, "_show_dictation_test_hud", lambda *message: messages.append(message))
    monkeypatch.setattr(window, "_ensure_polish_test_runtime", lambda: None)
    window.dictation_runtime_ready = True
    preview = window._preview_config()
    window.dictation_runtime_signature = (preview.dictation.ramble_model, preview.speech.language)
    for index in (4, 3, 2):
        window.index = index
        window._refresh()
    assert messages == []
    window.index = 1
    window._refresh()
    assert messages == [("Ready", "Hold the hotkey to speak", "idle")]
    close_window(window, qt_app)

def test_theme_switch_repaints_quality_icons_for_the_new_surface(tmp_path, qt_app):
    config = AppConfig()
    config.hud.theme = "dark"
    _path, window = make_window(tmp_path, config=config)
    unchecked = next(button for button in window.speed_group.buttons() if not button.isChecked())
    before = unchecked.icon().pixmap(22, 22).toImage().pixelColor(11, 11).name()
    assert before == window.palette.surface.casefold()
    window._toggle_theme()
    after = unchecked.icon().pixmap(22, 22).toImage().pixelColor(11, 11).name()
    assert window.palette.mode == "light"
    assert after == window.palette.surface.casefold()
    assert after != before
    close_window(window, qt_app)


def test_theme_switch_recreates_the_hud_with_the_new_theme(tmp_path, qt_app):
    config = AppConfig()
    config.hud.theme = "dark"
    _path, window = make_window(tmp_path, config=config)

    class HudProbe:
        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    probe = HudProbe()
    window.dictation_test_hud = probe
    window._toggle_theme()
    assert probe.stop_calls == 1
    assert window.dictation_test_hud is None
    assert window.config.hud.theme == "light"
    close_window(window, qt_app)


def test_live_polish_reuses_prepared_transcriber_and_rewriter(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    calls = SimpleNamespace(transcribe=0, polish=0)

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    class Transcriber:
        def mode_config(self, _model):
            return window.config.speech

        def transcribe(self, _clip, **_kwargs):
            calls.transcribe += 1
            return "um checkout requests time out after thirty seconds"

    class Rewriter:
        def polish(self, text, **_kwargs):
            calls.polish += 1
            return text.replace("um ", "").replace("thirty", "30")

    transcriber = Transcriber()
    rewriter = Rewriter()
    app = {"label": "Outlook", "process": "outlook.exe", "profile": "email"}
    config = window._preview_config()
    probe = HudProbe()
    window.dictation_test_hud = probe
    window._run_live_polish(config, object(), "", app, transcriber, rewriter)
    window._run_live_polish(config, object(), "", app, transcriber, rewriter)
    assert calls.transcribe == 2
    assert calls.polish == 2
    assert window.polish_test_events.qsize() == 2
    assert probe.messages == [
        ("Polishing text", "Improving clarity", "rewrite"),
        ("Polishing text", "Improving clarity", "rewrite"),
    ]
    window.dictation_test_hud = None
    close_window(window, qt_app)


def test_selected_polish_transcribes_spoken_request_as_instruction(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    purposes: list[str] = []

    class Transcriber:
        def mode_config(self, _model):
            return window.config.speech

        def transcribe(self, _clip, *, config, **_kwargs):
            purposes.append(config.purpose)
            return "turn this into three bullet points"

    class Rewriter:
        def rewrite(self, selected_text, instruction, **_kwargs):
            assert selected_text == "Selected text"
            assert instruction == "turn this into three bullet points"
            return "- First\n- Second\n- Third"

    window._run_live_polish(
        window._preview_config(),
        object(),
        "Selected text",
        {"label": "Selected text", "process": "", "profile": "general"},
        Transcriber(),
        Rewriter(),
    )
    assert purposes == ["polish_instruction"]
    close_window(window, qt_app)


def test_polish_reuses_the_warm_dictation_microphone(tmp_path, qt_app, monkeypatch):
    _path, window = make_window(tmp_path)
    calls = SimpleNamespace(start=0, stop=0, close=0)

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    class Recorder:
        def start(self):
            calls.start += 1

        def stop(self):
            calls.stop += 1

        def close(self):
            calls.close += 1

    recorder = Recorder()
    window.index = 2
    window.dictation_runtime_ready = True
    window.dictation_recorder = recorder
    window.dictation_transcriber = object()
    window.polish_rewriter = object()
    probe = HudProbe()
    window.dictation_test_hud = probe
    monkeypatch.setattr(window, "_polish_support_ready", lambda: True)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: True)
    window._begin_polish_recording()
    assert window.polish_recorder is recorder
    assert calls.start == 1
    assert probe.messages[-1] == (
        "Listening for polish",
        f"{window.polish_active_app['label']} — release to polish",
        "rewrite",
    )
    window._stop_polish_test()
    assert calls.stop == 1
    assert calls.close == 0
    window.dictation_recorder = None
    window.dictation_transcriber = None
    window.polish_rewriter = None
    window.dictation_test_hud = None
    close_window(window, qt_app)


def test_selected_polish_uses_production_instruction_hud(tmp_path, qt_app, monkeypatch):
    from PySide6.QtGui import QTextCursor
    _path, window = make_window(tmp_path)

    class Recorder:
        def start(self):
            pass

        def stop(self):
            return None

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    selected = next(
        button
        for button in window.polish_mode_group.buttons()
        if button.property("mode_id") == "selected"
    )
    selected.setChecked(True)
    cursor = window.polish_selection_editor.textCursor()
    cursor.select(QTextCursor.Document)
    window.polish_selection_editor.setTextCursor(cursor)
    window.polish_selection_editor.clearFocus()
    window.index = 2
    window.dictation_runtime_ready = True
    window.dictation_recorder = Recorder()
    window.dictation_transcriber = object()
    window.polish_rewriter = object()
    probe = HudProbe()
    window.dictation_test_hud = probe
    monkeypatch.setattr(window, "_polish_support_ready", lambda: True)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: True)
    window._begin_polish_recording()
    assert probe.messages[-1] == (
        "Say your instruction",
        "Selected text — release to transform",
        "rewrite",
    )
    assert "checkout timeout" in window.polish_selected_text.casefold()
    window._stop_polish_test()
    window.dictation_recorder = None
    window.dictation_transcriber = None
    window.polish_rewriter = None
    window.dictation_test_hud = None
    close_window(window, qt_app)


def test_navigation_keeps_dictation_prepare_alive_between_exercises(tmp_path, qt_app, monkeypatch):
    _path, window = make_window(tmp_path)
    stopped: list[int] = []
    monkeypatch.setattr(window, "_stop_polish_test", lambda: None)
    monkeypatch.setattr(window, "_cancel_dictation_attempt", lambda: None)
    monkeypatch.setattr(window, "_stop_polish_test_runtime", lambda: None)
    monkeypatch.setattr(window, "_stop_dictation_test", lambda: stopped.append(window.index))
    monkeypatch.setattr(window, "_persist_progress", lambda: None)
    monkeypatch.setattr(window, "_refresh", lambda: None)

    window.index = 1
    window._next()
    assert window.index == 2
    assert stopped == []
    window._next()
    assert window.index == 3
    assert stopped == []
    window._next()
    assert window.index == 4
    assert stopped == [3]
    close_window(window, qt_app)



def test_dictation_ready_on_polish_page_continues_polish_prepare(tmp_path, qt_app, monkeypatch):
    _path, window = make_window(tmp_path)
    calls: list[str] = []

    class Resource:
        def close(self):
            pass

    window.index = 2
    window.dictation_runtime_generation = 7
    window.dictation_runtime_preparing = True
    monkeypatch.setattr(window, "_restart_onboarding_hotkeys", lambda: None)
    monkeypatch.setattr(window, "_ensure_polish_test_runtime", lambda: calls.append("polish"))
    window.dictation_runtime_events.put(
        (7, "ready", (Resource(), Resource(), window.config.speech, True))
    )
    window._poll_dictation_runtime()
    assert window.dictation_runtime_ready
    assert calls == ["polish"]
    close_window(window, qt_app)


def test_quality_selection_always_recomputes_download_visibility(tmp_path, qt_app, monkeypatch):
    from types import SimpleNamespace

    import voicepilot.onboarding_tests as onboarding_tests

    _path, window = make_window(tmp_path)
    balanced = next(
        button for button in window.speed_group.buttons() if button.property("profile_id") == "balanced"
    )
    fast = next(
        button for button in window.speed_group.buttons() if button.property("profile_id") == "instant"
    )
    balanced_model = window._speech_model_for_profile("balanced").model
    monkeypatch.setattr(
        onboarding_tests,
        "installed_status",
        lambda preset, **_kwargs: SimpleNamespace(installed=preset.model != balanced_model),
    )
    monkeypatch.setattr(onboarding_tests, "engine_runtime_available", lambda _engine: True)
    window._refresh_model_status()
    fast.setChecked(True)
    assert window.model_download_button.isHidden()
    balanced.setChecked(True)
    assert not window.model_download_button.isHidden()
    assert "download" in window.model_download_button.text().casefold()
    fast.setChecked(True)
    assert window.model_download_button.isHidden()
    balanced.setChecked(True)
    assert not window.model_download_button.isHidden()
    close_window(window, qt_app)


def test_dark_sidebar_step_icons_do_not_render_as_extra_circles(tmp_path, qt_app):
    config = AppConfig()
    config.hud.theme = "dark"
    _path, window = make_window(tmp_path, config=config)
    stylesheet = window.window.styleSheet()
    step_icon_rule = stylesheet.split("QLabel#StepIcon {", 1)[1].split("}", 1)[0]
    assert "border: none" in step_icon_rule
    assert "border-radius" not in step_icon_rule
    close_window(window, qt_app)


def test_onboarding_typography_matches_settings_foundation(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    stylesheet = window.window.styleSheet()
    assert 'font-family: "Segoe UI"' in stylesheet
    page_title_rule = stylesheet.rsplit("QLabel#PageTitle {", 1)[1].split("}", 1)[0]
    assert "font-size: 26px" in page_title_rule
    assert "font-weight: 600" in page_title_rule
    close_window(window, qt_app)


def test_first_visible_interactive_page_refreshes_runtime_state(tmp_path, qt_app, monkeypatch):
    _path, window = make_window(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(window, "_refresh", lambda: calls.append("visible"))
    window.show()
    qt_app.processEvents()
    assert calls == ["visible"]
    close_window(window, qt_app)


def test_language_page_prepares_dictate_before_first_practice_press(
    tmp_path, qt_app, monkeypatch
):
    _path, window = make_window(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(window, "_speech_support_ready", lambda: True)
    monkeypatch.setattr(window, "_ensure_dictation_test_runtime", lambda: calls.append("prepare"))
    window.index = 0
    window._refresh()
    assert calls == ["prepare"]
    close_window(window, qt_app)


def test_background_dictation_readiness_changes_preparing_hud_to_ready(
    tmp_path, qt_app, monkeypatch
):
    _path, window = make_window(tmp_path)
    window.index = 1

    class Resource:
        def close(self):
            pass

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    probe = HudProbe()
    window.dictation_test_hud = probe
    window.dictation_runtime_generation = 4
    monkeypatch.setattr(window, "_restart_onboarding_hotkeys", lambda: None)
    window.dictation_runtime_events.put(
        (4, "ready", (Resource(), Resource(), window.config.speech, True))
    )
    window._poll_dictation_runtime()
    assert window.dictation_runtime_ready is True
    assert window.dictation_status.text() == "Waiting for your shortcut"
    assert probe.messages == [("Ready", "Hold the hotkey to speak", "idle")]
    window.dictation_test_hud = None
    close_window(window, qt_app)


def test_completed_sidebar_steps_use_blue_checks_without_green_copy(
    tmp_path, qt_app, monkeypatch
):
    import voicepilot.settings_icons as settings_icons

    _path, window = make_window(tmp_path)
    rendered: list[tuple[str, str, int]] = []
    original = settings_icons.settings_nav_icon

    def record_icon(name, color, size):
        rendered.append((name, color, size))
        return original(name, color, size)

    monkeypatch.setattr(settings_icons, "settings_nav_icon", record_icon)
    monkeypatch.setattr(window, "_speech_support_ready", lambda: False)
    window.index = 2
    window._refresh()
    step_icons = [entry for entry in rendered if entry[2] == 15]
    assert step_icons[0] == ("check", window.palette.accent, 15)
    assert step_icons[1] == ("check", window.palette.accent, 15)
    complete_rule = window.window.styleSheet().split(
        'QLabel#StepIcon[complete="true"] {', 1
    )[1].split("}", 1)[0]
    assert window.palette.accent in complete_rule
    assert window.palette.success not in complete_rule
    close_window(window, qt_app)


def test_visible_shortcut_configurator_uses_dismissible_accent_pulse(tmp_path, qt_app):
    _path, window = make_window(tmp_path)
    assert not window.dictate_shortcut_recorder.attentionActive()
    assert not window.dictation_practice_shortcut_chip.attentionActive()
    assert not window.polish_shortcut_recorder.attentionActive()

    window.index = 1
    window.dictation_runtime_ready = True
    preview = window._preview_config()
    window.dictation_runtime_signature = (preview.dictation.ramble_model, preview.speech.language)
    window.dictation_test_hud = SimpleNamespace(show=lambda *_args: None, stop=lambda: None)
    window.dictation_test_hud_ready.set()
    window._refresh()
    assert window.dictate_shortcut_recorder.attentionActive()
    assert window.dictation_practice_shortcut_chip.attentionActive()
    assert not window.polish_shortcut_recorder.attentionActive()

    window.dictate_shortcut_recorder.begin_capture()
    assert not window.dictate_shortcut_recorder.attentionActive()
    assert window.dictation_practice_shortcut_chip.attentionActive()
    window.index = 0
    window._refresh()
    window.index = 1
    window._refresh()
    assert not window.dictate_shortcut_recorder.attentionActive()
    assert window.dictation_practice_shortcut_chip.attentionActive()

    window.dictation_practice_shortcut_chip.dismissAttention()
    assert not window.dictation_practice_shortcut_chip.attentionActive()

    window.index = 2
    window.polish_check.setChecked(True)
    window._refresh()
    assert window.polish_shortcut_recorder.attentionActive()
    close_window(window, qt_app)


def test_actual_shortcut_press_dismisses_every_related_pulse(tmp_path, qt_app, monkeypatch):
    _path, window = make_window(tmp_path)
    monkeypatch.setattr(window, "_begin_dictation_recording", lambda: None)
    monkeypatch.setattr(window, "_begin_polish_recording", lambda: None)
    window.index = 1
    window.dictation_runtime_ready = True
    preview = window._preview_config()
    window.dictation_runtime_signature = (preview.dictation.ramble_model, preview.speech.language)
    window.dictation_test_hud = SimpleNamespace(show=lambda *_args: None, stop=lambda: None)
    window.dictation_test_hud_ready.set()
    window._refresh()
    assert window.dictate_shortcut_recorder.attentionActive()
    assert window.dictation_practice_shortcut_chip.attentionActive()
    window._handle_onboarding_hotkey_event("start", "dictate")
    assert not window.dictate_shortcut_recorder.attentionActive()
    assert not window.dictation_practice_shortcut_chip.attentionActive()

    window.index = 2
    window.polish_check.setChecked(True)
    window._refresh()
    assert window.polish_shortcut_recorder.attentionActive()
    window._handle_onboarding_hotkey_event("start", "polish")
    assert not window.polish_shortcut_recorder.attentionActive()
    close_window(window, qt_app)


def test_shortcut_attention_respects_reduced_motion(tmp_path, qt_app, monkeypatch):
    import voicepilot.windows_ui as windows_ui

    monkeypatch.setattr(windows_ui, "motion_enabled", lambda: False)
    _path, window = make_window(tmp_path)
    window.index = 1
    window.dictation_runtime_ready = True
    preview = window._preview_config()
    window.dictation_runtime_signature = (preview.dictation.ramble_model, preview.speech.language)
    window.dictation_test_hud = SimpleNamespace(show=lambda *_args: None, stop=lambda: None)
    window.dictation_test_hud_ready.set()
    window._refresh()
    assert window.dictate_shortcut_recorder.attentionActive()
    assert window.dictate_shortcut_recorder.property("attentionProgress") == pytest.approx(0.85)
    assert window.dictation_practice_shortcut_chip.attentionActive()
    assert window.dictation_practice_shortcut_chip.property("attentionProgress") == pytest.approx(0.85)
    close_window(window, qt_app)


def test_acoustically_silent_worker_failure_uses_warning_hud(tmp_path, qt_app, monkeypatch):
    import voicepilot.onboarding_tests as onboarding_tests

    _path, window = make_window(tmp_path)

    class Transcriber:
        def transcribe(self, *_args, **_kwargs):
            raise RuntimeError("OnboardingTestsMixin._run_dictation_test failed")

    class HudProbe:
        def __init__(self):
            self.messages = []

        def show(self, title, subtitle, kind):
            self.messages.append((title, subtitle, kind))

    monkeypatch.setattr(onboarding_tests, "clip_has_speech_activity", lambda _clip: False)
    probe = HudProbe()
    window.dictation_test_hud = probe
    window.active_dictation_test_generation = 9
    window._run_dictation_test(
        window._preview_config(), object(), 9, Transcriber(), window.config.speech
    )
    window._poll_dictation_test()
    assert window.dictation_status.text() == "Nothing heard"
    assert window.dictation_result.text() == "No speech was detected. Hold Dictate and try again."
    assert probe.messages[-1] == ("Nothing heard", "No speech was detected", "warning")
    window.dictation_test_hud = None
    close_window(window, qt_app)


def test_polish_silent_worker_failure_uses_warning_contract(tmp_path, qt_app, monkeypatch):
    import voicepilot.onboarding_shortcuts as onboarding_shortcuts

    _path, window = make_window(tmp_path)

    class Transcriber:
        def mode_config(self, _model):
            return window.config.speech

        def transcribe(self, *_args, **_kwargs):
            raise RuntimeError("Speech worker closed unexpectedly")

    monkeypatch.setattr(onboarding_shortcuts, "clip_has_speech_activity", lambda _clip: False)
    window._run_live_polish(
        window._preview_config(),
        object(),
        "",
        {"label": "Outlook", "process": "outlook.exe", "profile": "email"},
        Transcriber(),
        object(),
    )
    event, message = window.polish_test_events.get_nowait()
    assert event == "error"
    assert message == "No speech was detected."
    close_window(window, qt_app)
