import os
from threading import Event
from time import sleep
from unittest.mock import patch

from voicepilot.config import AppConfig, save_config


def test_dictation_page_does_not_probe_hardware_during_open(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])

    probe_started = Event()

    def slow_hardware_probe():
        probe_started.set()
        sleep(1)
        raise AssertionError("Dictation page opening must not probe hardware")

    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    with (
        patch.object(SettingsWindow, "_refresh_home_status"),
        patch(
            "voicepilot.settings_dictation_page.list_audio_devices",
            return_value=["Microphone Array"],
        ),
        patch(
            "voicepilot.speed_lab.detect_hardware",
            side_effect=slow_hardware_probe,
        ),
        patch(
            "voicepilot.settings_dictation_page.detect_hardware",
            side_effect=slow_hardware_probe,
        ),
    ):
        window = SettingsWindow(path)
        try:
            window._show_named_page("Dictation")
            app.processEvents()
            assert not probe_started.is_set()
        finally:
            window.close()
    app.processEvents()
