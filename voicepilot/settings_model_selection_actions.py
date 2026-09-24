from __future__ import annotations

import subprocess
from pathlib import Path
from .models import (
    cuda_runtime_available,
    engine_runtime_available,
    find_speech_model,
    installed_status,
    is_cpu_heavy_model,
    is_gpu_class_model,
    model_supports_language,
    speech_language_options,
)
from .speed_lab import (
    PARAKEET_ENGLISH_MODEL,
)
from .settings_helpers import combo_value


class SettingsModelSelectionActionsMixin:
    def _sync_model_widgets(self) -> None:
        from PySide6.QtCore import QSignalBlocker

        pairs = {
            "speech.engine": self.config.speech.engine,
            "speech.model": self.config.speech.model,
            "speech.device": self.config.speech.device,
            "speech.compute_type": self.config.speech.compute_type,
            "speech.language": self.config.speech.language,
            "speech.preload_on_startup": self.config.speech.preload_on_startup,
            "dictation.ramble_model": self.config.dictation.ramble_model,
            "dictation.polish_model": self.config.dictation.polish_model,
            "dictation.rewrite_instruction_model": self.config.dictation.rewrite_instruction_model,
        }
        for key, value in pairs.items():
            widget = self.widgets.get(key)
            if widget is None:
                continue
            # A model change is one atomic operation. Block auto-save while
            # related controls are synchronized to avoid partial settings.
            blocker = QSignalBlocker(widget)
            try:
                if hasattr(widget, "setCurrentText"):
                    widget.setCurrentText(str(value))
                elif hasattr(widget, "setChecked"):
                    widget.setChecked(bool(value))
                elif hasattr(widget, "setText"):
                    widget.setText(str(value))
            finally:
                del blocker

        language_picker = getattr(self, "dictation_language_combo", None)
        if language_picker is not None:
            blocker = QSignalBlocker(language_picker)
            try:
                index = language_picker.findData(self.config.speech.language)
                if index >= 0:
                    language_picker.setCurrentIndex(index)
            finally:
                del blocker
            refresh_consumer = getattr(self, "_refresh_dictation_consumer_state", None)
            if callable(refresh_consumer):
                refresh_consumer()

        sync_advanced = getattr(self, "_sync_advanced_model_controls", None)
        if callable(sync_advanced):
            sync_advanced()
        self._refresh_model_status_label()

    def _apply_language_model(self, language: str, model: str, status_label=None) -> None:
        preset = find_speech_model(model)
        if preset is None or not model_supports_language(preset, language):
            self.status.setText("Choose a model compatible with the selected language.")
            return
        if not installed_status(preset, include_size=False).installed:
            self.status.setText(f"Download {preset.label} before using it.")
            return
        if not engine_runtime_available(preset.engine):
            self.status.setText(
                "Install Parakeet support first." if preset.engine == "sherpa_onnx" else f"{preset.label} runtime is unavailable."
            )
            return

        self.config.speech.language = language
        self.config.speech.engine = preset.engine
        self.config.speech.model = preset.model
        self.config.speech.device = preset.device_hint
        self.config.speech.compute_type = preset.compute_hint
        if preset.engine == "sherpa_onnx":
            self.config.speech.preload_on_startup = True
        self.config.dictation.ramble_model = preset.model
        self.config.dictation.polish_model = preset.model
        self.config.dictation.rewrite_instruction_model = preset.model
        self._pending_dictation_language = None
        self._sync_model_widgets()
        self._save(silent=True)

        language_label = next(
            (label for code, label in speech_language_options() if code == language),
            language or "Auto-detect",
        )
        message = f"{preset.label} selected for {language_label}. Changes applied."
        if status_label is not None:
            status_label.setText(message)
            self._set_tone(status_label, "good")
        self.status.setText(message)

    def _apply_selected_model(self, table, key: str) -> None:
        row = table.currentRow()
        if row < 0:
            self.status.setText("Choose a model first.")
            return
        model = table.item(row, 0).text()
        engine = table.item(row, 1).text() if table.columnCount() > 1 and table.item(row, 1) is not None else self.config.speech.engine
        if key not in {
            "dictation.ramble_model",
            "dictation.polish_model",
            "dictation.rewrite_instruction_model",
        }:
            self.status.setText(f"Unknown model setting: {key}")
            return
        self.config.speech.model = model
        self.config.dictation.ramble_model = model
        self.config.dictation.polish_model = model
        self.config.dictation.rewrite_instruction_model = model

        self.config.speech.engine = engine
        preset = find_speech_model(model)
        if preset is not None:
            self.config.speech.device = preset.device_hint
            self.config.speech.compute_type = preset.compute_hint
        self._sync_model_widgets()
        self._save(silent=True)
        warning = self._model_fit_warning_text([model])
        self.status.setText(warning or f"Selected {model} as the default speech model. Changes applied.")
        self._refresh_model_fit_warning()

    def _refresh_model_fit_warning(self) -> None:
        if self.model_fit_warning is None:
            return
        models = [
            combo_value(self.widgets["dictation.ramble_model"])
            if "dictation.ramble_model" in self.widgets
            else self.config.dictation.ramble_model
        ]
        warning = self._model_fit_warning_text(models)
        if warning:
            self.model_fit_warning.show()
            self.model_fit_warning.setText(warning)
            self._set_tone(self.model_fit_warning, "warn")
        else:
            self.model_fit_warning.clear()
            self.model_fit_warning.hide()

    def _model_fit_warning_text(self, models: list[str]) -> str:
        device = combo_value(self.widgets["speech.device"]) if "speech.device" in self.widgets else self.config.speech.device
        cuda_ready = cuda_runtime_available()
        daily_model = "small.en" if self.config.speech.language == "en" else "small"
        if device == "cuda" and cuda_ready:
            return ""
        if device == "cuda" and not cuda_ready:
            return "CUDA is selected, but the NVIDIA CUDA runtime is not ready. Use CPU/int8 now, or install CUDA/cuDNN before choosing GPU models."
        risky = [model for model in models if is_gpu_class_model(model)]
        if risky:
            selected = ", ".join(dict.fromkeys(risky))
            return f"{selected} is a GPU-class model. On CPU it can take minutes. Recommended for this language: {daily_model}."
        heavy = [model for model in models if is_cpu_heavy_model(model)]
        if heavy:
            selected = ", ".join(dict.fromkeys(heavy))
            return f"{selected} favors accuracy over speed. It can feel slow on CPU; choose {daily_model} for daily dictation or benchmark first."
        return ""

    def _refresh_parakeet_status(self, status_label) -> None:
        preset = find_speech_model(PARAKEET_ENGLISH_MODEL)
        if preset is None:
            status_label.setText("Parakeet is not available in this build.")
            self._set_tone(status_label, "bad")
            return
        runtime_ready = engine_runtime_available("sherpa_onnx")
        model_ready = installed_status(preset, include_size=False).installed
        if runtime_ready and model_ready:
            status_label.setText("Parakeet is ready. Use it through Precise mode for higher-accuracy local dictation.")
            self._set_tone(status_label, "accent")
        elif runtime_ready:
            status_label.setText("Parakeet support is installed. Download the Parakeet model next.")
            self._set_tone(status_label, "warn")
        elif model_ready:
            status_label.setText("Parakeet model is downloaded. Install Parakeet support to use it.")
            self._set_tone(status_label, "warn")
        else:
            status_label.setText("Parakeet is optional. Install support, then download the model to use it for Precise mode.")
            self._set_tone(status_label, "neutral")

    def _install_parakeet_support(self, status_label) -> None:
        app_root = Path(__file__).resolve().parents[1]
        script = app_root / "scripts" / "install-parakeet.ps1"
        if not script.exists():
            status_label.setText("Install script is missing. Re-run setup or use scripts\\install-parakeet.cmd.")
            self._set_tone(status_label, "bad")
            return
        command = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        creationflags = subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
        try:
            subprocess.Popen(command, cwd=str(app_root), creationflags=creationflags)
        except Exception as exc:
            status_label.setText(f"Could not start Parakeet support install: {exc}")
            self._set_tone(status_label, "bad")
            return
        status_label.setText("Started Parakeet support install in a new terminal. Refresh when it finishes.")
        self._set_tone(status_label, "warn")
        self.status.setText("Installing Parakeet support.")

    def _use_parakeet_for_precise(self, status_label) -> None:
        preset = find_speech_model(PARAKEET_ENGLISH_MODEL)
        if preset is None:
            status_label.setText("Parakeet is not available in this build.")
            self._set_tone(status_label, "bad")
            return
        if not engine_runtime_available("sherpa_onnx"):
            status_label.setText("Install Parakeet support first.")
            self._set_tone(status_label, "warn")
            return
        if not installed_status(preset, include_size=False).installed:
            status_label.setText("Download the Parakeet model first.")
            self._set_tone(status_label, "warn")
            return
        self.config.speech.engine = "sherpa_onnx"
        self.config.speech.model = PARAKEET_ENGLISH_MODEL
        self.config.speech.device = "cpu"
        self.config.speech.compute_type = "int8"
        self.config.speech.preload_on_startup = True
        self.config.dictation.ramble_model = PARAKEET_ENGLISH_MODEL
        self.config.dictation.polish_model = PARAKEET_ENGLISH_MODEL
        self.config.dictation.rewrite_instruction_model = PARAKEET_ENGLISH_MODEL
        self._sync_model_widgets()
        self._save(silent=True)
        status_label.setText("Parakeet selected for Precise dictation. Changes applied.")
        self._set_tone(status_label, "good")
        self.status.setText("Parakeet selected for Precise. Changes applied.")
