from __future__ import annotations

import queue
import threading
from dataclasses import replace

from .ai_catalog import DEFAULT_POLISH_MODEL_ID, polish_model, runtime_candidates
from .ai_hardware import detect_ai_hardware
from .ai_runtime import (
    RuntimeProgress,
    install_polish_model,
    install_runtime,
    model_is_installed,
    runtime_is_installed,
)
from .llama_server import bundled_llama_server_available
from .models import DownloadProgress, ModelDownloadCancelled, download_model
from .onboarding_helpers import friendly_setup_error
from .rewrite_backends import verify_completion_backend


class OnboardingDownloadsMixin:
    """Cooperative first-run downloads with the same pause/cancel contract as Settings."""

    def _start_polish_setup(self) -> None:
        if self.polish_setup_running or self._polish_support_ready():
            self._refresh_polish_setup_status()
            return
        candidates = runtime_candidates(detect_ai_hardware())
        if not candidates:
            self.polish_setup_status.setText("Polish is not supported on this PC yet. Dictation still works.")
            return
        from PySide6.QtCore import QTimer

        self.polish_check.setChecked(True)
        self.polish_setup_running = True
        self.polish_setup_paused = False
        self.polish_setup_pause_event.clear()
        self.polish_setup_cancel_event.clear()
        self._set_polish_quality_enabled(False)
        self.polish_setup_button.setEnabled(False)
        self.polish_setup_button.setText("Downloading…")
        self._show_polish_download_controls(True)
        self.polish_setup_progress.setRange(0, 0)
        self.polish_setup_progress.show()
        self.polish_setup_status.setText("Preparing Polish download…")
        self.polish_setup_timer = QTimer(self.window)
        self.polish_setup_timer.timeout.connect(self._poll_polish_setup)
        self.polish_setup_timer.start(100)
        model_id = self.recommended_polish_model.id if self.recommended_polish_model is not None else DEFAULT_POLISH_MODEL_ID
        model = polish_model(model_id)
        rewrite_config = replace(
            self._preview_config().rewrite,
            provider="embedded",
            llama_model_id=model.id,
            llama_model_path="",
        )
        threading.Thread(
            target=self._run_polish_setup,
            args=(candidates, model, rewrite_config),
            name="WinsperOnboardingPolishSetup",
            daemon=True,
        ).start()

    def _run_polish_setup(self, candidates, model, rewrite_config=None) -> None:
        def publish(stage: str, base: int, span: int, value: RuntimeProgress) -> None:
            percent = None if value.percent is None else base + int(value.percent * span / 100)
            self.polish_setup_events.put(("progress", (stage, percent)))

        try:
            baseline = next(
                (candidate for candidate in candidates if candidate.backend == "cpu"),
                None,
            )
            preferred = candidates[0] if candidates else None
            if baseline is not None and not bundled_llama_server_available() and not runtime_is_installed(baseline):
                install_runtime(
                    baseline,
                    progress_callback=lambda value: publish("Installing local writing support", 0, 10, value),
                    pause_event=self.polish_setup_pause_event,
                    cancel_event=self.polish_setup_cancel_event,
                )
            acceleration_warning = ""
            if preferred is not None and preferred is not baseline and not runtime_is_installed(preferred):
                try:
                    install_runtime(
                        preferred,
                        progress_callback=lambda value: publish("Enabling hardware acceleration", 10, 15, value),
                        pause_event=self.polish_setup_pause_event,
                        cancel_event=self.polish_setup_cancel_event,
                    )
                except Exception:
                    if self.polish_setup_cancel_event.is_set():
                        raise
                    acceleration_warning = " Winsper selected a compatible option for this PC."
            if not model_is_installed(model):
                install_polish_model(
                    model,
                    progress_callback=lambda value: publish("Downloading Polish support", 25, 75, value),
                    pause_event=self.polish_setup_pause_event,
                    cancel_event=self.polish_setup_cancel_event,
                )
            if rewrite_config is None:
                rewrite_config = replace(
                    self.config.rewrite,
                    provider="embedded",
                    llama_model_id=model.id,
                    llama_model_path="",
                )
            if self.polish_setup_cancel_event.is_set():
                raise RuntimeError("Polish download cancelled.")
            self.polish_setup_events.put(("progress", ("Verifying local writing support", 100)))
            verify_completion_backend(rewrite_config)
            self.polish_setup_events.put(("done", (model, acceleration_warning)))
        except Exception as exc:
            event = "cancelled" if self.polish_setup_cancel_event.is_set() else "error"
            self.polish_setup_events.put((event, exc))

    def _poll_polish_setup(self) -> None:
        while True:
            try:
                event, payload = self.polish_setup_events.get_nowait()
            except queue.Empty:
                return
            if event == "progress":
                status, percent = payload
                self.polish_setup_status.setText(f"{status}…")
                self.polish_setup_progress.setRange(0, 0 if percent is None else 100)
                if percent is not None:
                    self.polish_setup_progress.setValue(percent)
                continue
            self.polish_setup_running = False
            self.polish_setup_paused = False
            self.polish_setup_pause_event.clear()
            self.polish_setup_cancel_event.clear()
            self._set_polish_quality_enabled(True)
            self._show_polish_download_controls(False)
            if self.polish_setup_timer is not None:
                self.polish_setup_timer.stop()
                self.polish_setup_timer = None
            if event == "done":
                model, warning = payload
                self._polish_provider_changed = True
                self.config.rewrite.provider = "embedded"
                self.config.rewrite.llama_model_id = model.id
                self.config.rewrite.llama_model_path = ""
                self.polish_setup_progress.setRange(0, 100)
                self.polish_setup_progress.setValue(100)
                self._refresh_polish_setup_status()
                self._ensure_polish_test_runtime()
                if warning:
                    self.polish_setup_status.setText(warning.strip())
                    self.polish_setup_status.show()
                else:
                    # Backend verification above is authoritative for this
                    # completed setup. Keep stale availability probes from
                    # resurfacing download copy after success.
                    self.polish_setup_status.hide()
                    self.polish_setup_button.hide()
            elif event == "cancelled":
                self.polish_setup_progress.hide()
                self.polish_setup_status.setText("Download cancelled. Incomplete files were removed.")
                self.polish_setup_button.setText("Download Polish model")
                self.polish_setup_button.setEnabled(True)
                self.polish_setup_button.show()
            else:
                self.polish_setup_progress.hide()
                self.polish_setup_status.setText(f"Polish setup could not finish. {friendly_setup_error(payload)}")
                self.polish_setup_button.setText("Try setup again")
                self.polish_setup_button.setEnabled(True)
                self.polish_setup_button.show()

    def _toggle_polish_setup_pause(self) -> None:
        if not self.polish_setup_running:
            return
        self.polish_setup_paused = not self.polish_setup_paused
        if self.polish_setup_paused:
            self.polish_setup_pause_event.set()
            self.polish_setup_pause_button.setText("Resume")
            self.polish_setup_status.setText("Download paused. Progress is preserved.")
        else:
            self.polish_setup_pause_event.clear()
            self.polish_setup_pause_button.setText("Pause")
            self.polish_setup_status.setText("Resuming download…")

    def _cancel_polish_setup(self) -> None:
        if not self.polish_setup_running:
            return
        self.polish_setup_cancel_event.set()
        self.polish_setup_pause_event.clear()
        self.polish_setup_pause_button.setEnabled(False)
        self.polish_setup_cancel_button.setEnabled(False)
        self.polish_setup_status.setText("Cancelling download…")

    def _show_polish_download_controls(self, visible: bool) -> None:
        self.polish_setup_pause_button.setText("Pause")
        self.polish_setup_pause_button.setEnabled(visible)
        self.polish_setup_cancel_button.setEnabled(visible)
        self.polish_setup_pause_button.setVisible(visible)
        self.polish_setup_cancel_button.setVisible(visible)

    def _refresh_polish_setup_status(self) -> None:
        if self.polish_setup_button is None:
            return
        self._refresh_polish_quality_models()
        model = self.recommended_polish_model or polish_model(DEFAULT_POLISH_MODEL_ID)
        if self.polish_quality_summary is not None:
            self.polish_quality_summary.setText(model.label)
        if self.polish_setup_running:
            return
        ready = self._polish_support_ready()
        downloaded = model_is_installed(model)
        size = f"{model.size_bytes / (1024**3):.1f} GB"
        self.polish_setup_progress.hide()
        self._show_polish_download_controls(False)
        if ready:
            self.polish_setup_status.hide()
            self.polish_setup_button.hide()
            return
        self.polish_setup_status.show()
        if downloaded:
            self.polish_setup_status.setText(f"{model.label} is downloaded. Finish setting up Polish.")
            button_text = "Finish Polish setup"
        else:
            self.polish_setup_status.setText(f"{model.label} needs a one-time {size} download.")
            button_text = f"Download {model.label} · {size}"
        self.polish_setup_button.setText(button_text)
        self.polish_setup_button.setEnabled(True)
        self.polish_setup_button.show()

    def _skip_polish_setup(self) -> None:
        if self.polish_setup_running:
            self.polish_setup_status.setText("Pause or cancel the current download before leaving this step.")
            return
        self.polish_check.setChecked(False)
        self.config.onboarding.polish_skipped = True
        self.polish_setup_status.setText("Polish skipped. Dictation is ready.")
        self._persist_progress()

    def _launch_download(self, model: str) -> None:
        if self.download_running:
            self.model_status.setText("A model download is already running.")
            return
        from PySide6.QtCore import QTimer

        self.download_running = True
        self.download_paused = False
        self.download_pause_event.clear()
        self.download_cancel_event.clear()
        self.active_speech_download_model = model
        self.model_status.setText("Preparing speech download…")
        self.model_download_button.setEnabled(False)
        self.model_download_button.setText("Downloading…")
        self.model_download_progress.setRange(0, 0)
        self.model_download_progress.show()
        self._show_speech_download_controls(True)
        self.download_timer = QTimer(self.window)
        self.download_timer.timeout.connect(self._poll_download)
        self.download_timer.start(150)
        threading.Thread(
            target=self._run_download,
            args=(model,),
            name=f"WinsperDownload-{model}",
            daemon=True,
        ).start()

    def _run_download(self, model: str) -> None:
        try:
            download_model(
                model,
                progress_callback=lambda progress: self.download_events.put(("progress", progress)),
                pause_event=self.download_pause_event,
                cancel_event=self.download_cancel_event,
            )
            self.download_events.put(("done", None))
        except ModelDownloadCancelled:
            self.download_events.put(("cancelled", None))
        except Exception as exc:
            event = "cancelled" if self.download_cancel_event.is_set() else "error"
            self.download_events.put((event, friendly_setup_error(exc)))

    def _poll_download(self) -> None:
        while True:
            try:
                event, payload = self.download_events.get_nowait()
            except queue.Empty:
                return
            if event == "progress" and isinstance(payload, DownloadProgress):
                self._apply_download_progress(payload, self.model_status, self.model_download_progress)
                continue
            self.download_running = False
            self.download_paused = False
            self.active_speech_download_model = ""
            self.download_pause_event.clear()
            self.download_cancel_event.clear()
            self._show_speech_download_controls(False)
            self._stop_download_timer()
            if event == "done":
                self.model_download_progress.setRange(0, 100)
                self.model_download_progress.setValue(100)
                self._refresh()
            elif event == "cancelled":
                self.model_download_progress.hide()
                self.model_status.setText("Download cancelled. Incomplete files were removed.")
                self.model_download_button.setText("Download speech support")
                self.model_download_button.setEnabled(True)
                self.model_download_button.show()
            else:
                self.model_download_progress.hide()
                self.model_status.setText(f"Download failed: {payload}")
                self.model_download_button.setText("Try download again")
                self.model_download_button.setEnabled(True)
                self.model_download_button.show()

    def _toggle_speech_download_pause(self) -> None:
        if not self.download_running:
            return
        self.download_paused = not self.download_paused
        if self.download_paused:
            self.download_pause_event.set()
            self.model_download_pause_button.setText("Resume")
            self.model_status.setText("Download paused. Progress is preserved.")
        else:
            self.download_pause_event.clear()
            self.model_download_pause_button.setText("Pause")
            self.model_status.setText("Resuming download…")

    def _cancel_speech_download(self) -> None:
        if not self.download_running:
            return
        self.download_cancel_event.set()
        self.download_pause_event.clear()
        self.model_download_pause_button.setEnabled(False)
        self.model_download_cancel_button.setEnabled(False)
        self.model_status.setText("Cancelling download…")

    def _show_speech_download_controls(self, visible: bool) -> None:
        self.model_download_pause_button.setText("Pause")
        self.model_download_pause_button.setEnabled(visible)
        self.model_download_cancel_button.setEnabled(visible)
        self.model_download_pause_button.setVisible(visible)
        self.model_download_cancel_button.setVisible(visible)

    def _stop_download_timer(self) -> None:
        if self.download_timer is not None:
            self.download_timer.stop()
            self.download_timer = None
