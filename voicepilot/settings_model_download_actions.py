from __future__ import annotations

import queue
import threading
from .models import (
    DownloadProgress,
    ModelDownloadCancelled,
    download_model,
    format_download_progress,
)
from .settings_helpers import friendly_check_error
from .windows_ui import animate_progress_value


def create_download_control_button(text: str, accessible_name: str, tooltip: str):
    from PySide6.QtWidgets import QPushButton

    button = QPushButton(text)
    button.setObjectName("DownloadControlButton")
    button.setAccessibleName(accessible_name)
    button.setToolTip(tooltip)
    return button


def toggle_download_pause(pause_event, button, status_label) -> None:
    paused = not pause_event.is_set()
    if paused:
        pause_event.set()
    else:
        pause_event.clear()
    button.setText("Resume" if paused else "Pause")
    status_label.setText("Download paused. Progress is preserved." if paused else "Resuming download...")


def create_ai_model_download_controls(owner, status_label):
    pause_button = create_download_control_button("Pause", "Pause Polish model download", "Pause this download and keep its progress.")
    cancel_button = create_download_control_button(
        "Cancel",
        "Cancel Polish model download",
        "Stop this download. Cached progress can be reused later.",
    )
    pause_button.hide()
    cancel_button.hide()
    owner.ai_model_pause_event = None
    owner.ai_model_cancel_event = None

    def toggle_pause() -> None:
        if owner.ai_model_pause_event is not None:
            toggle_download_pause(owner.ai_model_pause_event, pause_button, status_label)

    def cancel_download() -> None:
        if owner.ai_model_pause_event is not None:
            owner.ai_model_pause_event.clear()
        if owner.ai_model_cancel_event is None:
            return
        owner.ai_model_cancel_event.set()
        pause_button.setEnabled(False)
        cancel_button.setEnabled(False)
        status_label.setText("Cancelling download...")

    pause_button.clicked.connect(toggle_pause)
    cancel_button.clicked.connect(cancel_download)
    return pause_button, cancel_button


