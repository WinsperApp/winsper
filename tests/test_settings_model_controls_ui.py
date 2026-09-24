import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from voicepilot.config import AppConfig, load_config, save_config


def test_advanced_missing_model_is_staged_without_replacing_active_dictation_quality():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
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
            page = window.stack.currentWidget()
            window._open_advanced_models()
            app.processEvents()

            missing = window.language_model_combo.findData("parakeet-tdt-0.6b-v2-int8")
            assert missing >= 0
            window.language_model_combo.setCurrentIndex(missing)
            app.processEvents()

            summary = page.findChild(QLabel, "QualitySummary")
            balanced = next(button for button in page.findChildren(QPushButton, "QualityOption") if button.text() == "Balanced")
            custom = next(button for button in page.findChildren(QPushButton, "QualityOption") if button.text().startswith("Custom"))
            assert summary.text().endswith(" - Whisper Small · English")
            assert balanced.isChecked()
            assert window._advanced_dialog is not None
            assert window._advanced_dialog.isVisible()
            download = next(button for button in window._advanced_dialog.findChildren(QPushButton) if button.text().startswith("Download Parakeet v2"))
            assert download.isVisible()
            window._advanced_dialog.close()
            app.processEvents()
            assert balanced.isChecked()
            assert not custom.isChecked()
            assert custom.text().startswith("Custom")
            assert summary.text().endswith(" - Whisper Small · English")
            assert window.config.speech.model == "small.en"
            assert load_config(path).speech.model == "small.en"

            ready = window.language_model_combo.findData("small.en")
            assert ready >= 0
            window.language_model_combo.setCurrentIndex(ready)
            app.processEvents()
            assert summary.text().endswith(" - Whisper Small · English")
            window.close()
def test_installed_advanced_model_persists_as_custom_quality():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)

        def install_state(preset, **_kwargs):
            return SimpleNamespace(installed=preset.model in {"small.en", "parakeet-tdt-0.6b-v2-int8"})

        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch("voicepilot.settings_dictation_page.list_audio_devices", return_value=["Microphone Array"]),
            patch("voicepilot.settings_dictation_page.installed_status", side_effect=install_state),
            patch("voicepilot.settings_dictation_page.engine_runtime_available", return_value=True),
            patch("voicepilot.settings_model_selection_actions.installed_status", side_effect=install_state),
            patch("voicepilot.settings_model_selection_actions.engine_runtime_available", return_value=True),
            patch("voicepilot.settings_speech_models_page.installed_status", side_effect=install_state),
            patch("voicepilot.settings_speech_models_page.engine_runtime_available", return_value=True),
            patch("voicepilot.settings_speech_models_page.acceleration_status", return_value=SimpleNamespace(gpu=None, verified=False)),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window = SettingsWindow(path)
            window.show()
            window._show_named_page("Dictation")
            window._open_advanced_models()
            app.processEvents()
            index = window.language_model_combo.findData("parakeet-tdt-0.6b-v2-int8")
            window.language_model_combo.setCurrentIndex(index)
            app.processEvents()
            window._advanced_dialog.close()
            app.processEvents()

            page = window.stack.currentWidget()
            custom = next(button for button in page.findChildren(QPushButton, "QualityOption") if button.text().startswith("Custom"))
            summary = page.findChild(QLabel, "QualitySummary")
            assert custom.isChecked()
            assert "Parakeet v2" in custom.text()
            assert "Parakeet v2" in summary.text()
            saved = load_config(path)
            assert saved.dictation.ramble_model == "parakeet-tdt-0.6b-v2-int8"
            assert saved.dictation.quality_profile == "custom"
            window.close()
    app.processEvents()


    app.processEvents()


