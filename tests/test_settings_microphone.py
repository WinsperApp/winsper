import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from voicepilot.config import AppConfig, load_config, save_config


def test_settings_microphone_route_rejects_unsafe_bluetooth_capture():
    from voicepilot.settings_microphone import microphone_home_status
    from voicepilot.system_audio import resolve_microphone_route

    airpods = "Headset (AirPods Pro), Windows WASAPI"
    realtek = "Microphone Array (Realtek(R) Audio), Windows WASAPI"

    route = resolve_microphone_route(airpods, [airpods, realtek])
    assert route.preferred is None
    assert route.active == realtek
    assert route.preferred_available
    assert not route.using_fallback

    windows_default = resolve_microphone_route(None, [realtek])
    assert windows_default.preferred is None
    assert windows_default.active == realtek
    assert not windows_default.using_fallback
    assert microphone_home_status(airpods, [realtek]) == (
        "Microphone Array (Realtek(R) Audio)",
        "",
        "neutral",
    )
    assert microphone_home_status(airpods, []) == (
        "No microphone found",
        "Check Windows sound settings.",
        "bad",
    )


def test_dictation_page_normalizes_bluetooth_preference_to_automatic():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.audio.input_device = "Headset (AirPods Pro), Windows WASAPI"
        save_config(config, path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch(
                "voicepilot.settings_dictation_page.list_audio_devices",
                return_value=["Microphone Array (Realtek(R) Audio), Windows WASAPI"],
            ),
        ):
            window = SettingsWindow(path)
            window.show()
            window._show_named_page("Dictation")
            QTest.qWait(100)

            combo = next(
                item
                for item in window.stack.currentWidget().findChildren(QComboBox)
                if item.accessibleName() == "Microphone"
            )
            status = window.stack.currentWidget().findChild(QLabel, "MicrophoneRouteStatus")
            assert status is not None
            assert combo.currentText() == "Microphone Array (Realtek(R) Audio)"
            assert combo.property("preferredMicrophone") == "Windows default"
            assert "Currently using Microphone Array" in combo.accessibleDescription()
            assert status.isHidden()
            assert status.text() == ""

            window._save(silent=True)
            assert load_config(path).audio.input_device is None

            automatic = combo.findData("Windows default")
            assert automatic >= 0
            combo.activated.emit(automatic)
            QTest.qWait(20)
            assert combo.currentText() == "Microphone Array (Realtek(R) Audio)"
            assert load_config(path).audio.input_device is None
            window.close()
    app.processEvents()


def test_dictation_page_only_surfaces_a_real_microphone_failure():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel
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
            window._show_named_page("Dictation")
            QTest.qWait(100)

            combo = next(
                item
                for item in window.stack.currentWidget().findChildren(QComboBox)
                if item.accessibleName() == "Microphone"
            )
            status = window.stack.currentWidget().findChild(QLabel, "MicrophoneRouteStatus")
            assert combo.currentText() == "No microphone found"
            assert not combo.isEnabled()
            assert status is not None
            assert status.text() == "Check Windows sound settings."
            assert status.isVisible()
            assert status.property("tone") == "bad"
            window.close()
    app.processEvents()
