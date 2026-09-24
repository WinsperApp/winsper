from __future__ import annotations

import queue
import threading
from pathlib import Path

from .ai_catalog import local_ai_root
from .model_storage import (
    configure_model_storage,
    copy_models_to_storage,
    huggingface_cache_root,
    model_storage_display_root,
)
from .models import (
    detect_hardware,
    engine_runtime_available,
    find_speech_model,
    installed_status,
    model_supports_language,
    recommended_model_for_language,
    speech_language_options,
    speech_models_for_language,
)
from .settings_model_storage_actions import restore_default_model_storage
from .speech_runtime import acceleration_status, install_nvidia_runtime, runtime_size_bytes, verify_nvidia_runtime
from .settings_helpers import friendly_check_error
from .settings_widgets import create_settings_combo
from .windows_ui import animate_progress_value


class SettingsSpeechModelsPageMixin:
    def _build_models_page(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QFileDialog,
            QComboBox,
            QFrame,
            QHBoxLayout,
            QLabel,
            QMessageBox,
            QProgressBar,
            QPushButton,
            QSizePolicy,
            QStyle,
            QVBoxLayout,
        )

        page, layout = self._page(
            "Dictation models",
            "Choose how Winsper listens. Every option runs locally on this PC.",
        )
        hardware = detect_hardware()

        current_panel = QFrame()
        current_panel.setObjectName("ModelCurrentPanel")
        current_layout = QHBoxLayout(current_panel)
        current_layout.setContentsMargins(18, 15, 18, 15)
        current_layout.setSpacing(14)
        current_copy = QVBoxLayout()
        current_copy.setSpacing(3)
        current_eyebrow = QLabel("CURRENT SETUP")
        current_eyebrow.setObjectName("ModelEyebrow")
        current_model = QLabel()
        current_model.setObjectName("ModelCurrentTitle")
        current_meta = QLabel()
        current_meta.setObjectName("Muted")
        current_copy.addWidget(current_eyebrow)
        current_copy.addWidget(current_model)
        current_copy.addWidget(current_meta)
        current_state = QLabel()
        current_state.setObjectName("ModelStateBadge")
        current_state.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        current_layout.addLayout(current_copy, 1)
        current_layout.addWidget(current_state, alignment=Qt.AlignVCenter)
        layout.addWidget(current_panel)

        setup_panel = QFrame()
        setup_panel.setObjectName("ModelPanel")
        setup_layout = QVBoxLayout(setup_panel)
        setup_layout.setContentsMargins(20, 18, 20, 18)
        setup_layout.setSpacing(12)
        setup_title = QLabel("Speech setup")
        setup_title.setObjectName("CardTitle")
        setup_layout.addWidget(setup_title)

        language_combo = create_settings_combo(
            lambda: self.palette,
            accessible_name="Speech language",
        )
        language_combo.setEditable(True)
        language_combo.setInsertPolicy(QComboBox.NoInsert)
        for code, label in speech_language_options():
            language_combo.addItem(label, code)
        selected_language = self.config.speech.language.strip().casefold()
        index = language_combo.findData(selected_language)
        language_combo.setCurrentIndex(index if index >= 0 else 0)
        if language_combo.completer() is not None:
            language_combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
            language_combo.completer().setFilterMode(Qt.MatchContains)
        self.language_combo = language_combo

        model_combo = create_settings_combo(
            lambda: self.palette,
            accessible_name="Transcription model",
        )
        self.language_model_combo = model_combo
        self._simple_row(
            setup_layout,
            "Transcription model",
            "The recommended option appears first.",
            model_combo,
            compact=True,
        )
        recommendation = QLabel()
        recommendation.setObjectName("ModelRecommendation")
        recommendation.setWordWrap(False)
        recommendation.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        setup_layout.addWidget(recommendation, alignment=Qt.AlignLeft)
        download_button = QPushButton("Download model")
        download_button.setObjectName("ModelDownloadButton")
        download_button.setMinimumWidth(132)
        model_summary = QFrame()
        model_summary.setObjectName("ModelSummary")
        model_summary_layout = QHBoxLayout(model_summary)
        model_summary_layout.setContentsMargins(16, 12, 12, 12)
        model_summary_layout.setSpacing(14)
        model_detail = QLabel()
        model_detail.setObjectName("ModelSummaryText")
        model_detail.setProperty("tone", "neutral")
        model_detail.setWordWrap(True)
        model_summary_layout.addWidget(model_detail, 1)
        model_summary_layout.addWidget(download_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        setup_layout.addWidget(model_summary)
        download_feedback = QFrame()
        download_feedback.setObjectName("ModelDownloadFeedback")
        download_feedback.hide()
        download_feedback_layout = QVBoxLayout(download_feedback)
        download_feedback_layout.setContentsMargins(14, 12, 14, 12)
        download_feedback_layout.setSpacing(7)
        download_heading = QHBoxLayout()
        download_heading.setSpacing(10)
        download_status = QLabel("")
        download_status.setObjectName("ModelDownloadStatus")
        download_status.setWordWrap(False)
        download_value = QLabel("")
        download_value.setObjectName("ModelDownloadValue")
        download_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        download_heading.addWidget(download_status, 1)
        download_heading.addWidget(download_value)
        download_feedback_layout.addLayout(download_heading)
        download_progress = QProgressBar()
        download_progress.setObjectName("ModelDownloadProgress")
        download_progress.setRange(0, 100)
        download_progress.setValue(0)
        download_progress.setTextVisible(False)
        download_progress.setFixedHeight(6)
        download_feedback_layout.addWidget(download_progress)
        download_meta = QLabel("")
        download_meta.setObjectName("ModelDownloadMeta")
        download_meta.setWordWrap(False)
        download_feedback_layout.addWidget(download_meta)
        download_controls = QHBoxLayout()
        download_controls.setSpacing(8)
        download_controls.addStretch(1)
        download_pause = QPushButton("Pause")
        download_pause.setObjectName("DownloadControlButton")
        download_pause.setAccessibleName("Pause model download")
        download_pause.setToolTip("Pause this download and keep its progress.")
        download_cancel = QPushButton("Cancel")
        download_cancel.setObjectName("DownloadControlButton")
        download_cancel.setAccessibleName("Cancel model download")
        download_cancel.setToolTip("Stop this download. Cached progress can be reused later.")
        download_controls.addWidget(download_pause)
        download_controls.addWidget(download_cancel)
        download_feedback_layout.addLayout(download_controls)
        # The download controller remains reusable, while this surface can
        # render richer progress without adding a second state machine.
        download_progress._winsper_feedback_container = download_feedback
        download_progress._winsper_value_label = download_value
        download_progress._winsper_meta_label = download_meta
        download_progress._winsper_pause_button = download_pause
        download_progress._winsper_cancel_button = download_cancel
        setup_layout.addWidget(download_feedback)

        actions = QHBoxLayout()
        support_button = QPushButton("Install Parakeet support")
        support_button.setObjectName("PrimaryButton")
        support_button.setMinimumWidth(176)
        actions.addWidget(support_button)
        actions.addStretch(1)
        setup_layout.addLayout(actions)
        layout.addWidget(setup_panel)

        acceleration_panel = QFrame()
        acceleration_panel.setObjectName("HardwareAccelerationPanel")
        acceleration_card = QVBoxLayout(acceleration_panel)
        acceleration_card.setContentsMargins(20, 15, 20, 15)
        acceleration_card.setSpacing(9)
        acceleration_row = QHBoxLayout()
        acceleration_row.setSpacing(16)
        acceleration_copy = QVBoxLayout()
        acceleration_copy.setSpacing(4)
        acceleration_title = QLabel("Hardware acceleration")
        acceleration_title.setObjectName("CardTitle")
        acceleration_detail = QLabel()
        acceleration_detail.setObjectName("HardwareAccelerationStatus")
        acceleration_detail.setWordWrap(True)
        acceleration_copy.addWidget(acceleration_title)
        acceleration_copy.addWidget(acceleration_detail)
        acceleration_row.addLayout(acceleration_copy, 1)
        acceleration_button = QPushButton()
        acceleration_button.setObjectName("HardwareAccelerationButton")
        acceleration_button.setMinimumWidth(156)
        acceleration_button.hide()
        acceleration_row.addWidget(acceleration_button, 0, Qt.AlignVCenter)
        acceleration_card.addLayout(acceleration_row)
        acceleration_progress = QProgressBar()
        acceleration_progress.setRange(0, 100)
        acceleration_progress.hide()
        acceleration_card.addWidget(acceleration_progress)
        acceleration_events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        acceleration_timer = None

        storage_panel = QFrame()
        storage_panel.setObjectName("ModelStoragePanel")
        storage_layout = QVBoxLayout(storage_panel)
        storage_layout.setContentsMargins(20, 18, 20, 18)
        storage_layout.setSpacing(12)
        storage_title = QLabel("Model storage location")
        storage_title.setObjectName("CardTitle")
        storage_subtitle = QLabel("Choose where Winsper keeps downloaded speech and Polish models.")
        storage_subtitle.setObjectName("Muted")
        storage_layout.addWidget(storage_title)
        storage_layout.addWidget(storage_subtitle)

        storage_row = QHBoxLayout()
        storage_row.setSpacing(10)
        storage_field = QFrame()
        storage_field.setObjectName("ModelStorageField")
        storage_field_layout = QHBoxLayout(storage_field)
        storage_field_layout.setContentsMargins(15, 9, 14, 9)
        storage_field_layout.setSpacing(10)
        storage_icon = QLabel()
        storage_icon.setObjectName("ModelStorageIcon")
        storage_icon.setPixmap(self.window.style().standardIcon(QStyle.SP_DirIcon).pixmap(18, 18))
        storage_path = QLabel()
        storage_path.setObjectName("ModelStoragePath")
        storage_path.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        storage_badge = QLabel("DEFAULT")
        storage_badge.setObjectName("ModelStorageBadge")
        storage_field_layout.addWidget(storage_icon)
        storage_field_layout.addWidget(storage_path, 1)
        storage_field_layout.addWidget(storage_badge)
        storage_browse = QPushButton("Browse")
        storage_browse.setObjectName("StorageBrowseButton")
        storage_browse.setMinimumWidth(104)
        storage_default = QPushButton("Use default")
        storage_default.setObjectName("StorageDefaultButton")
        storage_default.setMinimumWidth(104)
        storage_row.addWidget(storage_field, 1)
        storage_row.addWidget(storage_default)
        storage_row.addWidget(storage_browse)
        storage_layout.addLayout(storage_row)
        storage_feedback = QFrame()
        storage_feedback.setObjectName("ModelDownloadFeedback")
        storage_feedback.hide()
        storage_feedback_layout = QVBoxLayout(storage_feedback)
        storage_feedback_layout.setContentsMargins(14, 12, 14, 12)
        storage_feedback_layout.setSpacing(7)
        storage_progress_heading = QHBoxLayout()
        storage_progress_heading.setSpacing(10)
        storage_progress_status = QLabel("Moving downloaded models")
        storage_progress_status.setObjectName("ModelDownloadStatus")
        storage_progress_value = QLabel("Please keep Winsper open")
        storage_progress_value.setObjectName("ModelDownloadValue")
        storage_progress_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        storage_progress_heading.addWidget(storage_progress_status, 1)
        storage_progress_heading.addWidget(storage_progress_value)
        storage_feedback_layout.addLayout(storage_progress_heading)
        storage_progress = QProgressBar()
        storage_progress.setObjectName("ModelDownloadProgress")
        storage_progress.setRange(0, 0)
        storage_progress.setTextVisible(False)
        storage_progress.setFixedHeight(6)
        storage_feedback_layout.addWidget(storage_progress)
        storage_progress_meta = QLabel("Winsper keeps the original files until the copy is complete.")
        storage_progress_meta.setObjectName("ModelDownloadMeta")
        storage_feedback_layout.addWidget(storage_progress_meta)
        storage_layout.addWidget(storage_feedback)
        layout.addWidget(storage_panel)
        layout.addWidget(acceleration_panel)

        self.model_storage_path_label = storage_path
        self.model_storage_badge = storage_badge
        self.model_storage_browse_button = storage_browse
        self.model_storage_default_button = storage_default
        self.model_storage_progress = storage_feedback
        storage_events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        storage_timer = None

        def refresh_storage_location() -> None:
            root = model_storage_display_root().resolve()
            full_path = str(root)
            storage_path.setToolTip(full_path)
            storage_path.setText(
                storage_path.fontMetrics().elidedText(
                    full_path,
                    Qt.ElideMiddle,
                    560,
                )
            )
            using_default = not bool(self.config.model_storage.path.strip())
            storage_badge.setVisible(using_default)
            storage_default.setVisible(not using_default)

        def apply_storage_location(path: str) -> None:
            self.config.model_storage.path = path
            configure_model_storage(path)
            self._save(silent=True)
            refresh_storage_location()
            refresh_model_detail()
            refresh_current_setup()

        def choose_storage_location() -> None:
            nonlocal storage_timer
            selected = QFileDialog.getExistingDirectory(
                self.window,
                "Choose model storage location",
                str(model_storage_display_root()),
                QFileDialog.ShowDirsOnly,
            )
            if not selected:
                return
            destination = Path(selected).expanduser().resolve()
            current = model_storage_display_root().expanduser().resolve()
            if destination == current:
                return

            speech_source = huggingface_cache_root()
            polish_source = local_ai_root()
            storage_browse.setEnabled(False)
            storage_default.setEnabled(False)
            storage_feedback.show()

            def worker() -> None:
                try:
                    copied = copy_models_to_storage(
                        destination,
                        speech_source=speech_source,
                        polish_source=polish_source,
                    )
                    storage_events.put(("done", (str(destination), copied)))
                except Exception as exc:
                    storage_events.put(("error", exc))

            from PySide6.QtCore import QTimer

            timer = QTimer(self.window)
            storage_timer = timer

            def poll() -> None:
                nonlocal storage_timer
                try:
                    event, payload = storage_events.get_nowait()
                except queue.Empty:
                    return
                timer.stop()
                storage_timer = None
                storage_feedback.hide()
                storage_browse.setEnabled(True)
                storage_default.setEnabled(True)
                if event == "done":
                    path, copied = payload
                    apply_storage_location(path)
                    message = (
                        f"Model location changed. {copied} downloaded model{'' if copied == 1 else 's'} copied."
                        if copied
                        else "Model location changed. New downloads will be stored there."
                    )
                    self.status.setText(message)
                    self._show_toast("Model location changed", "good")
                    return
                QMessageBox.warning(
                    self.window,
                    "Winsper",
                    f"Winsper could not change the model location.\n\n{payload}",
                )

            timer.timeout.connect(poll)
            timer.start(100)
            threading.Thread(
                target=worker,
                name="WinsperModelStorageMove",
                daemon=True,
            ).start()

        def restore_default_storage() -> None:
            def restored(copied: int) -> None:
                apply_storage_location("")
                message = (
                    f"Default location restored. {copied} downloaded model{'' if copied == 1 else 's'} copied."
                    if copied
                    else "Default model location restored."
                )
                self.status.setText(message)
                self._show_toast("Default model location restored", "good")

            restore_default_model_storage(
                self,
                browse_button=storage_browse,
                default_button=storage_default,
                feedback=storage_feedback,
                on_done=restored,
            )

        storage_browse.clicked.connect(choose_storage_location)
        storage_default.clicked.connect(restore_default_storage)

        def language_label(code: str) -> str:
            return next(
                (label for option_code, label in speech_language_options() if option_code == code),
                code or "Auto / Mixed",
            )

        def refresh_current_setup() -> None:
            preset = find_speech_model(self.config.speech.model)
            label = preset.label if preset is not None else self.config.speech.model
            ready = bool(
                preset is not None and installed_status(preset, include_size=False).installed and engine_runtime_available(preset.engine)
            )
            current_model.setText(label or "Choose a model")
            current_meta.setText(f"{language_label(self.config.speech.language)} · Local processing")
            current_state.setText("Ready" if ready else "Needs setup")
            self._set_tone(current_state, "accent" if ready else "warn")

        def selected_code() -> str:
            value = language_combo.currentData()
            return str(value) if value is not None else self.config.speech.language

        def selected_model() -> str:
            value = model_combo.currentData()
            return str(value) if value is not None else ""

        def verification_model() -> str:
            selected = find_speech_model(selected_model())
            if selected is not None and selected.engine == "faster_whisper" and installed_status(selected, include_size=False).installed:
                return selected.model
            fallback = find_speech_model("small.en")
            if fallback is not None and installed_status(fallback, include_size=False).installed:
                return fallback.model
            return ""

        def refresh_acceleration() -> None:
            status = acceleration_status()
            acceleration_panel.setVisible(status.gpu is not None and not status.verified)
            self._set_tone(acceleration_detail, "accent" if status.verified else ("warn" if status.gpu else "neutral"))
            if status.gpu is None:
                acceleration_detail.setText("CPU processing is ready. It offers the widest compatibility and requires no extra setup.")
                acceleration_button.hide()
            elif status.verified:
                acceleration_detail.setText(f"{status.gpu.name} · Acceleration is enabled and verified.")
                acceleration_button.hide()
            elif status.installed or status.system_runtime:
                acceleration_detail.setText(f"{status.gpu.name} · Run one compatibility check to enable acceleration.")
                acceleration_button.setText("Verify acceleration")
                acceleration_button.setEnabled(bool(verification_model()))
                acceleration_button.show()
                if not verification_model():
                    acceleration_detail.setText(f"{status.gpu.name} · Download a Whisper model above, then verify acceleration.")
            else:
                acceleration_detail.setText(f"{status.gpu.name} · Optional faster processing is available for compatible Whisper models.")
                acceleration_button.setText(f"Enable NVIDIA acceleration ({runtime_size_bytes() / (1024**3):.1f} GB)")
                acceleration_button.setEnabled(True)
                acceleration_button.show()

        def start_acceleration_setup() -> None:
            nonlocal acceleration_timer
            status = acceleration_status()
            model = verification_model()
            if status.gpu is None:
                refresh_acceleration()
                return
            if (status.installed or status.system_runtime) and not model:
                acceleration_detail.setText(status.detail + "\nDownload a Whisper model first to verify GPU acceleration.")
                self._set_tone(acceleration_detail, "warn")
                return
            acceleration_progress.show()
            acceleration_progress.setRange(0, 0)
            acceleration_button.setEnabled(False)

            def worker() -> None:
                try:
                    if not (status.installed or status.system_runtime):
                        install_nvidia_runtime(progress_callback=lambda progress: acceleration_events.put(("progress", progress)))
                    selected_for_probe = model or verification_model()
                    if not selected_for_probe:
                        acceleration_events.put(("ready", "NVIDIA runtime installed. Download a Whisper model, then verify GPU."))
                        return
                    result = verify_nvidia_runtime(selected_for_probe)
                    if not result.verified:
                        raise RuntimeError(result.detail)
                    acceleration_events.put(("done", result.detail))
                except Exception as exc:
                    acceleration_events.put(("error", exc))

            from PySide6.QtCore import QTimer

            timer = QTimer(self.window)
            acceleration_timer = timer

            def poll() -> None:
                nonlocal acceleration_timer
                while True:
                    try:
                        event, payload = acceleration_events.get_nowait()
                    except queue.Empty:
                        return
                    if event == "progress":
                        progress = payload
                        acceleration_detail.setText(progress.status)
                        if progress.percent is not None:
                            acceleration_progress.setRange(0, 100)
                            animate_progress_value(acceleration_progress, progress.percent)
                        continue
                    timer.stop()
                    acceleration_timer = None
                    acceleration_progress.hide()
                    acceleration_button.setEnabled(True)
                    if event == "done":
                        self.config.speech.device = "cuda"
                        self.config.speech.compute_type = "float16"
                        self._sync_model_widgets()
                        self._save(silent=True)
                        self.status.setText("NVIDIA acceleration enabled and verified.")
                        refresh_current_setup()
                    elif event == "ready":
                        self.status.setText(str(payload))
                    else:
                        acceleration_detail.setText(f"GPU setup failed. CPU mode remains active.\n{friendly_check_error(payload)}")
                        self._set_tone(acceleration_detail, "warn")
                    refresh_acceleration()

            timer.timeout.connect(poll)
            timer.start(100)
            threading.Thread(target=worker, name="WinsperNvidiaRuntime", daemon=True).start()

        def refresh_model_detail() -> None:
            preset = find_speech_model(selected_model())
            if preset is None:
                model_detail.setText("Choose a compatible model.")
                self._set_tone(model_detail, "neutral")
                download_button.setEnabled(False)
                download_button.hide()
                support_button.setVisible(False)
                return
            installed = installed_status(preset, include_size=False).installed
            runtime_ready = engine_runtime_available(preset.engine)
            state = "Ready" if installed and runtime_ready else ("Download required" if not installed else "Runtime support required")
            model_detail.setText(f"{preset.label}\n{preset.tier} · {preset.best_for}\n{state} on this PC")
            self._set_tone(model_detail, "accent" if installed and runtime_ready else "warn")
            download_button.setEnabled(not installed)
            download_button.setVisible(not installed)
            download_button.setText(f"Download {preset.label}")
            support_button.setVisible(installed and preset.engine == "sherpa_onnx" and not runtime_ready)

        def preset_ready(preset) -> bool:
            return bool(
                preset is not None and installed_status(preset, include_size=False).installed and engine_runtime_available(preset.engine)
            )

        def refresh_models(prefer_recommended: bool = False) -> None:
            language = selected_code()
            presets = speech_models_for_language(language)
            recommended = recommended_model_for_language(language, hardware)
            current = self.config.speech.model
            current_supported = any(preset.model == current and model_supports_language(preset, language) for preset in presets)
            if prefer_recommended:
                ready_choice = next(
                    (preset for preset in [recommended, *presets] if preset_ready(preset)),
                    None,
                )
                target = (ready_choice or recommended).model
            else:
                target = current if current_supported else recommended.model
            model_combo.blockSignals(True)
            model_combo.clear()
            ordered = [recommended, *(preset for preset in presets if preset.model != recommended.model)]
            for preset in ordered:
                model_combo.addItem(preset.label, preset.model)
            target_index = model_combo.findData(target)
            model_combo.setCurrentIndex(target_index if target_index >= 0 else 0)
            model_combo.blockSignals(False)
            recommendation.setText(f"Recommended · {recommended.label}")
            refresh_model_detail()

        def sync_advanced_controls(
            language: str | None = None,
            model: str | None = None,
            *,
            prefer_recommended: bool = False,
        ) -> None:
            """Refresh the cached Advanced dialog from the saved selection."""
            from PySide6.QtCore import QSignalBlocker

            target_language = self.config.speech.language if language is None else str(language).strip().casefold()
            language_blocker = QSignalBlocker(language_combo)
            try:
                language_index = language_combo.findData(target_language)
                if language_index >= 0:
                    language_combo.setCurrentIndex(language_index)
            finally:
                del language_blocker
            refresh_models(prefer_recommended and model is None)
            if model:
                model_blocker = QSignalBlocker(model_combo)
                try:
                    model_index = model_combo.findData(model)
                    if model_index >= 0:
                        model_combo.setCurrentIndex(model_index)
                finally:
                    del model_blocker
                refresh_model_detail()
            refresh_current_setup()

        self._sync_advanced_model_controls = sync_advanced_controls

        def clear_pending_setup() -> None:
            callback = getattr(self, "_clear_dictation_model_setup", None)
            if callable(callback):
                callback()

        def remember_pending_setup(model: str) -> None:
            callback = getattr(self, "_request_dictation_model_setup", None)
            if callable(callback):
                callback(selected_code(), model)

        def auto_apply_selection() -> None:
            model = selected_model()
            if not model:
                return
            preset = find_speech_model(model)
            if not preset_ready(preset):
                return
            clear_pending_setup()
            if model == self.config.speech.model and selected_code() == self.config.speech.language:
                refresh_current_setup()
                return
            self.config.dictation.quality_profile = "custom"
            self._apply_language_model(selected_code(), model, model_detail)
            refresh_current_setup()
            refresh_model_detail()

        def download_selection() -> None:
            model = selected_model()
            if not model:
                return
            self._start_model_download(
                model,
                download_status,
                download_progress,
                lambda: (refresh_model_detail(), auto_apply_selection()),
                download_button,
            )

        def language_changed() -> None:
            refresh_models(True)
            auto_apply_selection()

        def model_changed() -> None:
            refresh_model_detail()
            model = selected_model()
            preset = find_speech_model(model)
            if model and not preset_ready(preset):
                remember_pending_setup(model)
                return
            auto_apply_selection()

        language_combo.currentIndexChanged.connect(lambda _index: language_changed())
        model_combo.currentIndexChanged.connect(lambda _index: model_changed())
        download_button.clicked.connect(download_selection)
        download_pause.clicked.connect(
            lambda: self._toggle_model_download_pause(
                download_status,
                download_progress,
            )
        )
        download_cancel.clicked.connect(
            lambda: self._cancel_model_download(
                download_status,
                download_progress,
            )
        )
        support_button.clicked.connect(lambda: self._install_parakeet_support(model_detail))
        acceleration_button.clicked.connect(start_acceleration_setup)
        refresh_models()
        refresh_current_setup()
        refresh_acceleration()
        refresh_storage_location()
        layout.addStretch(1)
        return page
