from __future__ import annotations

import queue
import threading
from dataclasses import replace

from .audio import RecordingTooShort
from .audio_factory import create_audio_recorder
from .config import AppConfig
from .models import (
    DownloadProgress,
    engine_runtime_available,
    find_speech_model,
    format_download_progress,
    installed_status,
)
from .ai_catalog import POLISH_MODELS, DEFAULT_POLISH_MODEL_ID, polish_model, runtime_candidates
from .ai_hardware import detect_ai_hardware
from .ai_runtime import (
    model_is_installed,
    runtime_is_installed,
)
from .vocabulary import effective_vocabulary
from .llama_server import bundled_llama_server_available
from .runtime_log import write_runtime_log
from .isolated_transcribe import IsolatedSpeechTranscriber
from .spoken_formatting import apply_spoken_layout
from .transcribe import clip_has_speech_activity
from .onboarding_helpers import (
    friendly_setup_error,
    speech_download_description,
)


class OnboardingTestsMixin:
    def _speech_support_ready(self) -> bool:
        preview = self._preview_config()
        preset = find_speech_model(preview.dictation.ramble_model or preview.speech.model)
        return bool(
            preset is not None and engine_runtime_available(preset.engine) and installed_status(preset, include_size=False).installed
        )

    def _polish_support_ready(self) -> bool:
        candidates = runtime_candidates(detect_ai_hardware())
        if not candidates:
            return False
        runtime_ready = bundled_llama_server_available() or any(runtime_is_installed(candidate) for candidate in candidates)
        if not runtime_ready:
            return False
        model_id = self.recommended_polish_model.id if self.recommended_polish_model is not None else DEFAULT_POLISH_MODEL_ID
        model = polish_model(model_id)
        return model_is_installed(model)

    def _set_model_ready_tick(self, label, ready: bool) -> None:
        from .settings_icons import settings_nav_icon

        label.setVisible(ready)
        label.setAccessibleName("Downloaded" if ready else "Not downloaded")
        if ready:
            label.setPixmap(settings_nav_icon("check", self.palette.success, 14).pixmap(14, 14))

    def _refresh_speech_quality_models(self, recommended_model: str) -> None:
        for profile_id, (model_label, model_tick) in self.speech_quality_models.items():
            preset = self._speech_model_for_profile(profile_id)
            if preset is None:
                model_label.setText("Unavailable")
                self._set_model_ready_tick(model_tick, False)
                continue
            ready = engine_runtime_available(preset.engine) and installed_status(preset, include_size=False).installed
            suffix = " · Recommended" if preset.model == recommended_model else ""
            model_label.setText(f"{preset.label}{suffix}")
            self._set_model_ready_tick(model_tick, ready)

    def _select_polish_model(self, model_id: str) -> None:
        if self.polish_setup_running:
            return
        try:
            selected = polish_model(model_id)
        except KeyError:
            return
        model_changed = self.config.rewrite.llama_model_id != selected.id
        self.recommended_polish_model = selected
        self._polish_provider_changed = True
        self.config.rewrite.provider = "embedded"
        self.config.rewrite.llama_model_id = selected.id
        self.config.rewrite.llama_model_path = ""
        self.polish_check.setChecked(True)
        self._refresh_polish_setup_status()
        if model_changed:
            self._stop_polish_test_runtime()
        self._ensure_polish_test_runtime()

    def _set_polish_quality_enabled(self, enabled: bool) -> None:
        if self.polish_quality_group is None:
            return
        for button in self.polish_quality_group.buttons():
            model_id = str(button.property("model_id") or "")
            model_entry = self.polish_quality_models.get(model_id)
            supported = bool(model_entry and model_entry[2].property("supported"))
            if model_entry is not None:
                model_entry[2].setEnabled(enabled and supported)
            button.setEnabled(enabled and supported)

    def _refresh_polish_quality_models(self) -> None:
        for model in POLISH_MODELS:
            entry = self.polish_quality_models.get(model.id)
            if entry is None:
                continue
            model_label, model_tick, frame = entry
            suffix = " · Recommended" if model.id == self.polish_recommended_model_id else ""
            if not frame.property("supported"):
                suffix = " · Needs more memory"
            model_label.setText(f"{model.label}{suffix}")
            self._set_model_ready_tick(model_tick, model_is_installed(model))

    def _refresh_model_status(self) -> None:
        preview = self._preview_config()
        preset = find_speech_model(preview.dictation.ramble_model or preview.speech.model)
        if preset is None:
            self.model_status.setText("Winsper could not choose compatible speech support. Try another quality option.")
            if self.model_download_button is not None:
                self.model_download_button.show()
                self.model_download_button.setEnabled(False)
            return
        self.recommended = preset
        language = str(self.language_combo.currentData() or "en")
        recommended_id = "large-v3-turbo" if self.speech_acceleration_ready else "small.en" if language == "en" else "small"
        pc_recommendation = find_speech_model(recommended_id) or preset
        highlighted_model = preset if self._is_first_run else pc_recommendation
        self._refresh_speech_quality_models(highlighted_model.model)
        ready = installed_status(preset, include_size=False).installed and engine_runtime_available(preset.engine)
        size_copy, enough_space = speech_download_description(preset.model)
        profile = self.speed_group.checkedButton()
        quality = profile.text().splitlines()[0] if profile is not None else "Balanced"
        choice = f"{quality} — {preset.label}"
        prefix = "Fast start" if self._is_first_run else f"Recommended for this PC: {pc_recommendation.label}. Selection"
        if ready:
            self.model_status.setText(f"{prefix}: {choice}. Speech support is ready.")
        elif enough_space:
            self.model_status.setText(f"{prefix}: {choice}. Requires {size_copy} once.")
        else:
            self.model_status.setText(f"{prefix}: {choice}. It needs {size_copy}, but this drive may not have enough free space.")
        if self.model_download_button is not None:
            if ready:
                self.model_download_button.hide()
            elif self.download_running:
                self.model_download_button.show()
                active = self.active_speech_download_model == preset.model
                self.model_download_button.setText("Downloading this model…" if active else "Another model is downloading…")
                self.model_download_button.setEnabled(False)
            else:
                self.model_download_button.show()
                self.model_download_button.setText(f"Download speech support · {size_copy}")
                self.model_download_button.setEnabled(enough_space)

    def _download_selected_speech_support(self) -> None:
        self._refresh_model_status()
        if self._speech_support_ready():
            return
        self._launch_download(self.recommended.model)

    def _cancel_dictation_attempt(self) -> None:
        was_recording = self.dictation_recording
        was_transcribing = self.dictation_test_running and not was_recording
        self.dictation_test_generation += 1
        self.active_dictation_test_generation = self.dictation_test_generation
        if was_recording and self.dictation_recorder is not None:
            try:
                self.dictation_recorder.stop()
            except Exception:
                pass
        if was_transcribing and self.dictation_transcriber is not None:
            self.dictation_transcriber.cancel()
        while True:
            try:
                self.dictation_test_events.get_nowait()
            except queue.Empty:
                break
        self.dictation_recording = False
        self.dictation_test_running = False
        if was_recording:
            self._show_dictation_test_hud("Cancelled", "Nothing was inserted", "cancelled")

    def _stop_dictation_test(self) -> None:
        self._cancel_dictation_attempt()
        self.dictation_runtime_generation += 1
        cancel_event = self.dictation_runtime_cancel_event
        self.dictation_runtime_cancel_event = None
        if cancel_event is not None:
            cancel_event.set()
        with self.dictation_runtime_prepare_lock:
            preparing_recorder = self.dictation_runtime_prepare_recorder
            preparing_transcriber = self.dictation_runtime_prepare_transcriber
        if preparing_transcriber is not None:
            preparing_transcriber.cancel()
        if preparing_recorder is not None:
            try:
                preparing_recorder.close()
            except Exception:
                pass
        prepare_thread = self.dictation_runtime_thread
        self.dictation_runtime_thread = None
        prepare_is_alive = getattr(prepare_thread, "is_alive", lambda: False)
        if prepare_thread is not None and prepare_thread is not threading.current_thread() and prepare_is_alive():
            prepare_thread.join(timeout=1.0)
            if prepare_is_alive():
                write_runtime_log(
                    self.config_path,
                    "onboarding Dictate preparation shutdown",
                    "Preparation did not exit within 1 second; resources were cancelled.",
                )
        self.dictation_runtime_preparing = False
        self.dictation_runtime_ready = False
        self.dictation_runtime_signature = None
        if self.dictation_timer is not None:
            self.dictation_timer.stop()
            self.dictation_timer = None
        if self.dictation_recorder is not None:
            recorder = self.dictation_recorder
            self.dictation_recorder = None
            try:
                recorder.stop()
            except Exception:
                pass
            finally:
                recorder.close()
        transcriber = self.dictation_transcriber
        self.dictation_transcriber = None
        self.dictation_speech_config = None
        if transcriber is not None:
            transcriber.close()
        while True:
            try:
                _generation, event, payload = self.dictation_runtime_events.get_nowait()
            except queue.Empty:
                break
            if event == "ready":
                stale_recorder, stale_transcriber, _speech_config, _microphone_ready = payload
                stale_recorder.close()
                stale_transcriber.close()

    def _ensure_dictation_test_runtime(self) -> None:
        config = self._preview_config()
        signature = (config.dictation.ramble_model, config.speech.language)
        if self.dictation_runtime_ready or self.dictation_runtime_preparing:
            if self.dictation_runtime_signature == signature:
                if self.index == 1:
                    if self.dictation_runtime_ready:
                        self._show_dictation_test_hud("Ready", "Hold the hotkey to speak", "idle")
                    else:
                        self._show_dictation_test_hud("Preparing Winsper", "Getting things ready", "preparing")
                return
            self._stop_dictation_test()
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.platformName().casefold() == "offscreen":
            return
        if self.index == 0:
            # Start HUD infrastructure invisibly while user chooses language
            # and quality. Step 2 can then publish Preparing/Ready immediately.
            self._prepare_dictation_test_hud()
        self.dictation_runtime_generation += 1
        generation = self.dictation_runtime_generation
        cancel_event = threading.Event()
        self.dictation_runtime_cancel_event = cancel_event
        self.dictation_runtime_preparing = True
        self.dictation_runtime_signature = signature
        if self.dictation_timer is None:
            from PySide6.QtCore import QTimer

            self.dictation_timer = QTimer(self.window)
            self.dictation_timer.timeout.connect(self._poll_dictation_test)
            self.dictation_timer.start(50)
        self.dictation_result.setText("Getting Dictate ready…")
        if self.index == 1:
            self._show_dictation_test_hud("Preparing Winsper", "Getting things ready", "preparing")
        prepare_thread = threading.Thread(
            target=self._prepare_dictation_test_runtime,
            args=(config, generation, cancel_event),
            name="WinsperOnboardingDictationPrepare",
            daemon=True,
        )
        self.dictation_runtime_thread = prepare_thread
        prepare_thread.start()

    def _prepare_dictation_test_runtime(
        self,
        config: AppConfig,
        generation: int,
        cancel_event: threading.Event | None = None,
    ) -> None:
        cancel_event = cancel_event or threading.Event()
        recorder = None
        transcriber = None
        try:
            recorder = create_audio_recorder(config.audio)
            with self.dictation_runtime_prepare_lock:
                if generation == self.dictation_runtime_generation:
                    self.dictation_runtime_prepare_recorder = recorder
            if cancel_event.is_set():
                return

            def record_device_fallback(_requested, fallback) -> None:
                config.speech.device = fallback.device
                config.speech.compute_type = fallback.compute_type
                self.dictation_runtime_events.put((generation, "fallback", fallback))

            transcriber = IsolatedSpeechTranscriber(
                config.speech,
                effective_vocabulary(config),
                on_device_fallback=record_device_fallback,
            )
            with self.dictation_runtime_prepare_lock:
                if generation == self.dictation_runtime_generation:
                    self.dictation_runtime_prepare_transcriber = transcriber
            if cancel_event.is_set():
                return
            speech_config = replace(
                transcriber.mode_config(config.dictation.ramble_model),
                purpose="dictation",
            )
            transcriber.preload_model(
                speech_config,
                progress_callback=lambda progress: self.dictation_runtime_events.put((generation, "progress", progress)),
            )
            if cancel_event.is_set():
                return
            speech_config = replace(
                transcriber.mode_config(config.dictation.ramble_model),
                purpose="dictation",
            )
            microphone_ready = bool(recorder.warm_up())
            if cancel_event.is_set() or generation != self.dictation_runtime_generation:
                return
            with self.dictation_runtime_prepare_lock:
                if self.dictation_runtime_prepare_recorder is recorder:
                    self.dictation_runtime_prepare_recorder = None
                if self.dictation_runtime_prepare_transcriber is transcriber:
                    self.dictation_runtime_prepare_transcriber = None
            self.dictation_runtime_events.put((generation, "ready", (recorder, transcriber, speech_config, microphone_ready)))
            recorder = None
            transcriber = None
        except Exception as exc:
            if not cancel_event.is_set() and generation == self.dictation_runtime_generation:
                self.dictation_runtime_events.put((generation, "prepare_error", friendly_setup_error(exc)))
        finally:
            if recorder is not None:
                recorder.close()
            if transcriber is not None:
                transcriber.close()
            with self.dictation_runtime_prepare_lock:
                if self.dictation_runtime_prepare_recorder is recorder:
                    self.dictation_runtime_prepare_recorder = None
                if self.dictation_runtime_prepare_transcriber is transcriber:
                    self.dictation_runtime_prepare_transcriber = None
            if self.dictation_runtime_thread is threading.current_thread():
                self.dictation_runtime_thread = None

    def _prepare_dictation_test_hud(self) -> None:
        if self.dictation_test_hud is not None:
            return
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.platformName().casefold() == "offscreen":
            return
        from .hud_ui import create_status_hud

        self.dictation_test_hud_stop_requested = False
        self.dictation_test_hud_ready.clear()
        hud = create_status_hud(self.config.hud)
        self.dictation_test_hud = hud

        def start_hud() -> None:
            try:
                hud.start()
                with self.dictation_test_hud_message_lock:
                    if self.dictation_test_hud is hud and not self.dictation_test_hud_stop_requested:
                        self.dictation_test_hud_ready.set()
                        pending = self.dictation_test_hud_pending_message
                        self.dictation_test_hud_pending_message = None
                    else:
                        pending = None
                if self.dictation_test_hud_stop_requested:
                    hud.stop()
                elif pending is not None:
                    hud.show(*pending)
            except Exception:
                with self.dictation_test_hud_message_lock:
                    if self.dictation_test_hud is hud:
                        self.dictation_test_hud = None
                        self.dictation_test_hud_pending_message = None
            finally:
                self.dictation_test_hud_ready.set()

        self.dictation_test_hud_thread = threading.Thread(
            target=start_hud,
            name="WinsperOnboardingHUD",
            daemon=True,
        )
        self.dictation_test_hud_thread.start()

    def _show_dictation_test_hud(self, title: str, subtitle: str, kind: str) -> None:
        if self.index not in {1, 2, 3} and self.dictation_test_hud_stop_requested:
            return
        self._prepare_dictation_test_hud()
        message = (title, subtitle, kind)
        with self.dictation_test_hud_message_lock:
            hud = self.dictation_test_hud
            if hud is None:
                return
            if self.dictation_test_hud_ready.is_set() or self.dictation_test_hud_thread is None:
                self.dictation_test_hud_pending_message = None
                show_now = True
            else:
                self.dictation_test_hud_pending_message = message
                show_now = False
        if show_now:
            hud.show(*message)

    def _stop_dictation_test_hud(self) -> None:
        self.dictation_test_hud_stop_requested = True
        with self.dictation_test_hud_message_lock:
            self.dictation_test_hud_pending_message = None
        hud = self.dictation_test_hud
        if hud is not None:
            try:
                hud.stop()
            except Exception:
                pass
        thread = self.dictation_test_hud_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.5)
        self.dictation_test_hud = None
        self.dictation_test_hud_thread = None
        self.dictation_test_hud_ready.clear()

    def _begin_dictation_recording(self) -> None:
        if not self.dictation_runtime_ready or self.dictation_recorder is None:
            self._set_dictation_practice_state(
                "process",
                "Preparing Winsper",
                "Dictate becomes active as soon as speech and microphone support are ready.",
            )
            return
        if self.dictation_test_running:
            self._set_dictation_practice_state(
                "process",
                "Finishing your last dictation",
                "Your shortcut will be ready again in a moment.",
            )
            return
        self.dictation_test_running = True
        if self.index != 3:
            self.dictation_test_passed = False
        self.dictation_recording = True
        self.dictation_test_generation += 1
        self.active_dictation_test_generation = self.dictation_test_generation
        if self.dictation_timer is None:
            from PySide6.QtCore import QTimer

            self.dictation_timer = QTimer(self.window)
            self.dictation_timer.timeout.connect(self._poll_dictation_test)
            self.dictation_timer.start(100)
        self._set_dictation_practice_state(
            "process", "Opening your microphone", "Keep holding the shortcut.", "Speak when the HUD says Listening."
        )
        if self.dictation_progress is not None:
            self.dictation_progress.hide()
            self.dictation_progress.setRange(0, 100)
            self.dictation_progress.setValue(0)
        self._start_dictation_capture(
            self.dictation_recorder,
            self.active_dictation_test_generation,
        )

    def _start_dictation_capture(self, recorder, generation: int) -> None:
        def emit(event: str, payload: object = "") -> None:
            self.dictation_test_events.put((generation, event, payload))

        try:
            recorder.start()
        except Exception as exc:
            emit("capture_error", friendly_setup_error(exc))
            return
        threading.Thread(
            target=self._monitor_dictation_first_frame,
            args=(recorder, generation),
            name="WinsperOnboardingFirstAudio",
            daemon=True,
        ).start()

    def _monitor_dictation_first_frame(self, recorder, generation: int) -> None:
        def emit(event: str, payload: object = "") -> None:
            self.dictation_test_events.put((generation, event, payload))

        if recorder.wait_for_first_frame(0.10):
            emit("capture_ready")
            return
        emit("capture_starting")
        if recorder.wait_for_first_frame(1.40):
            emit("capture_ready")
        elif self.dictation_recording and generation == self.active_dictation_test_generation:
            try:
                recorder.stop()
            except Exception:
                pass
            emit("capture_error", "Microphone started but delivered no audio.")

    def _finish_dictation_recording(self) -> None:
        if not self.dictation_recording or self.dictation_recorder is None:
            return
        generation = self.active_dictation_test_generation
        recorder = self.dictation_recorder
        self.dictation_recording = False
        transcriber = self.dictation_transcriber
        speech_config = self.dictation_speech_config
        if transcriber is None or speech_config is None:
            self.dictation_test_running = False
            return
        threading.Thread(
            target=self._stop_dictation_capture,
            args=(
                self._preview_config(),
                recorder,
                transcriber,
                speech_config,
                generation,
            ),
            name="WinsperOnboardingCaptureStop",
            daemon=True,
        ).start()

    def _stop_dictation_capture(
        self,
        config,
        recorder,
        transcriber,
        speech_config,
        generation: int,
    ) -> None:
        def emit(event: str, payload: object = "") -> None:
            self.dictation_test_events.put((generation, event, payload))

        try:
            clip = recorder.stop()
        except RecordingTooShort as exc:
            event = "silent" if self._is_no_speech_error(exc) else "too_short"
            emit(event, str(exc))
            return
        except Exception as exc:
            emit("capture_error", friendly_setup_error(exc))
            return
        emit("status", "Turning speech into text…")
        emit("result", "Processing…")
        self._run_dictation_test(config, clip, generation, transcriber, speech_config)

    def _run_dictation_test(self, config: AppConfig, clip, generation: int, transcriber, speech_config) -> None:
        def emit(event: str, payload: object) -> None:
            self.dictation_test_events.put((generation, event, payload))

        try:
            profile = config.profiles.styles.get(config.profiles.default_profile)
            raw_text = transcriber.transcribe(
                clip,
                on_partial=lambda partial: emit("partial", partial),
                profile=profile,
                config=speech_config,
            ).strip()
            if not raw_text:
                emit("silent")
                return
            text = self.dictation_corrections.apply(raw_text, config.profiles.default_profile)
            text = apply_spoken_layout(text, config.spoken_formatting.enabled)
            emit("done", text)
        except RecordingTooShort as exc:
            event = "silent" if self._is_no_speech_error(exc) else "too_short"
            emit(event, str(exc))
        except Exception as exc:
            # Worker failures do not always preserve the model's no-speech
            # wording. Audio evidence is authoritative only on this error path,
            # so genuine speech keeps its actionable failure while acoustic
            # silence always gets Winsper's normal warning state.
            if self._is_no_speech_error(exc) or not clip_has_speech_activity(clip):
                emit("silent", "")
            else:
                write_runtime_log(
                    self.config_path,
                    "onboarding Dictate transcription failure",
                    str(exc),
                    exc,
                )
                emit("error", friendly_setup_error(exc))

    @staticmethod
    def _is_no_speech_error(exc: BaseException | str) -> bool:
        text = str(exc).casefold()
        return any(
            fragment in text
            for fragment in (
                "no speech",
                "nothing heard",
                "almost no speech energy",
                "only filler speech",
                "only silence",
                "empty transcript",
                "transcript was empty",
                "nothing was captured",
                "no words were captured",
                "recording too short",
            )
        )

    def _set_dictation_practice_state(
        self,
        tone: str,
        title: str,
        detail: str,
        transcript: str | None = None,
    ) -> None:
        if self.index == 3:
            self._set_trigger_practice_state(tone, title, detail, transcript)
            return
        from .settings_icons import settings_nav_icon

        colors = {
            "success": self.palette.success,
            "warning": self.palette.coral,
            "error": self.palette.coral,
            "record": self.palette.accent,
            "process": self.palette.accent,
            "idle": self.palette.muted,
        }
        icons = {
            "success": "check",
            "warning": "warning",
            "error": "warning",
            "record": "dictation",
            "process": "dictation",
            "idle": "dictation",
        }
        color = colors.get(tone, self.palette.muted)
        icon_name = icons.get(tone, "dictation")
        self.dictation_status.setText(title)
        if self.dictation_state_hint is not None:
            self.dictation_state_hint.setText(detail)
        if self.dictation_state_icon is not None:
            self.dictation_state_icon.setPixmap(settings_nav_icon(icon_name, color, 18).pixmap(18, 18))
            self.dictation_state_icon.setProperty("tone", tone)
        if transcript is not None:
            self.dictation_result.setText(transcript)
        if self.dictation_transcript_icon is not None:
            self.dictation_transcript_icon.setPixmap(settings_nav_icon(icon_name, color, 16).pixmap(16, 16))
            self.dictation_transcript_icon.setProperty("tone", tone)

    def _poll_dictation_test(self) -> None:
        self._poll_dictation_runtime()
        if (
            self.index in {1, 2, 3}
            and self.dictation_runtime_ready
            and self.dictation_test_hud is not None
            and self.dictation_test_hud_ready.is_set()
            and self.onboarding_hotkeys is None
        ):
            self._restart_onboarding_hotkeys()
        while True:
            try:
                generation, event, payload = self.dictation_test_events.get_nowait()
            except queue.Empty:
                return
            if generation != self.active_dictation_test_generation:
                continue
            if event == "capture_starting":
                self._set_dictation_practice_state("process", "Opening your microphone", "Keep holding the shortcut.")
                self._show_dictation_test_hud("Starting", "One moment", "process")
            elif event == "capture_ready":
                if self.dictation_recording:
                    self._set_dictation_practice_state("record", "Listening", "Keep holding while you speak.")
                    self._show_dictation_test_hud("Listening", "General — release to transcribe", "record")
            elif event == "status":
                if self.index == 3:
                    self._set_trigger_practice_state("process", str(payload), "Winsper is preparing the result.")
                else:
                    self.dictation_status.setText(payload)
                if self.dictation_test_button is not None and str(payload).lower().startswith(("downloading", "loading", "preparing")):
                    self.dictation_test_button.setText("Preparing...")
                elif self.dictation_test_button is not None and str(payload).lower().startswith("transcribing"):
                    self.dictation_test_button.setText("Transcribing...")
            elif event == "result":
                if self.index == 3:
                    self._set_trigger_practice_state("process", "Turning speech into text", "Your result is appearing below.", str(payload))
                else:
                    self.dictation_result.setText(payload)
            elif event == "progress" and isinstance(payload, DownloadProgress):
                self._apply_download_progress(payload, self.dictation_status, self.dictation_progress)
                self.dictation_result.setText(format_download_progress(payload))
                if self.dictation_test_button is not None:
                    self.dictation_test_button.setText("Downloading...")
            elif event == "partial":
                self._set_dictation_practice_state("process", "Turning speech into text", "Your words are appearing below.", str(payload))
                self._show_dictation_test_hud("Transcribing", str(payload), "process")
            elif event == "done":
                if self.index == 3:
                    self.dictation_test_running = False
                    recognized = self._evaluate_trigger_dictation(str(payload))
                    self._show_dictation_test_hud(
                        "Trigger recognized" if recognized else "Try again",
                        "See the onboarding result",
                        "success" if recognized else "warning",
                    )
                    continue
                self.dictation_test_passed = True
                self.next_button.setText("Continue to Polish")
                self.dictation_test_running = False
                if self.dictation_test_button is not None:
                    self.dictation_test_button.setEnabled(True)
                    self.dictation_test_button.setText("Hold to try again")
                self._set_dictation_practice_state(
                    "success",
                    "Dictation works",
                    f"Your shortcut is {self.dictate_shortcut_recorder.value()}.",
                    str(payload),
                )
                self._show_dictation_test_hud("Dictation works", "Your words appeared in Winsper", "success")
                if self.dictation_progress is not None:
                    self.dictation_progress.hide()
            elif event == "silent":
                self.dictation_test_running = False
                self.dictation_recording = False
                silence_copy = "No speech was detected. Hold Dictate and try again."
                self._set_dictation_practice_state("warning", "Nothing heard", "No words were captured.", silence_copy)
                self._show_dictation_test_hud("Nothing heard", "No speech was detected", "warning")
                if self.dictation_progress is not None:
                    self.dictation_progress.hide()
            elif event == "too_short":
                self.dictation_test_running = False
                self.dictation_recording = False
                self._set_dictation_practice_state(
                    "warning",
                    "Nothing heard",
                    "No words were captured.",
                    "Hold Dictate a little longer and try again.",
                )
                self._show_dictation_test_hud("Too short", "Hold a little longer and try again", "warning")
            elif event == "capture_error":
                self.dictation_test_running = False
                self.dictation_recording = False
                if self._is_no_speech_error(payload):
                    silence_copy = "No speech was detected. Hold Dictate and try again."
                    self._set_dictation_practice_state("warning", "Nothing heard", "No words were captured.", silence_copy)
                    self._show_dictation_test_hud("Nothing heard", "No speech was detected", "warning")
                    continue
                self._set_dictation_practice_state(
                    "error", "Microphone needs attention", "Check your microphone and try again.", str(payload)
                )
                self._show_dictation_test_hud("Microphone error", "Check your mic and try again", "error")
            elif event == "error":
                self.dictation_test_running = False
                self.dictation_recording = False
                if self.dictation_test_button is not None:
                    self.dictation_test_button.setEnabled(True)
                    self.dictation_test_button.setText("Hold to try again")
                if self._is_no_speech_error(payload):
                    silence_copy = "No speech was detected. Hold Dictate and try again."
                    self._set_dictation_practice_state("warning", "Nothing heard", "No words were captured.", silence_copy)
                    self._show_dictation_test_hud("Nothing heard", "No speech was detected", "warning")
                    continue
                self._set_dictation_practice_state(
                    "warning",
                    "Try Dictate again",
                    "Nothing was inserted.",
                    str(payload),
                )
                self._show_dictation_test_hud("Try Dictate again", "Nothing was inserted", "warning")
                if self.dictation_progress is not None:
                    self.dictation_progress.hide()

    def _poll_dictation_runtime(self) -> None:
        while True:
            try:
                generation, event, payload = self.dictation_runtime_events.get_nowait()
            except queue.Empty:
                return
            if generation != self.dictation_runtime_generation:
                if event == "ready":
                    recorder, transcriber, _speech_config, _microphone_ready = payload
                    recorder.close()
                    transcriber.close()
                continue
            if event == "progress" and isinstance(payload, DownloadProgress):
                self._apply_download_progress(payload, self.dictation_status, self.dictation_progress)
                continue
            if event == "fallback":
                self.dictation_device_fallback = (payload.device, payload.compute_type)
                self.config.speech.device = payload.device
                self.config.speech.compute_type = payload.compute_type
                continue
            self.dictation_runtime_preparing = False
            if event == "ready":
                recorder, transcriber, speech_config, microphone_ready = payload
                self.dictation_recorder = recorder
                self.dictation_transcriber = transcriber
                self.dictation_speech_config = speech_config
                self.dictation_runtime_ready = True
                self._set_dictation_practice_state(
                    "idle",
                    "Waiting for your shortcut",
                    "Hold Dictate when you are ready to speak." if microphone_ready else "Hold Dictate to try your microphone.",
                    "What Winsper hears will appear here.",
                )
                if self.index == 1:
                    if microphone_ready:
                        self._show_dictation_test_hud("Ready", "Hold the hotkey to speak", "idle")
                    else:
                        self._show_dictation_test_hud(
                            "Microphone needs attention",
                            "Winsper will retry when you speak",
                            "warning",
                        )
                if self.onboarding_hotkeys is None:
                    self._restart_onboarding_hotkeys()
                if self.index == 2:
                    self._ensure_polish_test_runtime()
            else:
                self.dictation_runtime_ready = False
                message = friendly_setup_error(payload if isinstance(payload, BaseException) else RuntimeError(str(payload)))
                if self._is_no_speech_error(payload):
                    self._set_dictation_practice_state(
                        "warning", "Nothing heard", "No words were captured.", "No speech was detected. Hold Dictate and try again."
                    )
                else:
                    self._set_dictation_practice_state("error", "Dictation needs attention", "Check speech setup, then try again.", message)

    def _apply_download_progress(self, progress: DownloadProgress, status_label, progress_bar) -> None:
        status_label.setText(f"Downloading local support…\n{format_download_progress(progress)}")
        if progress_bar is None:
            return
        if progress.percent is None:
            progress_bar.hide()
            return
        progress_bar.show()
        progress_bar.setTextVisible(True)
        progress_bar.setRange(0, 100)
        progress_bar.setValue(progress.percent)