class SettingsModelDownloadActionsMixin:
    def _start_model_download(self, model: str, status_label=None, progress_bar=None, on_done=None, action_button=None) -> None:
        if self.model_download_running:
            self.status.setText("A model download is already running.")
            return
        self.model_download_running = True
        self.model_download_paused = False
        self.model_download_pause_event.clear()
        self.model_download_cancel_event.clear()
        self._model_download_context = (
            model,
            status_label,
            progress_bar,
            on_done,
            action_button,
        )
        self.status.setText(f"Downloading {model}...")
        if action_button is not None:
            action_button.setProperty("winsper_original_text", action_button.text())
            action_button.setEnabled(False)
            action_button.setText("Downloading...")
        if status_label is not None:
            status_label.setText("Preparing secure download")
            self._set_tone(status_label, "neutral")
        if progress_bar is not None:
            self._model_download_feedback_token = getattr(self, "_model_download_feedback_token", 0) + 1
            progress_bar._winsper_feedback_token = self._model_download_feedback_token
            feedback = getattr(progress_bar, "_winsper_feedback_container", None)
            value_label = getattr(progress_bar, "_winsper_value_label", None)
            meta_label = getattr(progress_bar, "_winsper_meta_label", None)
            pause_button = getattr(progress_bar, "_winsper_pause_button", None)
            cancel_button = getattr(progress_bar, "_winsper_cancel_button", None)
            if feedback is not None:
                feedback.show()
            if value_label is not None:
                value_label.setText("")
                self._set_tone(value_label, "neutral")
            if meta_label is not None:
                meta_label.setText("Getting the local speech model ready.")
            if pause_button is not None:
                pause_button.setText("Pause")
                pause_button.setAccessibleName("Pause model download")
                pause_button.setEnabled(True)
            if cancel_button is not None:
                cancel_button.setEnabled(True)
            progress_bar.setRange(0, 0)
            progress_bar.setTextVisible(False)
            progress_bar.show()

        self._start_model_download_timer(
            status_label,
            progress_bar,
            on_done,
            action_button,
        )
        self._launch_model_download_worker(model)

    def _run_model_download(self, model: str) -> None:
        import time

        last_emit = 0.0

        def progress_callback(progress) -> None:
            nonlocal last_emit
            now = time.monotonic()
            if now - last_emit >= 0.1:
                self.model_download_events.put(("progress", progress))
                last_emit = now

        try:
            path = download_model(
                model,
                progress_callback=progress_callback,
                pause_event=self.model_download_pause_event,
                cancel_event=self.model_download_cancel_event,
            )
            self.model_download_events.put(("done", f"Download complete. {model} is ready at {path}"))
        except ModelDownloadCancelled:
            self.model_download_events.put(("cancelled", None))
        except Exception as exc:
            if self.model_download_cancel_event.is_set():
                self.model_download_events.put(("cancelled", None))
            elif self.model_download_pause_event.is_set():
                self.model_download_events.put(("paused", None))
            else:
                self.model_download_events.put(("error", friendly_check_error(exc)))

    def _poll_model_download(self, status_label=None, progress_bar=None, on_done=None, action_button=None) -> None:
        while True:
            try:
                event, payload = self.model_download_events.get_nowait()
            except queue.Empty:
                return
            if event == "progress" and isinstance(payload, DownloadProgress):
                if status_label is not None:
                    status_label.setText(payload.status or "Downloading model")
                    self._set_tone(status_label, "neutral")
                value_label = getattr(progress_bar, "_winsper_value_label", None)
                meta_label = getattr(progress_bar, "_winsper_meta_label", None)
                if value_label is not None:
                    value_label.setText(f"{payload.percent}%" if payload.percent is not None else "")
                    self._set_tone(value_label, "neutral")
                if meta_label is not None:
                    meta_label.setText(format_download_progress(payload))
                self._apply_progress_bar(progress_bar, payload)
            elif event == "done":
                self.model_download_running = False
                self.model_download_paused = False
                self.status.setText(str(payload))
                if status_label is not None:
                    status_label.setText("Download complete")
                    self._set_tone(status_label, "good")
                if progress_bar is not None:
                    progress_bar.setTextVisible(False)
                    progress_bar.setRange(0, 100)
                    progress_bar.setValue(100)
                    value_label = getattr(progress_bar, "_winsper_value_label", None)
                    meta_label = getattr(progress_bar, "_winsper_meta_label", None)
                    if value_label is not None:
                        value_label.setText("Ready")
                        self._set_tone(value_label, "accent")
                    if meta_label is not None:
                        meta_label.setText("Installed locally and selected.")
                self._restore_model_download_button(action_button)
                self._reset_model_download_controls(progress_bar)
                self._stop_model_download_timer()
                self._model_download_context = None
                if on_done is not None:
                    on_done()
                self._schedule_model_download_feedback_hide(
                    status_label,
                    progress_bar,
                )
            elif event == "cancelled":
                self.model_download_running = False
                self.model_download_paused = False
                self.status.setText("Model download cancelled.")
                if status_label is not None:
                    status_label.setText("Download cancelled")
                    self._set_tone(status_label, "neutral")
                if progress_bar is not None:
                    progress_bar.hide()
                    value_label = getattr(progress_bar, "_winsper_value_label", None)
                    meta_label = getattr(progress_bar, "_winsper_meta_label", None)
                    if value_label is not None:
                        value_label.clear()
                        self._set_tone(value_label, "neutral")
                    if meta_label is not None:
                        meta_label.setText("You can restart the download at any time.")
                self._restore_model_download_button(action_button)
                self._reset_model_download_controls(progress_bar)
                self._stop_model_download_timer()
                self._model_download_context = None
                self._schedule_model_download_feedback_hide(
                    status_label,
                    progress_bar,
                )
            elif event == "error":
                self.model_download_running = False
                self.model_download_paused = False
                self.status.setText(f"Download failed: {payload}")
                if status_label is not None:
                    status_label.setText("Download failed")
                    self._set_tone(status_label, "bad")
                if progress_bar is not None:
                    progress_bar.hide()
                    value_label = getattr(progress_bar, "_winsper_value_label", None)
                    meta_label = getattr(progress_bar, "_winsper_meta_label", None)
                    if value_label is not None:
                        value_label.setText("Try again")
                        self._set_tone(value_label, "bad")
                    if meta_label is not None:
                        meta_label.setText(str(payload))
                self._restore_model_download_button(action_button)
                self._reset_model_download_controls(progress_bar)
                self._stop_model_download_timer()
                self._model_download_context = None

    def _toggle_model_download_pause(self, status_label=None, progress_bar=None) -> None:
        if self.model_download_running and not self.model_download_paused:
            self.model_download_pause_event.set()
            self.model_download_paused = True
            self.status.setText("Model download paused.")
            if status_label is not None:
                status_label.setText("Download paused")
                self._set_tone(status_label, "neutral")
            if progress_bar is not None:
                value_label = getattr(progress_bar, "_winsper_value_label", None)
                meta_label = getattr(progress_bar, "_winsper_meta_label", None)
                pause_button = getattr(progress_bar, "_winsper_pause_button", None)
                if value_label is not None:
                    value_label.setText("Paused")
                    self._set_tone(value_label, "neutral")
                if meta_label is not None:
                    meta_label.setText("Resume when you are ready. Downloaded data is preserved.")
                if pause_button is not None:
                    pause_button.setText("Resume")
                    pause_button.setAccessibleName("Resume model download")
                    pause_button.setEnabled(True)
            return
        if not self.model_download_running or not self.model_download_paused or self._model_download_context is None:
            return

        self.model_download_pause_event.clear()
        self.model_download_paused = False
        self.status.setText("Resuming model download...")
        if status_label is not None:
            status_label.setText("Resuming download")
            self._set_tone(status_label, "neutral")
        if progress_bar is not None:
            value_label = getattr(progress_bar, "_winsper_value_label", None)
            meta_label = getattr(progress_bar, "_winsper_meta_label", None)
            pause_button = getattr(progress_bar, "_winsper_pause_button", None)
            if value_label is not None:
                value_label.setText("")
                self._set_tone(value_label, "neutral")
            if meta_label is not None:
                meta_label.setText("Continuing from the downloaded data.")
            if pause_button is not None:
                pause_button.setText("Pause")
                pause_button.setAccessibleName("Pause model download")
                pause_button.setEnabled(True)

    def _cancel_model_download(self, status_label=None, progress_bar=None) -> None:
        if not self.model_download_running and not self.model_download_paused:
            return
        was_paused = self.model_download_paused
        self.model_download_cancel_event.set()
        self.model_download_pause_event.clear()
        self.model_download_paused = False
        self.status.setText("Cancelling model download...")
        if status_label is not None:
            status_label.setText("Cancelling download")
            self._set_tone(status_label, "neutral")
        if progress_bar is not None:
            value_label = getattr(progress_bar, "_winsper_value_label", None)
            pause_button = getattr(progress_bar, "_winsper_pause_button", None)
            cancel_button = getattr(progress_bar, "_winsper_cancel_button", None)
            if value_label is not None:
                value_label.setText("")
                self._set_tone(value_label, "neutral")
            if pause_button is not None:
                pause_button.setEnabled(False)
            if cancel_button is not None:
                cancel_button.setEnabled(False)
        if was_paused:
            self.model_download_events.put(("cancelled", None))
            self._ensure_model_download_timer()

    def _start_model_download_timer(
        self,
        status_label,
        progress_bar,
        on_done,
        action_button,
    ) -> None:
        from PySide6.QtCore import QTimer

        self._stop_model_download_timer()
        self.model_download_timer = QTimer(self.window)
        self.model_download_timer.timeout.connect(
            lambda: self._poll_model_download(
                status_label,
                progress_bar,
                on_done,
                action_button,
            )
        )
        self.model_download_timer.start(150)

    def _ensure_model_download_timer(self) -> None:
        if self.model_download_timer is not None or self._model_download_context is None:
            return
        _model, status_label, progress_bar, on_done, action_button = self._model_download_context
        self._start_model_download_timer(
            status_label,
            progress_bar,
            on_done,
            action_button,
        )

    def _launch_model_download_worker(self, model: str) -> None:
        threading.Thread(
            target=self._run_model_download,
            args=(model,),
            name=f"WinsperModelDownload-{model}",
            daemon=True,
        ).start()

    def _reset_model_download_controls(self, progress_bar) -> None:
        self.model_download_pause_event.clear()
        self.model_download_cancel_event.clear()
        if progress_bar is None:
            return
        pause_button = getattr(progress_bar, "_winsper_pause_button", None)
        cancel_button = getattr(progress_bar, "_winsper_cancel_button", None)
        if pause_button is not None:
            pause_button.setText("Pause")
            pause_button.setAccessibleName("Pause model download")
            pause_button.setEnabled(False)
        if cancel_button is not None:
            cancel_button.setEnabled(False)

    def _schedule_model_download_feedback_hide(self, status_label, progress_bar) -> None:
        if progress_bar is None:
            return
        from PySide6.QtCore import QTimer

        token = getattr(progress_bar, "_winsper_feedback_token", None)

        def hide_completed_feedback() -> None:
            if self.model_download_running:
                return
            if getattr(progress_bar, "_winsper_feedback_token", None) != token:
                return
            feedback = getattr(progress_bar, "_winsper_feedback_container", None)
            if feedback is not None:
                feedback.hide()
            else:
                progress_bar.hide()
                if status_label is not None:
                    status_label.hide()

        QTimer.singleShot(1400, hide_completed_feedback)

    def _stop_model_download_timer(self) -> None:
        if self.model_download_timer is not None:
            self.model_download_timer.stop()
            self.model_download_timer = None

    def _restore_model_download_button(self, action_button) -> None:
        if action_button is None:
            return
        original = action_button.property("winsper_original_text") or "Download"
        action_button.setText(str(original))
        action_button.setEnabled(True)

    def _apply_progress_bar(self, progress_bar, progress: DownloadProgress) -> None:
        if progress_bar is None:
            return
        progress_bar.show()
        if progress.percent is None:
            progress_bar.setTextVisible(False)
            progress_bar.setRange(0, 0)
            return
        progress_bar.setTextVisible(False)
        progress_bar.setRange(0, 100)
        animate_progress_value(progress_bar, progress.percent)
