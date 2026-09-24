from __future__ import annotations

import logging
import threading
from dataclasses import replace

from .action_state import ActionPhase, CancelOutcome
from .action_presentation import ActionPresentationMixin
from .config import AppConfig, SpeechConfig, load_config, save_config
from .models import cuda_runtime_available, is_cpu_heavy_model, is_gpu_class_model
from .transcribe import FasterWhisperTranscriber, ModelRuntimeKey, model_runtime_key
from .isolated_transcribe import SpeechWorkerInterrupted
from .app_helpers import log_runtime_error, speech_progress_detail, speech_progress_title
from .runtime_log import write_runtime_log
from .vocabulary import effective_vocabulary


logger = logging.getLogger(__name__)


def primary_speech_runtime_key(config: AppConfig) -> ModelRuntimeKey:
    """Return the native runtime that must stay warm for Dictation."""
    resolver = FasterWhisperTranscriber(config.speech, effective_vocabulary(config))
    return model_runtime_key(resolver.mode_config(config.dictation.ramble_model))


class SpeechBackendLifecycleMixin(ActionPresentationMixin):
    def _action_backend_busy(self) -> bool:
        worker = getattr(self, "_action_worker", None)
        return bool(getattr(worker, "busy", False))

    def _cancel_transcriber(self) -> None:
        cancel = getattr(getattr(self, "transcriber", None), "cancel", None)
        if cancel is None:
            return
        try:
            cancel()
        except Exception as exc:
            log_runtime_error("speech cancel", exc, self.config_path)

    def _close_transcriber(self) -> None:
        close = getattr(getattr(self, "transcriber", None), "close", None)
        if close is None:
            return
        try:
            close()
        except Exception as exc:
            log_runtime_error("speech shutdown", exc, self.config_path)

    def _replace_transcriber(self, new_config) -> None:
        """Swap speech workers immediately and retire native workers in order."""
        replacement = self._create_transcriber(new_config)
        with self._lock:
            previous = self.transcriber
            previous_replacement_thread = getattr(
                self,
                "_speech_replacement_thread",
                None,
            )
            rewrite_preload_thread = getattr(self, "_rewrite_preload_thread", None)
            self.transcriber = replacement

            def retire_previous() -> None:
                try:
                    # Runtime switches are serialized. A rapid second settings
                    # change waits for the first retirement instead of loading
                    # another native model alongside it.
                    if (
                        previous_replacement_thread is not None
                        and previous_replacement_thread is not threading.current_thread()
                    ):
                        while (
                            previous_replacement_thread.is_alive()
                            and not self._stop_event.is_set()
                        ):
                            previous_replacement_thread.join(timeout=0.1)

                    # A cancelled embedded-Polish warm-up normally exits
                    # immediately. Never start another native model while it
                    # is still releasing RAM/CPU resources.
                    warned = False
                    while (
                        rewrite_preload_thread is not None
                        and rewrite_preload_thread is not threading.current_thread()
                        and rewrite_preload_thread.is_alive()
                        and not self._stop_event.is_set()
                    ):
                        rewrite_preload_thread.join(timeout=0.1)
                        if rewrite_preload_thread.is_alive() and not warned:
                            logger.info(
                                "Waiting for embedded Polish warm-up to release resources "
                                "before changing the speech runtime."
                            )
                            warned = True

                    cancel = getattr(previous, "cancel", None)
                    close = getattr(previous, "close", None)
                    for operation in (cancel, close):
                        if operation is None:
                            continue
                        try:
                            operation()
                        except Exception as exc:
                            log_runtime_error("speech replacement", exc, self.config_path)
                    if not self._stop_event.is_set() and self.transcriber is replacement:
                        self._start_preload_if_enabled()
                finally:
                    with self._lock:
                        if self._speech_replacement_thread is threading.current_thread():
                            self._speech_replacement_thread = None

            replacement_thread = threading.Thread(
                target=retire_previous,
                name="WinsperSpeechReplacement",
                daemon=True,
            )
            self._speech_replacement_thread = replacement_thread

        replacement_thread.start()

    def _speech_background_work_active(self) -> bool:
        """Return whether native speech replacement/preload is still running."""
        replacement_thread = getattr(self, "_speech_replacement_thread", None)
        preload_thread = getattr(self, "_preload_thread", None)
        return bool(
            (replacement_thread is not None and replacement_thread.is_alive())
            or (preload_thread is not None and preload_thread.is_alive())
        )

    def _set_idle(self, action_id: int = 0) -> None:
        if not action_id:
            return  # the coordinator doesn't support wildcard completions
        if self._coordinator.complete_action(action_id):
            self._publish_latest_action_event(action_id)
            with self._lock:
                self._polish_selection_captures.pop(action_id, None)
            if self._coordinator.query().paused:
                self.tray.set_paused(True)
                self._write_runtime_state("paused", "Listening paused", paused=True)
                self.hud.show("Paused", "Resume from tray or Settings", "paused")
            self._start_deferred_rewrite_preload()

    def _fail_action(self, action_id: int, outcome: str) -> None:
        """End only the matching action as failed; never complete it as success."""
        if not action_id or not self._coordinator.fail_action(action_id, outcome):
            return
        self._finalize_failed_action(action_id)

    def _finalize_failed_action(self, action_id: int) -> None:
        """Publish and clean up an action whose failure was already claimed."""
        self._publish_latest_action_event(action_id)
        with self._lock:
            self._polish_selection_captures.pop(action_id, None)
        if self._coordinator.query().paused:
            self.tray.set_paused(True)
            self._write_runtime_state("paused", "Listening paused", paused=True)
            self.hud.show("Paused", "Resume from tray or Settings", "paused")

    def _discard_active_recording(self) -> None:
        action_id = self._coordinator.current_action_id()
        if not action_id:
            return
        cancel_monitor = getattr(self, "_cancel_capture_monitor", None)
        if callable(cancel_monitor):
            cancel_monitor(action_id)
        if self._coordinator.query().phase is ActionPhase.SHUTTING_DOWN:
            try:
                with self._capture_audio_guard():
                    self.recorder.stop()
            except Exception:
                pass
            return
        outcome = self._coordinator.cancel(action_id)
        if outcome is not CancelOutcome.CANCEL_CAPTURING:
            return
        try:
            with self._capture_audio_guard():
                self.recorder.stop()
        except Exception:
            pass

    def _speech_config_for_mode(self, mode: str, transcriber=None) -> SpeechConfig:
        source = transcriber or self.transcriber
        config = source.mode_config(self._requested_model_for_mode(mode))
        purpose = "polish_instruction" if mode == "rewrite" else "dictation"
        return replace(config, purpose=purpose)

    def _requested_model_for_mode(self, mode: str) -> str:
        if mode in {"dictate", "polish", "rewrite"}:
            return self.config.dictation.ramble_model
        return self.config.speech.model

    def _model_status_text(self, context_label: str, actual_model: str) -> str:
        if is_gpu_class_model(actual_model) and (self.config.speech.device != "cuda" or not cuda_runtime_available()):
            return f"{actual_model} on CPU may be very slow"
        if is_cpu_heavy_model(actual_model) and self.config.speech.device != "cuda":
            return f"{actual_model} on CPU favors accuracy over speed"
        return f"{context_label} - {actual_model}"

    def _persist_speech_device_fallback(self, requested: SpeechConfig, fallback: SpeechConfig) -> None:
        latest = load_config(self.config_path)
        latest.speech.device = fallback.device
        latest.speech.compute_type = fallback.compute_type
        save_config(latest, self.config_path)
        with self._lock:
            self.config.speech.device = fallback.device
            self.config.speech.compute_type = fallback.compute_type
        message = (
            f"Winsper disabled {requested.device}/{requested.compute_type} after inference failed; "
            f"using {fallback.device}/{fallback.compute_type}."
        )
        logger.warning(message)
        write_runtime_log(self.config_path, "speech acceleration fallback", message)

    def _start_background_preloads(self) -> None:
        """Warm optional backends sequentially after input is already available."""
        if not self._start_preload_if_enabled():
            self._queue_or_start_rewrite_preload()

    def _prepare_dictation_for_startup(self) -> bool:
        """Block startup readiness until the production Dictation runtime is warm."""
        transcriber = self.transcriber
        speech_config = self._speech_config_for_mode("dictate", transcriber)
        return self._preload_models(transcriber, speech_config) is True

    def _start_preload_if_enabled(self) -> bool:
        if not self.config.speech.preload_on_startup or self._stop_event.is_set():
            return False
        transcriber = self.transcriber
        speech_config = self._speech_config_for_mode("dictate", transcriber)
        runtime_key = model_runtime_key(speech_config)
        if (
            self._preload_thread is not None
            and self._preload_thread.is_alive()
            and getattr(self, "_preload_transcriber", None) is transcriber
            and getattr(self, "_preload_runtime_key", None) == runtime_key
        ):
            return True
        self._preload_transcriber = transcriber
        self._preload_runtime_key = runtime_key
        self._preload_thread = threading.Thread(
            target=self._run_preload_sequence,
            args=(transcriber, speech_config),
            name="WinsperPreload",
            daemon=True,
        )
        self._preload_thread.start()
        return True

    def _run_preload_sequence(self, transcriber, speech_config: SpeechConfig) -> None:
        outcome = self._preload_models(transcriber, speech_config)
        if self._stop_event.is_set() or transcriber is not self.transcriber:
            return
        coordinator = getattr(self, "_coordinator", None)
        with self._lock:
            action_busy = coordinator is not None and coordinator.is_busy()
            if outcome is not False and not action_busy:
                self.hud.show("Ready", "Hold the hotkey to speak", "idle")
        if outcome is None:
            return
        self._queue_or_start_rewrite_preload()

    def _preload_models(
        self,
        transcriber=None,
        speech_config: SpeechConfig | None = None,
    ) -> bool | None:
        """Warm only the primary Dictation runtime; other STT models stay lazy."""
        transcriber = transcriber or self.transcriber
        speech_config = speech_config or self._speech_config_for_mode("dictate", transcriber)
        if self._stop_event.is_set() or transcriber is not self.transcriber:
            return False
        try:
            transcriber.preload_model(
                speech_config,
                progress_callback=lambda progress: self._show_preload_progress(
                    progress,
                    transcriber=transcriber,
                ),
            )
            return True
        except SpeechWorkerInterrupted:
            # Foreground use, config replacement, cancellation, and shutdown
            # intentionally interrupt optional background work.
            return False
        except Exception as exc:
            logger.warning("Optional speech preload skipped: %s", exc)
            write_runtime_log(self.config_path, "speech preload skipped", str(exc))
            return None

    def _queue_or_start_rewrite_preload(self) -> None:
        if self._stop_event.is_set():
            return
        if (
            self._coordinator.is_busy()
            or self._action_backend_busy()
            or self._speech_background_work_active()
        ):
            with self._lock:
                self._rewrite_preload_deferred = True
            logger.info(
                "Deferring embedded Polish preload until foreground/native speech work completes."
            )
            return
        self._start_rewrite_preload_if_enabled()

    def _start_deferred_rewrite_preload(self) -> None:
        with self._lock:
            should_start = bool(getattr(self, "_rewrite_preload_deferred", False))
            if should_start:
                self._rewrite_preload_deferred = False
        if should_start and not self._stop_event.is_set():
            self._queue_or_start_rewrite_preload()

    def _cancel_rewrite_preload(self, *, defer: bool) -> None:
        with self._lock:
            thread = getattr(self, "_rewrite_preload_thread", None)
            cancel_event = getattr(self, "_rewrite_preload_cancel_event", None)
            if cancel_event is None and (thread is None or not thread.is_alive()):
                return
            if cancel_event is not None:
                cancel_event.set()
            rewriter = getattr(self, "_rewrite_preload_rewriter", None)
            if defer and not self._stop_event.is_set():
                self._rewrite_preload_deferred = True
        cancel = getattr(rewriter, "cancel_warm_up", None)
        if cancel is not None:
            cancel()

    def _show_preload_progress(self, progress, *, transcriber=None) -> None:
        coordinator = getattr(self, "_coordinator", None)
        if (
            self._stop_event.is_set()
            or (transcriber is not None and transcriber is not self.transcriber)
            or (coordinator is not None and coordinator.is_busy())
        ):
            return
        status = progress.status.strip().lower()
        is_download_progress = (
            status.startswith("checking model")
            or status.startswith("downloading")
            or progress.done
        )
        if not is_download_progress:
            return
        self.hud.show(
            speech_progress_title(progress),
            speech_progress_detail(progress),
            "success" if progress.done else "process",
        )
