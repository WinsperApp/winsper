from __future__ import annotations

import os
import queue
import threading
from dataclasses import replace
from pathlib import Path

from .ai_catalog import (
    DEFAULT_POLISH_MODEL_ID,
    POLISH_MODELS,
    polish_model,
)
from .ai_runtime import (
    RuntimeProgress,
    embedded_model_for_ollama_reference,
    install_polish_model,
    model_is_installed,
    ollama_model_candidate,
    uninstall_polish_model,
)
from .model_progress import format_bytes
from .llama_server import (
    LlamaServerHealth,
    inspect_llama_server,
)
from .rewrite_backends import verify_completion_backend
from .windows_ui import animate_progress_value
from .settings_helpers import (
    friendly_check_error,
    model_matches,
    text_value,
)
from .settings_model_download_actions import create_ai_model_download_controls
from .settings_rewrite_acceleration import build_polish_acceleration_controls
from types import SimpleNamespace


def build_embedded_runtime_section(owner, _layout, provider_widget):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

    embedded_health = LlamaServerHealth(
        ready=False,
        managed=True,
        endpoint=owner.config.rewrite.llama_server_url,
        message="Winsper AI is managed on this PC",
        detail="Check the local engine when Polish needs troubleshooting.",
    )
    check_embedded_button = QPushButton("Check connection")
    check_embedded_button.setObjectName("DownloadControlButton")
    embedded_wrapper = QFrame()
    embedded_wrapper.hide()
    embedded_card = QVBoxLayout(embedded_wrapper)
    embedded_card.setContentsMargins(0, 0, 0, 0)
    embedded_card.addWidget(check_embedded_button)
    embedded_status = QLabel(embedded_health.message)
    embedded_status.setObjectName("StatusPanel")
    embedded_status.setProperty("tone", "neutral")
    embedded_status.setWordWrap(True)
    embedded_detail = QLabel(embedded_health.detail)
    embedded_detail.setObjectName("Muted")
    embedded_detail.setWordWrap(True)
    embedded_detail.hide()
    embedded_card.addWidget(embedded_status)
    embedded_card.addWidget(embedded_detail)

    def check_embedded() -> None:
        embedded_status.setText("Checking Winsper AI...")
        owner._set_tone(embedded_status, "neutral")
        check_embedded_button.setEnabled(False)
        events: "queue.Queue[LlamaServerHealth]" = queue.Queue()
        config = owner._current_rewrite_config()

        def worker() -> None:
            try:
                result = inspect_llama_server(config, timeout_seconds=2.0)
            except Exception as exc:
                result = LlamaServerHealth(
                    ready=False,
                    managed=True,
                    endpoint=config.llama_server_url,
                    message="Winsper AI could not be checked",
                    detail=friendly_check_error(exc),
                )
            events.put(result)

        timer = QTimer(owner.window)
        owner.embedded_health_timer = timer

        def poll() -> None:
            try:
                result = events.get_nowait()
            except queue.Empty:
                return
            timer.stop()
            owner.embedded_health_timer = None
            check_embedded_button.setEnabled(True)
            embedded_status.setText("Winsper AI connection established" if result.ready else result.message)
            owner._set_tone(embedded_status, "accent" if result.ready else "warn")
            if result.ready:
                embedded_detail.clear()
                embedded_detail.hide()
            else:
                embedded_detail.setText(result.detail or "Winsper could not verify the selected local model and engine.")
                embedded_detail.show()
            owner.status.setText("Winsper AI connection established." if result.ready else "Winsper AI needs attention.")

        timer.timeout.connect(poll)
        timer.start(100)
        threading.Thread(target=worker, name="WinsperEmbeddedHealth", daemon=True).start()

    check_embedded_button.clicked.connect(check_embedded)
    server_path_widget = owner._line("rewrite.llama_server_path", owner.config.rewrite.llama_server_path)
    server_path_widget.hide()
    embedded_model_id = owner.config.rewrite.llama_model_id
    if not embedded_model_id:
        matching_model = embedded_model_for_ollama_reference(owner.config.rewrite.model)
        if matching_model is not None and ollama_model_candidate(matching_model) is not None:
            embedded_model_id = matching_model.id
    embedded_model = owner._combo(
        "rewrite.llama_model_id",
        embedded_model_id,
        ["", *(model.id for model in POLISH_MODELS)],
    )
    embedded_model.hide()
    model_path_widget = owner._line(
        "rewrite.llama_model_path",
        owner.config.rewrite.llama_model_path,
    )
    install_model_button = QPushButton("Download model")
    install_model_button.setObjectName("ModelDownloadButton")
    install_model_button.setMinimumWidth(116)
    model_status = QLabel()
    model_status.setObjectName("ModelSummaryText")
    model_status.setWordWrap(True)
    embedded_card.addWidget(model_status)
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
    model_progress = QProgressBar()
    model_progress.setRange(0, 100)
    model_progress.setValue(0)
    model_progress.setObjectName("ModelDownloadProgress")
    model_progress.setTextVisible(False)
    model_progress.setFixedHeight(6)
    model_progress.hide()
    download_feedback_layout.addWidget(model_progress)
    download_meta = QLabel("")
    download_meta.setObjectName("ModelDownloadMeta")
    download_meta.setWordWrap(False)
    download_feedback_layout.addWidget(download_meta)
    remove_model_button = QPushButton("Remove model")
    remove_model_button.setObjectName("DownloadControlButton")
    pause_model_button, cancel_model_button = create_ai_model_download_controls(
        owner,
        download_status,
    )

    model_actions = QHBoxLayout()
    download_controls = QHBoxLayout()
    download_controls.setSpacing(8)
    download_controls.addStretch(1)
    download_controls.addWidget(pause_model_button)
    download_controls.addWidget(cancel_model_button)
    download_feedback_layout.addLayout(download_controls)
    embedded_card.addWidget(download_feedback)

    model_actions.addWidget(remove_model_button)
    model_actions.addStretch(1)
    model_actions.addWidget(install_model_button)
    embedded_card.addLayout(model_actions)

    def selected_polish_model():
        model_id = embedded_model.currentText().strip() or DEFAULT_POLISH_MODEL_ID
        try:
            return polish_model(model_id)
        except KeyError:
            return polish_model(DEFAULT_POLISH_MODEL_ID)

    ollama_health_state = {"value": None}
    model_repair_state = {"model_id": ""}
    auto_adopt_attempted: set[str] = set()
    download_feedback_token = {"value": 0}

    def refresh_model_status() -> None:
        provider = provider_widget.currentText().strip() or "embedded"
        if provider == "ollama":
            model_widget = getattr(owner, "_ollama_model_widget", None)
            selected = text_value(model_widget) if model_widget is not None else ""
            result = ollama_health_state["value"]
            if result is None or not result.reachable:
                model_status.setText("Ollama · Check connection to find installed models")
                owner._set_tone(model_status, "neutral")
            elif selected and any(model_matches(selected, candidate) for candidate in result.models):
                model_status.setText(f"Ollama · {selected} · Ready")
                owner._set_tone(model_status, "accent")
            elif not result.models:
                model_status.setText("Ollama · No models installed")
                owner._set_tone(model_status, "warn")
            else:
                model_status.setText(f"Ollama · {selected} · Not available in Ollama")
                owner._set_tone(model_status, "warn")
            install_model_button.hide()
            remove_model_button.hide()
            if owner.ai_model_cancel_event is None:
                pause_model_button.hide()
                cancel_model_button.hide()
            return
        configured_path = text_value(model_path_widget).strip()
        if configured_path:
            resolved_path = Path(os.path.expandvars(os.path.expanduser(configured_path)))
            if resolved_path.is_file():
                model_status.setText("Custom local model · Ready")
                owner._set_tone(model_status, "accent")
            else:
                model_status.setText("Custom model file not found")
                owner._set_tone(model_status, "warn")
            install_model_button.hide()
            remove_model_button.hide()
            if owner.ai_model_cancel_event is None:
                pause_model_button.hide()
                cancel_model_button.hide()
            return
        model = selected_polish_model()
        installed = model_is_installed(model)
        needs_repair = installed and model_repair_state["model_id"] == model.id
        ollama_candidate = None if installed else ollama_model_candidate(model)
        size_gb = model.size_bytes / (1024**3)
        if installed:
            availability = "Ready"
        elif ollama_candidate is not None:
            availability = "Available locally via Ollama"
        else:
            availability = "One-time download required"
        model_status.setText(f"{model.label} · {size_gb:.1f} GB · " + availability)
        owner._set_tone(model_status, "accent" if installed else "neutral")
        install_model_button.setVisible(not installed or needs_repair)
        remove_model_button.setVisible(installed)
        install_model_button.setText(
            "Repair model" if needs_repair else "Use existing model" if ollama_candidate is not None else "Download model"
        )
        remove_model_button.setEnabled(installed and owner.ai_model_cancel_event is None)

    def start_model_install(*, automatic: bool = False) -> None:
        if owner.ai_model_cancel_event is not None:
            owner.status.setText("A Polish model download is already running.")
            return
        if provider_widget.currentText().strip() != "embedded":
            return
        model = selected_polish_model()
        reusing_ollama = not model_is_installed(model) and ollama_model_candidate(model) is not None
        rewrite_config = replace(
            owner._current_rewrite_config(),
            provider="embedded",
            llama_model_id=model.id,
            llama_model_path="",
        )
        from PySide6.QtCore import QTimer

        events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        pause_event = threading.Event()
        cancel_event = threading.Event()
        owner.ai_model_pause_event = pause_event
        owner.ai_model_cancel_event = cancel_event
        download_feedback_token["value"] += 1
        download_feedback.show()
        download_status.setText("Preparing secure download")
        owner._set_tone(download_status, "neutral")
        download_value.clear()
        owner._set_tone(download_value, "neutral")
        download_meta.setText("Getting the local Polish model ready.")
        model_progress.setRange(0, 0)
        model_progress.setValue(0)
        model_progress.show()
        install_model_button.setEnabled(False)
        install_model_button.setText("Preparing..." if reusing_ollama else "Downloading...")
        if reusing_ollama:
            download_status.setText(
                "Linking the verified Ollama model to Winsper AI..." if automatic else "Verifying existing local model..."
            )
        remove_model_button.setEnabled(False)
        pause_model_button.setText("Pause")
        pause_model_button.show()
        pause_model_button.setEnabled(True)
        cancel_model_button.show()
        cancel_model_button.setEnabled(True)

        def progress(value: RuntimeProgress) -> None:
            events.put(("progress", value))

        def worker() -> None:
            try:
                installed_path = install_polish_model(
                    model,
                    progress_callback=progress,
                    pause_event=pause_event,
                    cancel_event=cancel_event,
                )
                events.put(("verifying", None))
                verify_completion_backend(rewrite_config, cancel_event)
                events.put(("done", installed_path))
            except Exception as exc:
                events.put(("error", exc))

        timer = QTimer(owner.window)
        owner.ai_model_install_timer = timer

        def poll() -> None:
            while True:
                try:
                    event, payload = events.get_nowait()
                except queue.Empty:
                    return
                if event == "progress" and isinstance(payload, RuntimeProgress):
                    download_status.setText(payload.status or "Downloading model")
                    owner._set_tone(download_status, "neutral")
                    if payload.percent is None:
                        download_value.clear()
                        download_meta.setText("Preparing the local Polish model.")
                        model_progress.setRange(0, 0)
                    else:
                        model_progress.setRange(0, 100)
                        animate_progress_value(model_progress, payload.percent)
                        download_value.setText(f"{payload.percent}%")
                        download_meta.setText(f"{format_bytes(payload.downloaded_bytes)} of {format_bytes(payload.total_bytes)}")
                    continue
                if event == "verifying":
                    download_status.setText("Verifying local writing support")
                    download_value.clear()
                    download_meta.setText("Checking the model and local AI engine.")
                    model_progress.setRange(0, 0)
                    continue
                timer.stop()
                owner.ai_model_install_timer = None
                owner.ai_model_pause_event = None
                owner.ai_model_cancel_event = None
                install_model_button.setEnabled(True)
                pause_model_button.hide()
                cancel_model_button.hide()
                model_progress.setRange(0, 100)
                if event == "done":
                    model_repair_state["model_id"] = ""
                    owner.config.rewrite.provider = "embedded"
                    owner.config.rewrite.llama_model_id = model.id
                    owner.config.rewrite.llama_model_path = ""
                    embedded_model.setCurrentText(model.id)
                    model_path_widget.setText("")
                    owner._save(silent=True)
                    model_progress.setValue(100)
                    download_status.setText("Download complete")
                    owner._set_tone(download_status, "good")
                    download_value.setText("Ready")
                    owner._set_tone(download_value, "accent")
                    download_meta.setText("Installed locally and selected.")
                    owner.status.setText(f"{model.label} linked to Winsper AI." if reusing_ollama else f"{model.label} installed.")
                    refresh_model_status()
                    refresh_consumer = getattr(owner, "_refresh_polish_quality", None)
                    if callable(refresh_consumer):
                        refresh_consumer()
                else:
                    cancelled = cancel_event.is_set()
                    if not cancelled and model_is_installed(model):
                        model_repair_state["model_id"] = model.id
                    refresh_model_status()
                    model_progress.hide()
                    if cancelled:
                        download_status.setText("Download cancelled")
                        owner._set_tone(download_status, "neutral")
                        download_value.clear()
                        owner._set_tone(download_value, "neutral")
                        download_meta.setText("You can restart the download at any time.")
                        owner.status.setText("Model download cancelled.")
                    else:
                        detail = (
                            f"Could not reuse the existing model: {friendly_check_error(payload)}"
                            if reusing_ollama
                            else friendly_check_error(payload)
                        )
                        download_status.setText("Download failed")
                        owner._set_tone(download_status, "bad")
                        download_value.setText("Try again")
                        owner._set_tone(download_value, "bad")
                        download_meta.setText(detail)
                        owner.status.setText(
                            "Existing Ollama model could not be linked." if reusing_ollama else "Embedded model download failed."
                        )
                feedback_token = download_feedback_token["value"]

                def hide_completed_feedback() -> None:
                    if owner.ai_model_cancel_event is None and download_feedback_token["value"] == feedback_token:
                        download_feedback.hide()

                QTimer.singleShot(1400, hide_completed_feedback)

        timer.timeout.connect(poll)
        timer.start(100)
        threading.Thread(target=worker, name="WinsperAIModelInstaller", daemon=True).start()

    def ensure_embedded_model_ready() -> None:
        if provider_widget.currentText().strip() != "embedded":
            return
        if text_value(model_path_widget).strip() or owner.ai_model_cancel_event is not None:
            return
        model = selected_polish_model()
        if model.id in auto_adopt_attempted or model_is_installed(model):
            return
        candidate = ollama_model_candidate(model)
        if candidate is None or not candidate[0].is_file():
            return
        auto_adopt_attempted.add(model.id)
        start_model_install(automatic=True)

    def remove_model() -> None:
        model = selected_polish_model()
        auto_adopt_attempted.add(model.id)
        try:
            uninstall_polish_model(model)
        except Exception as exc:
            model_status.setText(f"Could not remove model: {friendly_check_error(exc)}")
            return
        model_repair_state["model_id"] = ""
        model_progress.hide()
        refresh_model_status()
        owner.status.setText(f"{model.label} removed.")

    def refresh_model_surfaces() -> None:
        refresh_model_status()
        refresh_consumer = getattr(owner, "_refresh_polish_quality", None)
        if callable(refresh_consumer):
            refresh_consumer()

    embedded_model.currentTextChanged.connect(lambda _value: refresh_model_surfaces())
    model_path_widget.textChanged.connect(lambda _value: refresh_model_surfaces())
    install_model_button.clicked.connect(lambda _checked=False: start_model_install())
    remove_model_button.clicked.connect(remove_model)
    model_path_widget.hide()
    acceleration = build_polish_acceleration_controls(owner, embedded_card)
    return SimpleNamespace(
        wrapper=embedded_wrapper,
        model_status=model_status,
        model_feedback=download_feedback,
        model_progress=model_progress,
        install_model_button=install_model_button,
        remove_model_button=remove_model_button,
        pause_model_button=pause_model_button,
        cancel_model_button=cancel_model_button,
        runtime_status=acceleration.runtime_status,
        runtime_progress=acceleration.runtime_progress,
        acceleration_toggle=acceleration.acceleration_toggle,
        runtime_cancel_button=acceleration.runtime_cancel_button,
        runtime_action=acceleration.runtime_action,
        refresh_model_status=refresh_model_status,
        ensure_embedded_model_ready=ensure_embedded_model_ready,
        ollama_health_state=ollama_health_state,
        check_button=check_embedded_button,
        connection_status=embedded_status,
        connection_detail=embedded_detail,
    )
