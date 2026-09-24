from __future__ import annotations

import logging
import logging.handlers
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .audio_factory import create_audio_recorder
from .app_context import AppContextDetector, ForegroundContext
from .app_helpers import log_runtime_error, startup_microphone_ready
from .config import AppConfig
from .corrections import CorrectionStore
from .hotkeys import GlobalHoldHotkeys
from .history import HistoryStore
from .hud_ui import ConsoleHUD, create_status_hud
from .isolated_transcribe import IsolatedSpeechTranscriber
from .llama_server import LlamaServerModelMissing, resolve_llama_model_path
from .paste import TextInserter
from .recording_chime import RecordingChimePlayer
from .rewrite import TextRewriter
from .runtime_log import write_runtime_log
from .tray import NoopTray, WinsperTray
from .workers import BoundedWorker
from .vocabulary import effective_vocabulary

from .app_lifecycle import ListenerLifecycleMixin
from .app_pipeline import DictationPipelineMixin
from .action_state import ActionCoordinator
from .ai_catalog import should_preload_polish_model
from .ai_hardware import available_ram_gb
from .model_storage import configure_model_storage

logger = logging.getLogger(__name__)

STARTUP_TASK_TIMEOUT_SECONDS = 3.0
SHUTDOWN_PARALLEL_TIMEOUT_SECONDS = 3.0
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 3


def _configure_logging(config_path: Path) -> None:
    """Set up rotating file log for the voicepilot namespace.

    Does not touch the root logger so third-party libraries remain quiet.
    """
    log_path = config_path.parent / "voicepilot.log"
    pkg_logger = logging.getLogger("voicepilot")
    if pkg_logger.handlers:
        return  # already configured (e.g., in tests)
    pkg_logger.setLevel(logging.DEBUG)
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    pkg_logger.addHandler(handler)
    # Also surface WARNING+ to stderr so the terminal isn't completely silent.
    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    pkg_logger.addHandler(stderr_handler)


@dataclass
class LastInsertion:
    text: str = ""
    context: ForegroundContext | None = None
    history_id: str = ""