def test_advanced_models_exposes_real_model_storage_control():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFrame
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.model_storage.path = str(Path(temp) / "custom-models")
        save_config(config, path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch(
                "voicepilot.settings_speech_models_page.acceleration_status",
                return_value=SimpleNamespace(gpu=None, verified=False),
            ),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch(
                "voicepilot.settings_model_storage_actions.default_huggingface_cache_root",
                return_value=Path(temp) / "default-speech",
            ),
            patch(
                "voicepilot.settings_model_storage_actions.default_local_ai_root",
                return_value=Path(temp) / "default-polish",
            ),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window = SettingsWindow(path)
            window.show()
            window._open_advanced_models()
            app.processEvents()

            assert window.model_storage_path_label.toolTip() == str((Path(temp) / "custom-models").resolve())
            assert window.model_storage_badge.isHidden()
            assert not window.model_storage_default_button.isHidden()
            assert window.model_storage_browse_button.text() == "Browse"
            assert window.model_storage_progress.objectName() == "ModelDownloadFeedback"
            assert window.model_storage_progress.isHidden()
            acceleration_panel = window._advanced_dialog.findChild(
                QFrame,
                "HardwareAccelerationPanel",
            )
            assert acceleration_panel is not None and acceleration_panel.isHidden()

            window.model_storage_default_button.click()
            app.processEvents()
            QTest.qWait(250)
            assert load_config(path).model_storage.path == ""
            window.close()
    app.processEvents()


def test_dictation_and_cached_advanced_language_stay_in_sync_repeatedly():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        ready = SimpleNamespace(installed=True)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch(
                "voicepilot.settings_dictation_page.list_audio_devices",
                return_value=["Microphone Array"],
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
                "voicepilot.settings_speech_models_page.installed_status",
                return_value=ready,
            ),
            patch(
                "voicepilot.settings_speech_models_page.engine_runtime_available",
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
            window._open_advanced_models()
            app.processEvents()

            for language_code in ("fr", "hi", "es"):
                dictation_index = window.dictation_language_combo.findData(language_code)
                assert dictation_index >= 0
                window.dictation_language_combo.setCurrentIndex(dictation_index)
                app.processEvents()
                assert window.config.speech.language == language_code
                assert window.language_combo.currentData() == language_code
                assert load_config(path).speech.language == language_code

            window.close()
    app.processEvents()


def test_closed_settings_dropdown_ignores_mouse_wheel_changes():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with patch.object(SettingsWindow, "_refresh_home_status"):
            window = SettingsWindow(path)
        combo = window.widgets["hud.theme"]
        combo.setCurrentIndex(1)
        before = combo.currentIndex()
        local = QPointF(combo.rect().center())
        global_point = QPointF(combo.mapToGlobal(combo.rect().center()))
        wheel = QWheelEvent(
            local,
            global_point,
            QPoint(),
            QPoint(0, -120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(combo, wheel)
        assert combo.currentIndex() == before
        window.close()
    app.processEvents()


def test_model_download_completion_is_clear_and_transient():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QProgressBar
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch(
                "voicepilot.settings_speech_models_page.acceleration_status",
                return_value=SimpleNamespace(gpu=None, verified=False),
            ),
        ):
            window = SettingsWindow(path)
            window.show()
            window._open_advanced_models()
            app.processEvents()

        feedback = window._advanced_dialog.findChild(
            QFrame,
            "ModelDownloadFeedback",
        )
        status = window._advanced_dialog.findChild(QLabel, "ModelDownloadStatus")
        value = window._advanced_dialog.findChild(QLabel, "ModelDownloadValue")
        meta = window._advanced_dialog.findChild(QLabel, "ModelDownloadMeta")
        progress = window._advanced_dialog.findChild(
            QProgressBar,
            "ModelDownloadProgress",
        )
        assert feedback is not None
        assert status is not None
        assert value is not None
        assert meta is not None
        assert progress is not None

        feedback.show()
        progress.show()
        progress._winsper_feedback_token = 7
        window.model_download_running = True
        window.model_download_events.put(("done", "Download complete."))
        window._poll_model_download(status, progress)
        app.processEvents()

        assert status.text() == "Download complete"
        assert status.property("tone") == "good"
        assert value.text() == "Ready"
        assert value.property("tone") == "accent"
        assert meta.text() == "Installed locally and selected."
        assert progress.value() == 100
        assert not progress.isTextVisible()
        assert feedback.isVisible()

        QTest.qWait(1500)
        assert not feedback.isVisible()
        window.close()
    app.processEvents()


def test_model_download_pause_resume_and_cancel_controls():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch(
                "voicepilot.settings_speech_models_page.acceleration_status",
                return_value=SimpleNamespace(gpu=None, verified=False),
            ),
        ):
            window = SettingsWindow(path)
            window.show()
            window._open_advanced_models()
            app.processEvents()

        status = window._advanced_dialog.findChild(QLabel, "ModelDownloadStatus")
        meta = window._advanced_dialog.findChild(QLabel, "ModelDownloadMeta")
        progress = window._advanced_dialog.findChild(
            QProgressBar,
            "ModelDownloadProgress",
        )
        controls = window._advanced_dialog.findChildren(
            QPushButton,
            "DownloadControlButton",
        )
        pause_button = next(button for button in controls if button.text() == "Pause")
        cancel_button = next(button for button in controls if button.text() == "Cancel")
        action_button = QPushButton("Download model", window._advanced_dialog)
        assert status is not None
        assert meta is not None
        assert progress is not None

        with patch.object(window, "_launch_model_download_worker") as launch:
            window._start_model_download(
                "small.en",
                status,
                progress,
                action_button=action_button,
            )
            assert launch.call_count == 1
            assert pause_button.isEnabled()
            assert cancel_button.isEnabled()

            pause_button.click()
            assert window.model_download_pause_event.is_set()
            assert window.model_download_paused
            assert pause_button.text() == "Resume"
            assert "preserved" in meta.text()

            pause_button.click()
            assert launch.call_count == 1
            assert window.model_download_running
            assert not window.model_download_paused
            assert not window.model_download_pause_event.is_set()
            assert pause_button.text() == "Pause"

            cancel_button.click()
            assert window.model_download_cancel_event.is_set()
            window.model_download_events.put(("cancelled", None))
            window._poll_model_download(
                status,
                progress,
                action_button=action_button,
            )

        assert not window.model_download_running
        assert not window.model_download_paused
        assert status.text() == "Download cancelled"
        assert action_button.isEnabled()
        assert window._model_download_context is None
        window.close()
    app.processEvents()
