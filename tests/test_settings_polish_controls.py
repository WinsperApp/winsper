from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from voicepilot.config import AppConfig, load_config, save_config


def test_ollama_model_choices_only_show_detected_or_configured_models():
    from voicepilot.settings_helpers import ollama_combo_values

    assert ollama_combo_values([], "qwen2.5:1.5b") == []
    assert ollama_combo_values(["qwen3:4b", "qwen3:8b"], "old-model:latest") == [
        "qwen3:4b",
        "qwen3:8b",
    ]


def test_polish_acceleration_download_exposes_real_cancel_control():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QPushButton
    from voicepilot.ai_catalog import runtime_bundle
    from voicepilot.ai_hardware import AIGpu, AIHardware
    from voicepilot.ollama import OllamaHealth
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        hardware = AIHardware(
            "x64",
            "CPU",
            16,
            (AIGpu("NVIDIA RTX Test", "nvidia", 8, "CUDA0"),),
        )
        cuda = runtime_bundle("cuda12-x64")
        health = OllamaHealth(False, False, "", (), "http://localhost")
        with (
            patch("voicepilot.settings_rewrite_ollama.check_ollama_health", return_value=health),
            patch("voicepilot.settings_rewrite_acceleration.detect_ai_hardware_quick", return_value=hardware),
            patch("voicepilot.settings_rewrite_acceleration.runtime_candidates", return_value=[cuda]),
            patch("voicepilot.settings_rewrite_acceleration.runtime_is_installed", return_value=False),
            patch("voicepilot.settings_rewrite_embedded.ollama_model_candidate", return_value=None),
            patch("voicepilot.settings_rewrite_acceleration.Thread") as thread,
        ):
            window = SettingsWindow(path)
            window.show()
            window._open_advanced_polish_ai()
            app.processEvents()
            dialog = window._advanced_dialog
            action = dialog.findChild(QAbstractButton, "HardwareAccelerationToggle")
            cancel = next(
                button
                for button in dialog.findChildren(QPushButton, "DownloadControlButton")
                if button.accessibleName() == "Cancel acceleration download"
            )

            QTest.mouseClick(action, Qt.LeftButton)
            app.processEvents()
            assert window.ai_runtime_cancel_event is not None
            assert not cancel.isHidden()
            assert cancel.isEnabled()
            thread.return_value.start.assert_called_once_with()

            QTest.mouseClick(cancel, Qt.LeftButton)
            assert window.ai_runtime_cancel_event.is_set()
            assert not cancel.isEnabled()
            window.close()
    app.processEvents()