class WinsperApp(ListenerLifecycleMixin, DictationPipelineMixin):
    def __init__(self, config: AppConfig, config_path: Path) -> None:
        configure_model_storage(config.model_storage.path)
        self.config = config
        self.config_path = config_path
        self.context_detector = AppContextDetector(config)
        self.recorder = create_audio_recorder(config.audio)
        self.transcriber = self._create_transcriber(config)
        self.inserter = TextInserter(config.paste)
        self.rewriter = TextRewriter(config.rewrite, effective_vocabulary(config))
        self.corrections = CorrectionStore.for_config(
            config_path,
            max_rules=config.correction_memory.max_rules,
            enabled=config.correction_memory.enabled,
        )
        self.history = HistoryStore.for_config(
            config_path,
            max_items=config.history.max_items,
            enabled=config.history.enabled,
            retention_days=config.history.retention_days,
        )
        self.hud = create_status_hud(config.hud) if config.hud.enabled else ConsoleHUD()
        self.recording_chime = RecordingChimePlayer(config.hud.recording_chimes)
        self.tray = (
            WinsperTray(
                config,
                config_path,
                self.request_stop,
                self.pause_listening,
                self.resume_listening,
                self._copy_last_output,
            )
            if config.tray.enabled
            else NoopTray()
        )
        self.last = LastInsertion()
        self._lock = threading.Lock()
        # Recorder mutations are serialized separately from application state.
        # This keeps hotkey callbacks non-blocking while preventing a stale
        # first-packet monitor from restarting/stopping another capture phase.
        self._capture_audio_lock = threading.Lock()
        self._capture_monitor_cancel: threading.Event | None = None
        self._capture_monitor_action_id = 0
        # Single-owner state machine replacing the former scattered state vars.
        self._coordinator = ActionCoordinator()
        # _active_started_at is kept separately for hotkey toggle-tap timing.
        self._active_started_at = 0.0
        self._is_toggle = False
        self._action_context: ForegroundContext | None = None
        self._reload_pending = False
        self._reload_pending_silent = True
        self._restart_requested = False
        self._stop_event = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._shutdown_complete = threading.Event()
        self._action_worker = BoundedWorker("WinsperAction")
        self._context_thread: threading.Thread | None = None
        self._preload_thread: threading.Thread | None = None
        self._speech_replacement_thread: threading.Thread | None = None
        self._rewrite_preload_thread: threading.Thread | None = None
        self._rewrite_preload_deferred = False
        self._rewrite_preloaded_for = None
        self._rewrite_preload_rewriter = None
        self._rewrite_preload_cancel_event: threading.Event | None = None
        self._context_result: ForegroundContext | None = None
        self._context_action_id = 0
        self._polish_selection_captures = {}
        self.hotkeys: GlobalHoldHotkeys | None = None

    def _create_transcriber(self, config: AppConfig):
        return IsolatedSpeechTranscriber(
            config.speech,
            effective_vocabulary(config),
            on_device_fallback=self._persist_speech_device_fallback,
        )

    def run(self) -> None:
        startup_errors: dict[str, Exception] = {}

        def run_startup_task(name: str, callback) -> None:
            try:
                callback()
            except Exception as exc:
                startup_errors[name] = exc

        t_hud = threading.Thread(
            target=run_startup_task,
            args=("HUD", self.hud.start),
            name="WinsperHUDStartup",
            daemon=True,
        )
        t_hud.start()
        t_hud.join(timeout=STARTUP_TASK_TIMEOUT_SECONDS)
        if t_hud.is_alive():
            write_runtime_log(
                self.config_path,
                "startup timeout",
                f"HUD startup exceeded {STARTUP_TASK_TIMEOUT_SECONDS:.0f} seconds; continuing in recovery mode.",
            )
        elif "HUD" in startup_errors:
            log_runtime_error("HUD startup", startup_errors["HUD"], self.config_path)
        if "HUD" in startup_errors:
            self.hud = ConsoleHUD()
            self.hud.start()
        self.hotkeys = self._create_hotkeys()
        dictation_ready = True
        microphone_ready = True
        try:
            if self.config.speech.preload_on_startup:
                self.hud.show(
                    "Preparing Winsper",
                    "Getting things ready",
                    "preparing",
                )
                dictation_ready = self._prepare_dictation_for_startup()
            # Condition the Windows endpoint last. Keeping it active while
            # idle would violate push-to-talk privacy, but doing this after
            # model preparation minimizes first-capture driver cooldown.
            microphone_ready = startup_microphone_ready(self.recorder, self.config_path)
            if not microphone_ready:
                write_runtime_log(
                    self.config_path,
                    "microphone warm-up unavailable",
                    "Winsper will retry when dictation starts.",
                )
            self.hotkeys.start()
            if not dictation_ready:
                self.hud.show(
                    "Dictation needs attention",
                    "Check Settings, then restart Winsper",
                    "error",
                )
            elif not microphone_ready:
                self.hud.show(
                    "Microphone needs attention",
                    "Winsper will retry when you speak",
                    "warning",
                )
            else:
                self.hud.show("Ready", "Hold the hotkey to speak", "idle")
            self._write_runtime_state("listening", "Hotkeys active")
            self.tray.start()
            # Keep one terminal print for user visibility; everything else goes to the log.
            print("Winsper is running. Press Ctrl+C or choose Quit from the tray to quit.")
            logger.info("Winsper started. dictate=%s polish_enabled=%s",
                        self.config.hotkeys.dictate, self.config.dictation.polish_enabled)
            try:
                self.history.prune()
            except Exception as exc:
                log_runtime_error("history maintenance", exc, self.config_path)
            if dictation_ready:
                self._queue_or_start_rewrite_preload()
            last_responsiveness_tick = time.monotonic()
            while not self._stop_event.is_set():
                loop_started_at = time.monotonic()
                responsiveness_gap = loop_started_at - last_responsiveness_tick
                if responsiveness_gap >= 1.0:
                    available_memory = available_ram_gb()
                    memory_detail = (
                        f", available RAM {available_memory:.2f} GiB"
                        if available_memory is not None
                        else ""
                    )
                    logger.warning(
                        "Runtime heartbeat delayed by %.0f ms%s. "
                        "This can indicate Windows sleep/resume or temporary system contention.",
                        responsiveness_gap * 1000,
                        memory_detail,
                    )
                self._poll_control_command()
                time.sleep(0.2)
                last_responsiveness_tick = loop_started_at
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received; stopping.")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        with self._shutdown_lock:
            if self._shutdown_started:
                already_started = True
            else:
                self._shutdown_started = True
                already_started = False
        if already_started:
            self._shutdown_complete.wait(timeout=5.0)
            return

        coordinator = getattr(self, "_coordinator", None)
        if coordinator is not None:
            coordinator.begin_shutdown()
        self._stop_event.set()
        try:
            self._cancel_rewrite_preload(defer=False)
            self._shutdown_step("hotkeys", self.hotkeys.stop if self.hotkeys is not None else None)
            self._shutdown_step("auxiliary windows", self.tray.close_owned_windows)
            self._shutdown_step("tray", self.tray.stop)
            self._shutdown_step("active recording", self._discard_active_recording)
            self._shutdown_step("microphone", self.recorder.close)
            recording_chime = getattr(self, "recording_chime", None)
            self._shutdown_step("recording sounds", getattr(recording_chime, "close", None))
            parallel_steps = (
                ("speech backend", self._close_transcriber),
                ("rewrite backend", self.rewriter.close),
                ("HUD", self.hud.stop),
            )
            shutdown_threads = []
            for label, callback in parallel_steps:
                thread = threading.Thread(
                    target=self._shutdown_step,
                    args=(label, callback),
                    name=f"WinsperShutdown-{label.replace(' ', '-')}",
                    daemon=True,
                )
                shutdown_threads.append((label, thread))
                thread.start()
            shutdown_deadline = time.monotonic() + SHUTDOWN_PARALLEL_TIMEOUT_SECONDS
            try:
                worker_stopped = self._action_worker.stop(timeout=2.0)
            except Exception as exc:
                worker_stopped = False
                log_runtime_error("worker shutdown", exc, self.config_path)
            if not worker_stopped:
                write_runtime_log(
                    self.config_path,
                    "shutdown timeout",
                    "The active model operation exceeded the 2 second shutdown grace period.",
                )
            for label, thread in shutdown_threads:
                thread.join(timeout=max(0.0, shutdown_deadline - time.monotonic()))
                if thread.is_alive():
                    write_runtime_log(
                        self.config_path,
                        "shutdown timeout",
                        f"{label} exceeded the shutdown grace period.",
                    )
            self._join_background_thread(self._context_thread, 0.5)
            self._join_background_thread(getattr(self, "_speech_replacement_thread", None), 0.5)
            self._join_background_thread(self._preload_thread, 0.5)
            self._join_background_thread(getattr(self, "_rewrite_preload_thread", None), 0.5)
        finally:
            self._write_runtime_state("not_running", "Winsper has stopped")
            self._shutdown_complete.set()

    def _shutdown_step(self, label: str, callback) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            log_runtime_error(f"{label} shutdown", exc, self.config_path)

    def _start_rewrite_preload_if_enabled(self) -> None:
        if self._stop_event.is_set():
            return
        if (
            self._coordinator.is_busy()
            or self._action_backend_busy()
            or self._speech_background_work_active()
        ):
            with self._lock:
                self._rewrite_preload_deferred = True
            return
        if (
            not self.config.dictation.polish_enabled
            or self.config.rewrite.provider.strip().lower() not in {"embedded", "llama_cpp", "llama_server"}
            or (
                self._rewrite_preload_thread is not None
                and self._rewrite_preload_thread.is_alive()
                and self._rewrite_preload_rewriter is self.rewriter
            )
            or getattr(self, "_rewrite_preloaded_for", None) is self.rewriter
        ):
            return
        try:
            resolve_llama_model_path(self.config.rewrite)
        except LlamaServerModelMissing:
            # A model that has not been installed yet is a normal setup state.
            # Foreground Polish still reports the actionable error to the user.
            return
        if not should_preload_polish_model(
            self.config.rewrite.llama_model_id,
            model_path=self.config.rewrite.llama_model_path,
            available_memory_gb=available_ram_gb(),
        ):
            logger.info(
                "Skipping embedded Polish preload for %s because available memory is below the safe warm-up budget.",
                self.config.rewrite.llama_model_id,
            )
            return
        rewriter = self.rewriter
        cancel_event = threading.Event()

        def preload() -> None:
            try:
                if rewriter.warm_up(cancel_event=cancel_event) is False:
                    return
                with self._lock:
                    ready = self.rewriter is rewriter and not cancel_event.is_set()
                    if ready:
                        self._rewrite_preloaded_for = rewriter
                if ready:
                    write_runtime_log(
                        self.config_path,
                        "embedded Polish ready",
                        "Local AI runtime loaded in background.",
                    )
            except Exception as exc:
                log_runtime_error("embedded Polish preload", exc, self.config_path)
            finally:
                with self._lock:
                    if self._rewrite_preload_cancel_event is cancel_event:
                        self._rewrite_preload_cancel_event = None

        preload_thread = threading.Thread(
            target=preload,
            name="WinsperPolishPreload",
            daemon=True,
        )
        with self._lock:
            if (
                self._stop_event.is_set()
                or self._coordinator.is_busy()
                or self._action_backend_busy()
                or self._speech_background_work_active()
            ):
                self._rewrite_preload_deferred = not self._stop_event.is_set()
                return
            if self._rewrite_preloaded_for is rewriter or (
                self._rewrite_preload_rewriter is rewriter
                and self._rewrite_preload_cancel_event is not None
            ):
                return
            self._rewrite_preload_rewriter = rewriter
            self._rewrite_preload_cancel_event = cancel_event
            self._rewrite_preload_thread = preload_thread
        preload_thread.start()

    @staticmethod
    def _join_background_thread(thread: threading.Thread | None, timeout: float) -> None:
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=timeout)
