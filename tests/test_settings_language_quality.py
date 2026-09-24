from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from voicepilot.config import AppConfig, save_config


def test_dictation_language_change_replaces_incompatible_fast_mode():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QPushButton

    from voicepilot.models import HardwareSummary
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.speech.language = "en"
        config.speech.engine = "faster_whisper"
        config.speech.model = "tiny.en"
        config.speech.device = "cpu"
        config.speech.compute_type = "int8"
        config.dictation.ramble_model = "tiny.en"
        save_config(config, path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch(
                "voicepilot.settings_dictation_page.list_audio_devices",
                return_value=["Microphone Array"],
            ),
            patch(
                "voicepilot.settings_dictation_page.detect_hardware",
                return_value=HardwareSummary("Test CPU", 16, (), False, False),
            ),
        ):
            window = SettingsWindow(path)
        window.show()
        window._show_named_page("Dictation")
        app.processEvents()

        page = window.stack.currentWidget()
        language = next(
            combo
            for combo in page.findChildren(QComboBox)
            if combo.findData("hi") >= 0 and combo.findData("en") >= 0
        )
        quality = {
            button.text(): button
            for button in page.findChildren(QPushButton, "QualityOption")
        }
        assert quality["Fast"].isChecked()

        with patch(
            "voicepilot.settings_dictation_page.detect_hardware",
            return_value=HardwareSummary("Test CPU", 16, (), False, False),
        ), patch(
            "voicepilot.settings_dictation_page.installed_status",
            return_value=SimpleNamespace(installed=True),
        ), patch(
            "voicepilot.settings_dictation_page.engine_runtime_available",
            return_value=True,
        ), patch(
            "voicepilot.settings_model_selection_actions.installed_status",
            return_value=SimpleNamespace(installed=True),
        ), patch(
            "voicepilot.settings_model_selection_actions.engine_runtime_available",
            return_value=True,
        ), patch(
            "voicepilot.settings_persistence.set_start_with_windows",
        ), patch(
            "voicepilot.settings_persistence.request_control_command",
        ):
            language.setCurrentIndex(language.findData("hi"))
            app.processEvents()

        assert quality["Fast"].isEnabled()
        assert quality["Fast"].property("unavailable") is True
        assert quality["Fast"].cursor().shape() == Qt.ForbiddenCursor
        assert quality["Balanced"].isChecked()
        QTest.mouseClick(quality["Fast"], Qt.LeftButton)
        app.processEvents()
        assert quality["Balanced"].isChecked()
        assert quality["Fast"].toolTip() == "Fast is not available for this language."
        assert window.config.speech.language == "hi"
        window.close()
    app.processEvents()
