import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from voicepilot.config import AppConfig, load_config, save_config


def test_embedded_polish_settings_persist():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        window._open_advanced_polish_ai()
        app.processEvents()

        with (
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window.widgets["rewrite.provider"].setCurrentText("embedded")
            window.widgets["rewrite.llama_server_path"].setText(r"C:\WinsperAI\llama-server.exe")
            window.widgets["rewrite.llama_model_id"].setCurrentText("qwen3-4b-instruct-2507-q4km")
            window.widgets["rewrite.llama_model_path"].setText(r"C:\WinsperAI\polish.gguf")
            window.widgets["rewrite.llama_device"].setText("Vulkan1")
            window.widgets["rewrite.llama_gpu_layers"].setText("all")
            window._save(silent=True)

        saved = load_config(path)
        assert saved.rewrite.provider == "embedded"
        assert saved.rewrite.llama_server_path == r"C:\WinsperAI\llama-server.exe"
        assert saved.rewrite.llama_model_id == "qwen3-4b-instruct-2507-q4km"
        assert saved.rewrite.llama_model_path == r"C:\WinsperAI\polish.gguf"
        assert saved.rewrite.llama_device == "Vulkan1"
        assert saved.rewrite.llama_gpu_layers == "all"
        window.close()
    app.processEvents()


def test_polish_advanced_hides_engineering_controls_and_syncs_quality():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLabel, QPushButton
    from voicepilot.ollama import OllamaHealth
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        health = OllamaHealth(False, False, "", (), "http://localhost")
        with patch("voicepilot.settings_rewrite_ollama.check_ollama_health", return_value=health):
            window = SettingsWindow(path)
            window.show()
            window._show_named_page("Polish")
            app.processEvents()
            polish_page = window.stack.currentWidget()
            quality = polish_page.findChildren(QPushButton, "PolishQualityOption")
            assert [button.text() for button in quality] == [
                "Fast",
                "Balanced",
                "Best quality",
                "Custom",
            ]
            assert sum(button.isChecked() for button in quality) == 1
            custom = next(button for button in quality if button.text() == "Custom")
            assert custom.testAttribute(Qt.WA_TransparentForMouseEvents)
            window._open_advanced_polish_ai()
            app.processEvents()

        dialog = window._advanced_dialog
        provider = dialog.findChild(QFrame, "ProviderIntro")
        winsper_connection = dialog.findChild(QFrame, "WinsperProviderConnection")
        check = winsper_connection.findChild(QPushButton, "DownloadControlButton")
        assert provider.isVisible()
        assert winsper_connection.isVisible()
        assert check.text() == "Check connection"
        assert check.isVisible()
        assert dialog.findChild(QFrame, "NvidiaAccelerationRow").isVisible()
        assert dialog.findChild(QFrame, "OllamaProviderConnection").isHidden()
        assert dialog.findChild(QFrame, "OllamaProviderSettings").isHidden()
        assert dialog.findChild(QFrame, "TechnicalControls") is None
        assert dialog.findChild(QPushButton, "AdvancedToggle") is None
        assert window.widgets["rewrite.llama_model_id"].isHidden()
        model_selector = next(combo for combo in dialog.findChildren(QComboBox) if combo.accessibleName() == "Polish model")
        assert model_selector.isVisible()
        assert model_selector.currentData() == "qwen3-4b-instruct-2507-q4km"
        assert dialog.findChild(QFrame, "VoiceCommandSafeguards") is None
        provider_buttons = dialog.findChildren(QPushButton, "ProviderOption")
        assert [button.text() for button in provider_buttons] == ["Winsper AI", "Ollama"]
        assert all(button.isVisible() for button in provider_buttons)
        assert not dialog.findChildren(QPushButton, "PolishQualityOption")
        visible_copy = {label.text() for label in dialog.findChildren(QLabel) if label.isVisible()}
        assert "Performance" not in visible_copy
        assert "Preview before apply" not in visible_copy

        fast = next(button for button in quality if button.text() == "Fast")
        with patch("voicepilot.settings_polish_page.model_is_installed", return_value=True):
            QTest.mouseClick(fast, Qt.LeftButton)
        assert window.widgets["rewrite.llama_model_id"].currentText() == "qwen2.5-1.5b-q4km"
        with (
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window._save(silent=True)
        assert load_config(path).rewrite.llama_model_id == "qwen2.5-1.5b-q4km"
        window.close()
    app.processEvents()


def test_polish_advanced_only_claims_nvidia_after_cuda_probe():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel
    from voicepilot.ai_catalog import runtime_bundle
    from voicepilot.ai_hardware import AIGpu, AIHardware
    from voicepilot.ai_runtime import RuntimeProbe
    from voicepilot.ollama import OllamaHealth
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
        hardware = AIHardware(
            "x64",
            "CPU",
            16,
            (AIGpu("NVIDIA RTX Test", "nvidia", 8, "CUDA0"),),
        )
        cuda = runtime_bundle("cuda12-x64")
        health = OllamaHealth(False, False, "", (), "http://localhost")
        probe = RuntimeProbe(
            True,
            "test",
            (("CUDA0", "NVIDIA RTX Test"),),
        )
        with (
            patch("voicepilot.settings_rewrite_ollama.check_ollama_health", return_value=health),
            patch("voicepilot.settings_rewrite_acceleration.detect_ai_hardware_quick", return_value=hardware),
            patch("voicepilot.settings_rewrite_acceleration.runtime_candidates", return_value=[cuda]),
            patch("voicepilot.settings_rewrite_acceleration.runtime_is_installed", return_value=True),
            patch("voicepilot.settings_rewrite_acceleration.probe_runtime", return_value=probe),
            patch("voicepilot.settings_rewrite_acceleration.Thread", ImmediateThread),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window = SettingsWindow(path)
            window._open_advanced_polish_ai()
            QTest.qWait(150)
            app.processEvents()

            dialog = window._advanced_dialog
            status = dialog.findChild(QLabel, "HardwareAccelerationStatus")
            acceleration = dialog.findChild(QAbstractButton, "HardwareAccelerationToggle")
            assert acceleration.accessibleName() == "Use NVIDIA acceleration"
            assert acceleration.isChecked()
            assert acceleration._thumb_progress == 1.0

            QTest.mouseClick(acceleration, Qt.LeftButton)
            app.processEvents()
            assert load_config(path).rewrite.llama_gpu_layers == "0"
            assert "CPU mode active" in status.text()
            assert not acceleration.isChecked()

            QTest.mouseClick(acceleration, Qt.LeftButton)
            QTest.qWait(150)
            app.processEvents()
            assert load_config(path).rewrite.llama_gpu_layers == "auto"

        dialog = window._advanced_dialog
        status = dialog.findChild(QLabel, "HardwareAccelerationStatus")
        acceleration = dialog.findChild(QAbstractButton, "HardwareAccelerationToggle")
        assert status.text() == "NVIDIA RTX Test · NVIDIA acceleration enabled"
        assert acceleration.isChecked()
        window.close()
    app.processEvents()


def test_polish_advanced_recognizes_existing_local_model_path():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from voicepilot.ollama import OllamaHealth
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        model_path = root / "existing-model.gguf"
        model_path.write_bytes(b"existing local model")
        config = AppConfig()
        config.rewrite.provider = "embedded"
        config.rewrite.llama_model_path = str(model_path)
        path = root / "config.yaml"
        save_config(config, path)
        health = OllamaHealth(False, False, "", (), "http://localhost")
        with (
            patch("voicepilot.settings_rewrite_ollama.check_ollama_health", return_value=health),
            patch("voicepilot.settings_rewrite_embedded.ollama_model_candidate", return_value=None),
        ):
            window = SettingsWindow(path)
            window._open_advanced_polish_ai()
            app.processEvents()

        dialog = window._advanced_dialog
        status = dialog.findChild(QLabel, "ModelSummaryText")
        assert status.text() == "Custom local model · Ready"
        managed_actions = {
            button.text(): button
            for button in dialog.findChildren(QPushButton)
            if button.text() in {"Download model", "Repair model", "Remove model"}
        }
        assert managed_actions
        assert all(button.isHidden() for button in managed_actions.values())
        window.close()
    app.processEvents()


def test_polish_advanced_switches_between_embedded_and_ollama_without_false_download_prompt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QFrame, QLabel, QPushButton
    from voicepilot.ollama import OllamaHealth
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        health = OllamaHealth(
            reachable=False,
            model_available=False,
            model="qwen2.5:1.5b",
            models=(),
            tags_url="http://localhost:11434/api/tags",
            message="Ollama is not reachable",
            detail="Open Ollama, then check again.",
        )
        with (
            patch("voicepilot.settings_rewrite_ollama.check_ollama_health", return_value=health),
            patch("voicepilot.settings_rewrite_embedded.ollama_model_candidate", return_value=None),
        ):
            window = SettingsWindow(path)
            window._open_advanced_polish_ai()
            app.processEvents()

        dialog = window._advanced_dialog
        provider = dialog.findChild(QFrame, "ProviderIntro")
        engine_buttons = dialog.findChildren(QPushButton, "ProviderOption")
        ollama_button = next(button for button in engine_buttons if button.text() == "Ollama")
        with (
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            QTest.mouseClick(ollama_button, Qt.LeftButton)
        app.processEvents()

        assert window.widgets["rewrite.provider"].currentText() == "ollama"
        assert load_config(path).rewrite.provider == "ollama"
        assert provider.isVisible()
        assert dialog.findChild(QFrame, "WinsperModelPanel").isHidden()
        assert dialog.findChild(QFrame, "NvidiaAccelerationRow").isHidden()
        assert dialog.findChild(QFrame, "WinsperProviderConnection").isHidden()
        ollama_connection = dialog.findChild(QFrame, "OllamaProviderConnection")
        ollama_settings = dialog.findChild(QFrame, "OllamaProviderSettings")
        assert ollama_connection.isVisible()
        assert ollama_settings.isVisible()
        assert dialog.findChild(QFrame, "WinsperHealthPanel") is None
        assert dialog.findChild(QFrame, "OllamaHealthPanel") is None
        assert dialog.findChild(QFrame, "OllamaModelPanel") is None
        assert dialog.findChild(QFrame, "OllamaOptionsPanel") is None
        status = ollama_connection.findChild(QLabel, "StatusPanel")
        assert status.property("tone") == "neutral"
        check = ollama_connection.findChild(QPushButton, "DownloadControlButton")
        assert check.text() == "Check connection"
        assert check.isVisible()

        ollama_model = ollama_settings.findChild(QComboBox)
        assert ollama_model.count() == 0
        assert ollama_model.currentText() == ""
        assert ollama_model.lineEdit().isReadOnly()
        assert ollama_model.lineEdit().placeholderText() == "Check connection first"
        empty = OllamaHealth(True, False, "", (), "http://localhost:11434/api/tags")
        window._sync_ollama_model_widget(empty, ollama_model)
        assert ollama_model.lineEdit().placeholderText() == "No models installed"
        detected = OllamaHealth(
            True,
            True,
            "qwen3:4b",
            ("qwen3:4b", "qwen3:8b"),
            "http://localhost:11434/api/tags",
        )
        window._sync_ollama_model_widget(detected, ollama_model)
        assert [ollama_model.itemText(index) for index in range(ollama_model.count())] == [
            "qwen3:4b",
            "qwen3:8b",
        ]
        assert ollama_model.currentText() == ""
        assert ollama_model.lineEdit().placeholderText() == "Choose an installed model"
        ollama_model.setCurrentText("qwen3:4b")
        assert window.widgets["rewrite.model"].text() == "qwen3:4b"
        assert status.text() == "Ollama connection established · qwen3:4b"

        visible_copy = {label.text() for label in dialog.findChildren(QLabel) if label.isVisible()}
        assert {"Model", "Service address", "Keep model ready"}.issubset(visible_copy)
        assert {
            "Ollama connection",
            "Ollama model",
            "Ollama options",
            "AI engine location",
            "Model file",
            "Temperature",
            "Response timeout",
        }.isdisjoint(visible_copy)
        keep_ready = next(button for button in dialog.findChildren(QAbstractButton) if button.accessibleName() == "Keep model ready")
        assert keep_ready.isChecked()
        with (
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            QTest.mouseClick(keep_ready, Qt.LeftButton)
        assert load_config(path).rewrite.ollama_keep_alive == 0
        window.close()
    app.processEvents()


def test_polish_advanced_ollama_check_recovers_when_worker_stalls():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    import time

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.rewrite.provider = "ollama"
        save_config(config, path)

        def stalled_check(*_args, **_kwargs):
            time.sleep(0.5)
            raise AssertionError("late worker result must not keep the UI busy")

        with (
            patch(
                "voicepilot.settings_rewrite_ollama.OLLAMA_UI_TIMEOUT_SECONDS",
                0.05,
            ),
            patch(
                "voicepilot.settings_rewrite_ollama.check_ollama_health",
                side_effect=stalled_check,
            ),
        ):
            window = SettingsWindow(path)
            window._open_advanced_polish_ai()
            dialog = window._advanced_dialog
            check = dialog.findChild(QFrame, "OllamaProviderConnection").findChild(QPushButton, "DownloadControlButton")
            QTest.mouseClick(check, Qt.LeftButton)
            QTest.qWait(250)

            assert check.isEnabled()
            status_text = {label.text() for label in dialog.findChildren(QLabel)}
            assert "Ollama did not respond" in status_text
            window.close()
    app.processEvents()


def test_polish_quality_can_replace_a_custom_engine_selection():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.rewrite.provider = "ollama"
        save_config(config, path)
        window = SettingsWindow(path)
        window.show()
        window._show_named_page("Polish")
        app.processEvents()

        polish_page = window.stack.currentWidget()
        quality = polish_page.findChildren(QPushButton, "PolishQualityOption")
        custom = next(button for button in quality if button.text() == "Custom")
        fast = next(button for button in quality if button.text() == "Fast")
        assert custom.isChecked()
        assert fast.isEnabled()

        with (
            patch("voicepilot.settings_polish_page.model_is_installed", return_value=True),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            QTest.mouseClick(fast, Qt.LeftButton)
        app.processEvents()

        saved = load_config(path)
        assert saved.rewrite.provider == "embedded"
        assert saved.rewrite.llama_model_id == "qwen2.5-1.5b-q4km"
        assert saved.rewrite.llama_model_path == ""
        assert fast.isChecked()
        window.close()
    app.processEvents()


def test_polish_advanced_model_cancel_stops_the_download_worker():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QProgressBar, QPushButton
    from voicepilot.ai_runtime import RuntimeProgress
    from voicepilot.ollama import OllamaHealth
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        health = OllamaHealth(False, False, "", (), "http://localhost")
        with (
            patch("voicepilot.settings_rewrite_ollama.check_ollama_health", return_value=health),
            patch("voicepilot.settings_rewrite_embedded.model_is_installed", return_value=False),
            patch("voicepilot.settings_rewrite_embedded.ollama_model_candidate", return_value=None),
        ):
            window = SettingsWindow(path)
            window.show()
            window._open_advanced_polish_ai()
            app.processEvents()

        dialog = window._advanced_dialog
        download = next(button for button in dialog.findChildren(QPushButton) if button.text() == "Download model")
        pause = next(button for button in dialog.findChildren(QPushButton, "DownloadControlButton") if button.text() == "Pause")
        cancel = next(button for button in dialog.findChildren(QPushButton, "DownloadControlButton") if button.text() == "Cancel")

        feedback = dialog.findChild(QFrame, "ModelDownloadFeedback")
        progress = feedback.findChild(QProgressBar, "ModelDownloadProgress")
        download_status = feedback.findChild(QLabel, "ModelDownloadStatus")

        def cancelled_install(_model, **kwargs):
            assert kwargs["cancel_event"].is_set()
            kwargs["progress_callback"](RuntimeProgress("test", "Downloading model", 50, 100))
            raise RuntimeError("Download cancelled.")

        with (
            patch("voicepilot.settings_rewrite_embedded.install_polish_model", side_effect=cancelled_install),
            patch("voicepilot.settings_rewrite_embedded.threading.Thread") as thread,
            patch("voicepilot.settings_rewrite_embedded.ollama_model_candidate", return_value=None),
            patch("voicepilot.settings_rewrite_embedded.animate_progress_value") as animate,
        ):
            download.click()
            app.processEvents()
            assert window.ai_model_pause_event is not None
            assert window.ai_model_cancel_event is not None
            assert pause.isVisible()
            assert pause.isEnabled()
            assert cancel.isVisible()
            assert cancel.isEnabled()
            thread.return_value.start.assert_called_once_with()

            assert feedback.isVisible()
            assert progress.isVisible()
            assert not progress.isTextVisible()
            assert progress.height() == 6
            pause.click()
            assert window.ai_model_pause_event.is_set()
            assert pause.text() == "Resume"
            assert "preserved" in dialog.findChild(QLabel, "ModelDownloadStatus").text()

            cancel.click()
            assert window.ai_model_cancel_event.is_set()
            assert not window.ai_model_pause_event.is_set()
            assert not pause.isEnabled()
            assert not cancel.isEnabled()
            assert download_status.text() == "Cancelling download..."
            assert "â" not in download_status.text()

            first_worker = thread.call_args.kwargs["target"]
            first_worker()
            QTest.qWait(150)
            assert window.ai_model_cancel_event is None
            assert download.isEnabled()
            assert download_status.text() == "Download cancelled"
            animate.assert_called_once_with(progress, 50)

            download.click()
            assert thread.return_value.start.call_count >= 2
            cancel.click()
            thread.call_args.kwargs["target"]()
            QTest.qWait(150)
            assert window.ai_model_cancel_event is None

        window.close()
    app.processEvents()


def test_polish_advanced_offers_to_reuse_matching_ollama_model():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from voicepilot.ollama import OllamaHealth
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        health = OllamaHealth(False, False, "", (), "http://localhost")
        candidate = (Path(temp) / "ollama-model", "a" * 64, "qwen2.5:1.5b")
        with (
            patch("voicepilot.settings_rewrite_ollama.check_ollama_health", return_value=health),
            patch("voicepilot.settings_rewrite_embedded.model_is_installed", return_value=False),
            patch(
                "voicepilot.settings_rewrite_embedded.ollama_model_candidate",
                return_value=candidate,
            ),
        ):
            window = SettingsWindow(path)
            window._open_advanced_polish_ai()
            app.processEvents()

        dialog = window._advanced_dialog
        status = dialog.findChild(QLabel, "ModelSummaryText")
        assert "Available locally via Ollama" in status.text()
        assert any(button.text() == "Use existing model" for button in dialog.findChildren(QPushButton))
        window.close()
    app.processEvents()


def test_contextual_dialog_is_reused_and_rethemed():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        window._open_modal_page("Privacy", window._build_privacy_page)
        first = window._advanced_dialog
        first.close()
        window._open_modal_page("Privacy", window._build_privacy_page)
        assert window._advanced_dialog is first
        window._update_theme_preview("dark")
        assert first.styleSheet() == window.window.styleSheet()
        window.close()
    app.processEvents()


def test_model_selection_persists_before_audio_page_is_opened():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        assert "dictation.ramble_model" not in window.widgets

        table = QTableWidget(1, 2)
        table.setItem(0, 0, QTableWidgetItem("parakeet-tdt-0.6b-v2-int8"))
        table.setItem(0, 1, QTableWidgetItem("sherpa_onnx"))
        table.selectRow(0)

        with (
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window._apply_selected_model(table, "dictation.ramble_model")

        saved = load_config(path)
        assert saved.speech.model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.dictation.ramble_model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.dictation.polish_model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.dictation.rewrite_instruction_model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.speech.engine == "sherpa_onnx"
        assert saved.speech.device == "cpu"
        assert saved.speech.compute_type == "int8"
        assert "Parakeet v2" in window.model_status_label.text()
        window.close()
    app.processEvents()


def test_gpu_model_selection_persists_cuda_precision_atomically():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)

        with (
            patch(
                "voicepilot.settings_model_selection_actions.installed_status",
                return_value=SimpleNamespace(installed=True),
            ),
            patch("voicepilot.settings_model_selection_actions.engine_runtime_available", return_value=True),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window._apply_language_model("en", "large-v3-turbo")

        saved = load_config(path)
        assert saved.speech.model == "large-v3-turbo"
        assert saved.speech.engine == "faster_whisper"
        assert saved.speech.device == "cuda"
        assert saved.speech.compute_type == "float16"
        assert saved.dictation.ramble_model == "large-v3-turbo"
        window.close()
    app.processEvents()


def test_spoken_layout_setting_is_explained_and_persists():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QLabel
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        window._show_named_page("Dictation Details")
        toggle = window.widgets["spoken_formatting.enabled"]
        toggle.setChecked(False)
        labels = [label.text() for label in window.stack.currentWidget().findChildren(QLabel)]
        assert any('"new line"' in text for text in labels)

        with (
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window._save(silent=True)

        assert load_config(path).spoken_formatting.enabled is False
        window.close()
    app.processEvents()


def test_use_parakeet_for_precise_persists_immediately():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QLabel
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        status = QLabel()

        with (
            patch("voicepilot.settings_model_selection_actions.engine_runtime_available", return_value=True),
            patch(
                "voicepilot.settings_model_selection_actions.installed_status",
                return_value=SimpleNamespace(installed=True),
            ),
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window._use_parakeet_for_precise(status)

        saved = load_config(path)
        assert saved.speech.engine == "sherpa_onnx"
        assert saved.speech.model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.dictation.ramble_model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.dictation.polish_model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.dictation.rewrite_instruction_model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.speech.preload_on_startup is True
        assert "Parakeet v2" in window.model_status_label.text()
        assert "Changes applied" in status.text()
        window.close()
    app.processEvents()


def test_default_speech_model_updates_mode_specific_overrides():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        window._ensure_page_loaded(window.page_names.index("Hidden Fields"))
        window.widgets["speech.model"].setCurrentText("parakeet-tdt-0.6b-v2-int8")

        with (
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window._save(silent=True)

        saved = load_config(path)
        assert saved.speech.model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.speech.engine == "sherpa_onnx"
        assert saved.speech.device == "cpu"
        assert saved.speech.compute_type == "int8"
        assert saved.dictation.ramble_model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.dictation.polish_model == "parakeet-tdt-0.6b-v2-int8"
        assert saved.dictation.rewrite_instruction_model == "parakeet-tdt-0.6b-v2-int8"
        assert "Parakeet v2" in window.model_status_label.text()
        window.close()
    app.processEvents()


def test_language_page_filters_models_and_applies_selection_atomically():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        with (
            patch(
                "voicepilot.settings_model_selection_actions.installed_status",
                return_value=SimpleNamespace(installed=True),
            ),
            patch("voicepilot.settings_model_selection_actions.engine_runtime_available", return_value=True),
        ):
            window._ensure_page_loaded(window.page_names.index("Language + Speech"))
            french = window.language_combo.findData("fr")
            window.language_combo.setCurrentIndex(french)
            app.processEvents()

            available = {window.language_model_combo.itemData(index) for index in range(window.language_model_combo.count())}
            assert "parakeet-tdt-0.6b-v3-int8" in available
            assert "parakeet-tdt-0.6b-v2-int8" not in available

            with (
                patch("voicepilot.settings_persistence.set_start_with_windows"),
                patch("voicepilot.settings_persistence.request_control_command"),
            ):
                window._apply_language_model("fr", "parakeet-tdt-0.6b-v3-int8")

        saved = load_config(path)
        assert saved.speech.language == "fr"
        assert saved.speech.engine == "sherpa_onnx"
        assert saved.speech.model == "parakeet-tdt-0.6b-v3-int8"
        assert saved.dictation.ramble_model == saved.speech.model
        assert saved.dictation.polish_model == saved.speech.model
        assert saved.dictation.rewrite_instruction_model == saved.speech.model
        window.close()
    app.processEvents()
