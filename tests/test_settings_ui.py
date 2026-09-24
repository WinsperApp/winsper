import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from voicepilot.config import AppConfig, load_config, save_config


def test_shortcut_recorder_accepts_single_keys_and_cancel_chords():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_widgets import create_shortcut_recorder

    app = QApplication.instance() or QApplication([])
    recorder = create_shortcut_recorder("ctrl+space")
    recorder.show()

    QTest.mouseClick(recorder, Qt.LeftButton)
    QTest.keyClick(recorder, Qt.Key_F8)
    assert recorder.value() == "f8"
    assert recorder.property("recording") is False

    QTest.mouseClick(recorder, Qt.LeftButton)
    QTest.keyClick(recorder, Qt.Key_Escape, Qt.ControlModifier | Qt.MetaModifier)
    assert recorder.value() == "ctrl+win+esc"
    assert recorder.property("recording") is False

    QTest.mouseClick(recorder, Qt.LeftButton)
    QTest.keyClick(recorder, Qt.Key_Escape)
    assert recorder.value() == "esc"
    assert recorder.property("recording") is False

    QTest.mouseClick(recorder, Qt.LeftButton)
    QTest.keyClick(recorder, Qt.Key_Backspace)
    assert recorder.value() == "backspace"
    assert recorder.property("recording") is False

    recorder.close()
    app.processEvents()


def test_settings_motion_reaches_exact_final_state():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow, ToggleSwitch

    app = QApplication.instance() or QApplication([])
    toggle = ToggleSwitch.create(False)
    toggle.show()
    QTest.mouseClick(toggle, Qt.LeftButton)
    QTest.qWait(400)
    assert toggle.isChecked()
    assert toggle._thumb_progress == 1.0
    QTest.mouseClick(toggle, Qt.LeftButton)
    QTest.qWait(400)
    assert not toggle.isChecked()
    assert toggle._thumb_progress == 0.0

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        summary = SimpleNamespace(today_words=1234, today_minutes_saved=17.0, today_actions=42)
        with (
            patch("voicepilot.usage.usage_summary", return_value=summary),
            patch.object(SettingsWindow, "_refresh_home_status"),
        ):
            window = SettingsWindow(path)
            QTest.qWait(600)
            assert window._stat_words.text() == "1234"
            assert window._stat_time.text() == "17 min"
            assert window._stat_sessions.text() == "42"
        window.close()
    toggle.close()
    app.processEvents()


def test_general_page_is_stats_first_and_decluttered():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLabel, QStyleOptionViewItem
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with patch.object(SettingsWindow, "_refresh_home_status"):
            window = SettingsWindow(path)
        window.show()
        app.processEvents()

        page = window.stack.currentWidget()
        stats = page.findChild(QFrame, "StatsStrip")
        control = page.findChild(QFrame, "WinsperControl")
        appearance = page.findChild(QComboBox, "AppearanceCombo")
        hud_style = window.widgets["hud.mode"]
        hud_position = window.widgets["hud.position"]
        labels = {label.text() for label in page.findChildren(QLabel)}

        assert stats is not None
        assert control is not None
        assert appearance is not None
        stats_y = stats.mapTo(page, QPoint(0, 0)).y()
        control_y = control.mapTo(page, QPoint(0, 0)).y()
        appearance_y = appearance.mapTo(page, QPoint(0, 0)).y()
        hud_style_y = hud_style.mapTo(page, QPoint(0, 0)).y()
        hud_position_y = hud_position.mapTo(page, QPoint(0, 0)).y()
        assert stats_y < control_y < appearance_y
        assert appearance_y < hud_style_y < hud_position_y
        assert "Ready" not in labels
        assert "Everyday settings" not in labels
        assert "Keyboard shortcuts" not in labels
        assert [appearance.itemData(index) for index in range(appearance.count())] == [
            "system",
            "light",
            "dark",
        ]
        assert [appearance.itemText(index) for index in range(appearance.count())] == [
            "System",
            "Light",
            "Dark",
        ]
        assert [hud_style.itemText(index) for index in range(hud_style.count())] == [
            "Full HUD",
            "Compact HUD",
        ]
        assert [hud_style.itemData(index) for index in range(hud_style.count())] == [
            "standard",
            "compact",
        ]
        assert [hud_position.itemText(index) for index in range(hud_position.count())] == [
            "Bottom center",
            "Bottom left",
            "Bottom right",
            "Top center",
        ]
        assert [hud_position.itemData(index) for index in range(hud_position.count())] == ["center", "left", "right", "top"]
        assert appearance.size() == hud_style.size()
        assert appearance.size() == hud_position.size()
        assert appearance.itemDelegate().sizeHint(QStyleOptionViewItem(), appearance.model().index(0, 0)).height() == 40
        assert appearance.view().objectName() == "SettingsComboPopupList"
        assert window.home_pause_button.cursor().shape() == Qt.PointingHandCursor
        window.close()
    app.processEvents()