def test_unavailable_best_polish_quality_shows_download_without_changing_active_mode():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton
    from voicepilot.ollama import OllamaHealth
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.rewrite.provider = "embedded"
        config.rewrite.llama_model_id = "qwen3-4b-instruct-2507-q4km"
        save_config(config, path)
        health = OllamaHealth(False, False, "", (), "http://localhost")
        with (
            patch(
                "voicepilot.settings_polish_page.model_is_installed",
                side_effect=lambda model: model.id == "qwen3-4b-instruct-2507-q4km",
            ),
            patch("voicepilot.settings_rewrite_ollama.check_ollama_health", return_value=health),
            patch("voicepilot.settings_rewrite_embedded.model_is_installed", return_value=False),
            patch("voicepilot.settings_rewrite_embedded.ollama_model_candidate", return_value=None),
            patch("voicepilot.ai_runtime.model_is_installed", return_value=False),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window = SettingsWindow(path)
            window.show()
            window._show_named_page("Polish")
            app.processEvents()

            page = window.stack.currentWidget()
            quality = page.findChildren(QPushButton, "PolishQualityOption")
            balanced = next(button for button in quality if button.text() == "Balanced")
            best = next(button for button in quality if button.text() == "Best quality")
            assert balanced.isChecked()
            window._open_advanced_polish_ai()
            app.processEvents()
            assert window._advanced_dialog.isVisible()

            QTest.mouseClick(best, Qt.LeftButton)
            app.processEvents()

            saved = load_config(path)
            assert saved.rewrite.llama_model_id == "qwen3-4b-instruct-2507-q4km"
            assert balanced.isChecked()
            assert not best.isChecked()
            assert window.widgets["rewrite.llama_model_id"].currentText() == "qwen3-8b-q4km"
            summary = window._advanced_dialog.findChild(QFrame, "ModelSummary")
            status = summary.findChild(QLabel, "ModelSummaryText")
            download = summary.findChild(QPushButton, "ModelDownloadButton")
            assert "Qwen 3 8B" in status.text()
            assert download.text() == "Download model"
            assert download.isVisible()

            # Allow any delayed autosave to run before closing. The selected
            # working model must still be restored when Best remains missing.
            QTest.qWait(650)
            window._advanced_dialog.close()
            app.processEvents()
            saved = load_config(path)
            assert saved.rewrite.llama_model_id == "qwen3-4b-instruct-2507-q4km"
            assert balanced.isChecked()
            assert not best.isChecked()
            custom = next(button for button in quality if button.text() == "Custom")
            assert not custom.isChecked()
            assert window.widgets["rewrite.llama_model_id"].currentText() == "qwen3-4b-instruct-2507-q4km"
            window.close()
    app.processEvents()


def test_ollama_success_status_uses_accent_tone():
    from voicepilot.ollama import OllamaHealth
    from voicepilot.settings_helpers import ollama_status_text, ollama_tone

    health = OllamaHealth(
        True,
        True,
        "custom-polish:latest",
        ("custom-polish:latest",),
        "http://localhost:11434/api/tags",
    )
    assert ollama_status_text(health) == "Ollama connection established · custom-polish:latest"
    assert ollama_tone(health) == "accent"


def test_polish_custom_local_model_is_an_explicit_choice():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QFileDialog, QComboBox, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        model_path = Path(temp) / "my-polish-model.gguf"
        model_path.write_bytes(b"GGUF")
        save_config(AppConfig(), path)
        with (
            patch.object(QFileDialog, "getOpenFileName", return_value=(str(model_path), "GGUF models (*.gguf)")),
            patch("voicepilot.settings_rewrite_embedded.ollama_model_candidate", return_value=None),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window = SettingsWindow(path)
            window.show()
            window._show_named_page("Polish")
            window._open_advanced_polish_ai()
            app.processEvents()
            model_selector = next(
                combo for combo in window._advanced_dialog.findChildren(QComboBox) if combo.accessibleName() == "Polish model"
            )
            custom_index = model_selector.findData("__custom_local_model__")
            assert custom_index >= 0
            model_selector.setCurrentIndex(custom_index)
            app.processEvents()

            saved = load_config(path)
            assert saved.rewrite.provider == "embedded"
            assert saved.rewrite.llama_model_id == ""
            assert saved.rewrite.llama_model_path == str(model_path)
            assert window.widgets["rewrite.llama_model_path"].text() == str(model_path)
            quality = window.stack.currentWidget().findChildren(QPushButton, "PolishQualityOption")
            assert next(button for button in quality if button.text() == "Custom").isChecked()
            window.close()
    app.processEvents()


def test_winsper_ai_success_uses_established_connection_copy():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton
    from voicepilot.llama_server import LlamaServerHealth
    from voicepilot.settings_qt import SettingsWindow

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        health = LlamaServerHealth(True, True, "http://localhost", "Old copy", "Ready")
        with (
            patch("voicepilot.settings_rewrite_embedded.inspect_llama_server", return_value=health),
            patch("voicepilot.settings_rewrite_embedded.threading.Thread", ImmediateThread),
            patch("voicepilot.settings_rewrite_embedded.ollama_model_candidate", return_value=None),
        ):
            window = SettingsWindow(path)
            window._open_advanced_polish_ai()
            connection = window._advanced_dialog.findChild(QFrame, "WinsperProviderConnection")
            check = connection.findChild(QPushButton, "DownloadControlButton")
            QTest.mouseClick(check, Qt.LeftButton)
            QTest.qWait(150)
            status = connection.findChild(QLabel, "StatusPanel")
            assert status.text() == "Winsper AI connection established"
            assert status.property("tone") == "accent"
            detail = connection.findChild(QLabel, "Muted")
            assert detail.isHidden()
            assert detail.text() == ""
            window.close()
    app.processEvents()


def test_explicit_installed_polish_choice_supersedes_pending_download():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.rewrite.llama_model_id = "qwen3-4b-instruct-2507-q4km"
        save_config(config, path)
        installed = {"qwen2.5-1.5b-q4km", "qwen3-4b-instruct-2507-q4km"}
        with (
            patch("voicepilot.settings_polish_page.model_is_installed", side_effect=lambda model: model.id in installed),
            patch("voicepilot.settings_rewrite_embedded.model_is_installed", return_value=False),
            patch("voicepilot.settings_rewrite_embedded.ollama_model_candidate", return_value=None),
            patch("voicepilot.ai_runtime.model_is_installed", return_value=False),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window = SettingsWindow(path)
            window.show()
            window._show_named_page("Polish")
            page = window.stack.currentWidget()
            quality = page.findChildren(QPushButton, "PolishQualityOption")
            best = next(button for button in quality if button.text() == "Best quality")
            fast = next(button for button in quality if button.text() == "Fast")
            QTest.mouseClick(best, Qt.LeftButton)
            app.processEvents()
            assert window._pending_polish_selection is not None

            QTest.mouseClick(fast, Qt.LeftButton)
            app.processEvents()
            assert window._pending_polish_selection is None
            window._advanced_dialog.close()
            app.processEvents()
            saved = load_config(path)
            assert saved.rewrite.llama_model_id == "qwen2.5-1.5b-q4km"
            assert fast.isChecked()
            window.close()
    app.processEvents()