def test_settings_buttons_use_consistent_pointer_feedback():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton, QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch("voicepilot.settings_dictation_page.list_audio_devices", return_value=[]),
        ):
            window = SettingsWindow(path)

        window.show()
        window._ensure_all_pages_loaded()
        app.processEvents()

        buttons = window.window.findChildren(QAbstractButton)
        assert buttons
        for button in buttons:
            role = str(button.property("winsperCursorRole") or "")
            expected = (
                Qt.ForbiddenCursor
                if role == "forbidden"
                else Qt.ArrowCursor
                if role == "arrow"
                else Qt.PointingHandCursor
                if button.isEnabled()
                else Qt.ArrowCursor
            )
            assert button.cursor().shape() == expected, (
                button.objectName(),
                button.text(),
                role,
                button.isEnabled(),
            )

        disabled = next(button for button in buttons if button.isEnabled())
        disabled.setEnabled(False)
        app.processEvents()
        assert disabled.cursor().shape() == Qt.ArrowCursor
        disabled.setEnabled(True)
        app.processEvents()
        assert disabled.cursor().shape() == Qt.PointingHandCursor
        window.close()
    app.processEvents()


def test_every_settings_dropdown_uses_the_shared_premium_picker():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch("voicepilot.settings_dictation_page.list_audio_devices", return_value=[]),
        ):
            window = SettingsWindow(path)

        window.show()
        app.processEvents()
        combos = window.window.findChildren(QComboBox)
        assert combos
        from voicepilot.settings_combo_widgets import SETTINGS_COMBO_HEIGHT, SETTINGS_COMBO_WIDTH

        assert all(combo.objectName() in {"AppearanceCombo", "SettingsCombo"} for combo in combos)
        assert {(combo.width(), combo.height()) for combo in combos} == {(SETTINGS_COMBO_WIDTH, SETTINGS_COMBO_HEIGHT)}
        assert all(combo.cursor().shape() == Qt.PointingHandCursor for combo in combos)
        assert all(combo.view().objectName() == "SettingsComboPopupList" for combo in combos)
        assert all(combo._settings_popup.cursor().shape() == Qt.ArrowCursor for combo in combos)
        assert all(combo.view().cursor().shape() == Qt.ArrowCursor for combo in combos)
        assert all(combo.view().viewport().cursor().shape() == Qt.ArrowCursor for combo in combos)
        picker = combos[0]
        if picker.count() > 1:
            QTest.mouseClick(
                picker,
                Qt.LeftButton,
                Qt.NoModifier,
                QPoint(picker.width() - 12, picker.height() // 2),
            )
            app.processEvents()
            assert picker._settings_popup.isVisible()
            assert picker.view().viewport().cursor().shape() == Qt.ArrowCursor
            QTest.mouseClick(
                picker,
                Qt.LeftButton,
                Qt.NoModifier,
                QPoint(picker.width() - 12, picker.height() // 2),
            )
            app.processEvents()
            assert not picker._settings_popup.isVisible()

            # Reproduce Windows' real Qt.Popup ordering: the native window
            # closes first, then the same click reaches the combo owner.
            picker.showPopup()
            app.processEvents()
            assert picker._settings_popup.isVisible()
            picker._settings_popup.hide()
            app.processEvents()
            QTest.mouseClick(
                picker,
                Qt.LeftButton,
                Qt.NoModifier,
                QPoint(picker.width() - 12, picker.height() // 2),
            )
            app.processEvents()
            assert not picker._settings_popup.isVisible()

            hovered = picker.model().index(1, 0)
            picker.view().entered.emit(hovered)
            assert picker.view().hovered_row == 1
            assert picker.cursor().shape() == Qt.PointingHandCursor
            assert picker._settings_popup.cursor().shape() == Qt.ArrowCursor
            assert picker.view().cursor().shape() == Qt.ArrowCursor
            assert picker.view().viewport().cursor().shape() == Qt.PointingHandCursor
            assert window.window.cursor().shape() == Qt.ArrowCursor
            picker.view().viewportEntered.emit()
            assert picker.view().hovered_row == -1
            assert picker.view().cursor().shape() == Qt.ArrowCursor
            assert picker.view().viewport().cursor().shape() == Qt.ArrowCursor
        window.close()
    app.processEvents()


def test_dictation_page_is_consumer_focused_and_uses_structured_controls():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton
    from voicepilot.models import find_speech_model
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch("voicepilot.settings_dictation_page.list_audio_devices", return_value=["Microphone Array"]),
            patch(
                "voicepilot.settings_speech_models_page.acceleration_status",
                return_value=SimpleNamespace(
                    gpu=SimpleNamespace(name="Test NVIDIA GPU"),
                    verified=True,
                ),
            ),
        ):
            window = SettingsWindow(path)
        window.show()
        window._show_named_page("Dictation")
        app.processEvents()

        page = window.stack.currentWidget()
        panels = page.findChildren(QFrame, "DictationPanel")
        quality_selector = page.findChild(QFrame, "QualitySelector")
        shortcut_panel = page.findChild(QFrame, "DictationShortcutPanel")
        quality_options = page.findChildren(QPushButton, "QualityOption")
        labels = {label.text() for label in page.findChildren(QLabel)}
        buttons = {button.text(): button for button in page.findChildren(QPushButton)}

        assert len(panels) == 2
        assert quality_selector is not None
        assert shortcut_panel is not None
        assert page.findChild(QFrame, "DictationSetupCard") is None
        assert [button.text() for button in quality_options if not button.isHidden()] == [
            "Fast",
            "Balanced",
            "Best quality",
            "Custom",
        ]
        custom = quality_options[-1]
        assert custom.focusPolicy() == Qt.NoFocus
        assert custom.cursor().shape() == Qt.ArrowCursor
        assert custom.testAttribute(Qt.WA_TransparentForMouseEvents)
        assert not custom.isChecked()
        assert sum(button.isChecked() for button in quality_options if not button.isHidden()) == 1
        assert "Voice setup" in labels
        assert {"Shortcuts", "Dictate", "Cancel", "Tap to keep listening", "Spoken formatting"} <= labels
        spoken_label = next(label for label in page.findChildren(QLabel) if label.text() == "Spoken formatting")
        assert shortcut_panel.isAncestorOf(spoken_label)
        quality_summary = page.findChild(QLabel, "QualitySummary").text()
        assert " - " in quality_summary
        current_model = find_speech_model(window.config.dictation.ramble_model)
        assert current_model is not None and current_model.label in quality_summary
        assert "Change shortcuts" not in buttons
        assert "Apply" not in buttons
        assert "Advanced" in buttons
        assert buttons["Advanced"].objectName() == "QualityAdvancedButton"
        assert "hotkeys.dictate" in window.widgets
        assert "hotkeys.cancel" in window.widgets
        assert "hotkeys.tap_to_toggle_dictation" in window.widgets
        dictate = window.widgets["hotkeys.dictate"]
        cancel = window.widgets["hotkeys.cancel"]
        tap_toggle = window.widgets["hotkeys.tap_to_toggle_dictation"]
        QTest.mouseClick(dictate, Qt.LeftButton)
        QTest.keyClick(dictate, Qt.Key_F8)
        QTest.mouseClick(cancel, Qt.LeftButton)
        QTest.keyClick(cancel, Qt.Key_Escape, Qt.ControlModifier | Qt.MetaModifier)
        tap_toggle.setChecked(False)
        with (
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window._save(silent=True)
        saved = load_config(path)
        assert saved.hotkeys.dictate == "f8"
        assert saved.hotkeys.cancel == "ctrl+win+esc"
        assert saved.hotkeys.tap_to_toggle_dictation is False
        assert "Polish" not in labels
        assert "NVIDIA" not in " ".join(labels)
        assert "CUDA" not in " ".join(labels)
        with patch(
            "voicepilot.settings_speech_models_page.acceleration_status",
            return_value=SimpleNamespace(
                gpu=SimpleNamespace(name="Test NVIDIA GPU"),
                verified=True,
            ),
        ):
            buttons["Advanced"].click()
            app.processEvents()
        assert window._advanced_dialog.windowTitle() == "Winsper Dictation models"
        advanced_labels = {label.text() for label in window._advanced_dialog.findChildren(QLabel)}
        assert {
            "Dictation models",
            "CURRENT SETUP",
            "Speech setup",
            "Transcription model",
            "Hardware acceleration",
        } <= advanced_labels
        assert "I speak" not in advanced_labels
        assert "Choose a compatible local model for your Dictation language." not in advanced_labels
        assert not any("Change language on the Dictation page." in label for label in advanced_labels)
        storage_panel = window._advanced_dialog.findChild(QFrame, "ModelStoragePanel")
        acceleration_panel = window._advanced_dialog.findChild(
            QFrame,
            "HardwareAccelerationPanel",
        )
        assert storage_panel is not None
        assert acceleration_panel is not None
        assert acceleration_panel.isHidden()
        advanced_layout = storage_panel.parentWidget().layout()
        assert advanced_layout.indexOf(storage_panel) < advanced_layout.indexOf(acceleration_panel)
        assert "Polish AI" not in advanced_labels
        advanced_buttons = window._advanced_dialog.findChildren(QPushButton)
        assert "Refresh" not in {button.text() for button in advanced_buttons}
        assert "Check again" not in {button.text() for button in advanced_buttons}
        assert "Use model" not in {button.text() for button in advanced_buttons}
        assert "In use" not in {button.text() for button in advanced_buttons}
        model_actions = [button for button in advanced_buttons if button.text() in {"Download model", "Install Parakeet support"}]
        assert sum(button.isVisible() for button in model_actions) <= 1
        window.close()
    app.processEvents()


def test_dictation_page_does_not_wait_for_microphone_discovery():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from threading import Event
    from time import perf_counter

    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    scan_started = Event()
    release_scan = Event()
    scan_finished = Event()

    def slow_scan():
        scan_started.set()
        release_scan.wait(10)
        scan_finished.set()
        return ["Late microphone"]

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with patch.object(SettingsWindow, "_refresh_home_status"):
            window = SettingsWindow(path)
        try:
            with patch(
                "voicepilot.settings_dictation_page.list_audio_devices",
                side_effect=slow_scan,
            ):
                started_at = perf_counter()
                window._show_named_page("Dictation")
                elapsed = perf_counter() - started_at

            assert scan_started.wait(0.5)
            assert elapsed < 5
            assert not scan_finished.is_set()
        finally:
            release_scan.set()
            QTest.qWait(50)
            window.close()
    app.processEvents()


def test_missing_dictation_quality_opens_advanced_without_activating_model():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)

        def install_state(preset, **_kwargs):
            return SimpleNamespace(installed=preset.model == "small.en")

        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch("voicepilot.settings_dictation_page.list_audio_devices", return_value=["Microphone Array"]),
            patch("voicepilot.settings_dictation_page.installed_status", side_effect=install_state),
            patch("voicepilot.settings_dictation_page.engine_runtime_available", return_value=True),
            patch("voicepilot.settings_speech_models_page.installed_status", side_effect=install_state),
            patch("voicepilot.settings_speech_models_page.engine_runtime_available", return_value=True),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command") as control,
        ):
            window = SettingsWindow(path)
            window.show()
            window._show_named_page("Dictation")
            app.processEvents()

            page = window.stack.currentWidget()
            balanced = next(button for button in page.findChildren(QPushButton, "QualityOption") if button.text() == "Balanced")
            fast = next(button for button in page.findChildren(QPushButton, "QualityOption") if button.text() == "Fast")
            assert balanced.isChecked()
            quality_summary = page.findChild(QLabel, "QualitySummary")

            control.reset_mock()
            QTest.mouseClick(fast, Qt.LeftButton)
            app.processEvents()

            assert window._advanced_dialog is not None
            assert window._advanced_dialog.isVisible()
            assert window.language_model_combo.currentData() == "base.en"
            download = next(
                button for button in window._advanced_dialog.findChildren(QPushButton) if button.text().startswith("Download Whisper Base")
            )
            assert download.isVisible()
            assert "Whisper Small" in quality_summary.text()
            assert download.parentWidget() is window._advanced_dialog.findChild(QFrame, "ModelSummary")
            assert "Whisper Base" not in quality_summary.text()
            assert balanced.isChecked()
            assert not fast.isChecked()
            assert "Download required" not in quality_summary.text()
            assert "current model remains active" not in quality_summary.text()
            assert window.config.speech.model == "small.en"
            assert load_config(path).speech.model == "small.en"
            control.assert_not_called()
            window._advanced_dialog.close()
            app.processEvents()
            assert balanced.isChecked()
            assert not fast.isChecked()
            window.close()
    app.processEvents()


def test_advanced_ready_model_auto_saves_and_syncs_dictation_page():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        ready = SimpleNamespace(installed=True)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch("voicepilot.settings_dictation_page.list_audio_devices", return_value=["Microphone Array"]),
            patch("voicepilot.settings_speech_models_page.installed_status", return_value=ready),
            patch("voicepilot.settings_speech_models_page.engine_runtime_available", return_value=True),
            patch("voicepilot.settings_model_selection_actions.installed_status", return_value=ready),
            patch("voicepilot.settings_model_selection_actions.engine_runtime_available", return_value=True),
            patch(
                "voicepilot.settings_speech_models_page.acceleration_status",
                return_value=SimpleNamespace(gpu=None, verified=False),
            ),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window = SettingsWindow(path)
            window.show()
            window._show_named_page("Dictation")
            app.processEvents()
            window._open_advanced_models()
            app.processEvents()

            french = window.language_combo.findData("fr")
            assert french >= 0
            window.language_combo.setCurrentIndex(french)
            app.processEvents()

            assert window.config.speech.language == "fr"
            assert window.dictation_language_combo.currentData() == "fr"
            assert load_config(path).speech.language == "fr"
            assert all(
                button.text() not in {"Use model", "In use", "Check again"} for button in window._advanced_dialog.findChildren(QPushButton)
            )
            window.close()
    app.processEvents()


def test_dictation_quality_shows_exact_custom_model_state():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.speech.model = "distil-small.en"
        config.dictation.ramble_model = "distil-small.en"
        save_config(config, path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch("voicepilot.settings_dictation_page.list_audio_devices", return_value=["Microphone Array"]),
        ):
            window = SettingsWindow(path)
        window.show()
        window._show_named_page("Dictation")
        app.processEvents()

        visible = [
            button
            for button in window.stack.currentWidget().findChildren(
                QPushButton,
                "QualityOption",
            )
            if not button.isHidden()
        ]
        assert [button.text() for button in visible[:3]] == [
            "Fast",
            "Balanced",
            "Best quality",
        ]
        assert visible[3].text().startswith("Custom · ")
        assert visible[3].isChecked()
        assert not any(button.isChecked() for button in visible[:3])
        window.close()
    app.processEvents()


def test_dictation_quality_preset_updates_shared_speech_model():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.dictation.polish_model = "medium.en"
        config.dictation.rewrite_instruction_model = "tiny.en"
        save_config(config, path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch(
                "voicepilot.settings_dictation_page.installed_status",
                return_value=SimpleNamespace(installed=True),
            ),
            patch(
                "voicepilot.settings_dictation_page.engine_runtime_available",
                return_value=True,
            ),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window = SettingsWindow(path)
            window._show_named_page("Dictation")
            app.processEvents()
            fast = next(
                button
                for button in window.stack.currentWidget().findChildren(
                    QPushButton,
                    "QualityOption",
                )
                if button.text() == "Fast"
            )
            fast.click()
            app.processEvents()

        saved = load_config(path)
        assert saved.speech.model == "base.en"
        assert saved.dictation.ramble_model == "base.en"
        assert saved.dictation.polish_model == "base.en"
        assert saved.dictation.rewrite_instruction_model == "base.en"
        window.close()
    app.processEvents()


def test_language_change_preserves_compatible_custom_dictation_model():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.speech.language = "en"
        config.speech.model = "small"
        config.dictation.ramble_model = "small"
        save_config(config, path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch(
                "voicepilot.settings_dictation_page.installed_status",
                return_value=SimpleNamespace(installed=True),
            ),
            patch(
                "voicepilot.settings_dictation_page.engine_runtime_available",
                return_value=True,
            ),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window = SettingsWindow(path)
            window._show_named_page("Dictation")
            french = window.dictation_language_combo.findData("fr")
            assert french >= 0
            window.dictation_language_combo.setCurrentIndex(french)
            app.processEvents()

        saved = load_config(path)
        assert saved.speech.language == "fr"
        assert saved.speech.model == "small"
        assert saved.dictation.ramble_model == "small"
        window.close()
    app.processEvents()


def test_language_change_replaces_incompatible_custom_dictation_model():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication
    from voicepilot.models import find_speech_model
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.speech.language = "en"
        config.speech.engine = "sherpa_onnx"
        config.speech.model = "parakeet-tdt-0.6b-v2-int8"
        config.dictation.ramble_model = config.speech.model
        save_config(config, path)
        ready = SimpleNamespace(installed=True)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch(
                "voicepilot.settings_dictation_page.recommended_model_for_language",
                return_value=find_speech_model("small"),
            ),
            patch(
                "voicepilot.settings_dictation_page.installed_status",
                return_value=ready,
            ),
            patch(
                "voicepilot.settings_dictation_page.engine_runtime_available",
                return_value=True,
            ),
            patch(
                "voicepilot.settings_model_selection_actions.installed_status",
                return_value=ready,
            ),
            patch(
                "voicepilot.settings_model_selection_actions.engine_runtime_available",
                return_value=True,
            ),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window = SettingsWindow(path)
            window._show_named_page("Dictation")
            french = window.dictation_language_combo.findData("fr")
            assert french >= 0
            window.dictation_language_combo.setCurrentIndex(french)
            app.processEvents()

        saved = load_config(path)
        assert saved.speech.language == "fr"
        assert saved.speech.model == "small"
        assert saved.dictation.ramble_model == "small"
        window.close()
    app.processEvents()
