from __future__ import annotations

import logging
import threading
import time

from .app_context import AppContextDetector, focus_window, get_foreground_window_details
from .action_state import ActionPhase, CancelOutcome, PauseOutcome
from .audio_factory import create_audio_recorder
from .config import AppConfig, load_config
from .control import consume_control_command
from .corrections import CorrectionStore
from .hotkeys import GlobalHoldHotkeys
from .history import HistoryStore
from .hud_ui import ConsoleHUD, create_status_hud
from .paste import TextInserter
from .rewrite import TextRewriter
from .runtime_log import write_runtime_log
from .runtime_state import write_runtime_state
from .tray import NoopTray, WinsperTray
from .workers import BoundedWorker
from .app_speech_backend import primary_speech_runtime_key
from .app_helpers import (
    friendly_error_message,
    log_runtime_error,
)
from .model_storage import configure_model_storage
from .vocabulary import effective_vocabulary

CANCEL_BACKEND_GRACE_SECONDS = 3.0
logger = logging.getLogger(__name__)


class LifecycleControlMixin:
    def _create_hotkeys(self) -> GlobalHoldHotkeys:
        return GlobalHoldHotkeys(
            dictate_combo=self.config.hotkeys.dictate,
            polish_combo=self.config.hotkeys.polish if self.config.dictation.polish_enabled else "",
            rewrite_combo="",
            on_start=self._on_hotkey_start,
            on_stop=self._on_hotkey_stop,
            cancel_combo=self.config.hotkeys.cancel,
            asynchronous_callbacks=True,
            windows_allow_partial=True,
        )

    @property
    def restart_requested(self) -> bool:
        return self._restart_requested

    def request_stop(self) -> None:
        self._write_runtime_state("stopping", "Quit requested")
        self._stop_event.set()

    def request_restart(self) -> None:
        self._write_runtime_state("restarting", "Restart requested")
        self._restart_requested = True
        self._stop_event.set()

    def _poll_control_command(self) -> None:
        command = consume_control_command(self.config_path)
        if command == "stop":
            self.hud.show("Stopping Winsper", "Requested locally", "process")
            self.request_stop()
        elif command == "restart":
            self.hud.show("Restarting Winsper", "Requested locally", "process")
            self.request_restart()
        elif command == "reload":
            self.reload_config()
        elif command == "reload_silent":
            self.reload_config(silent=True)
        elif command == "pause":
            self.pause_listening()
        elif command == "resume":
            self.resume_listening()
        backend_busy = self._action_backend_busy()
        busy = self._coordinator.is_busy() or backend_busy
        with self._lock:
            apply_pending_reload = self._reload_pending and not busy
            pending_reload_silent = self._reload_pending_silent
        if apply_pending_reload:
            self.reload_config(silent=pending_reload_silent)
        elif not busy:
            # The action worker clears its busy flag just after the pipeline
            # callback returns. Retry a deferred optional warm-up from the
            # regular app loop instead of adding another timer or worker.
            self._start_deferred_rewrite_preload()

    def reload_config(self, silent: bool = False) -> bool:
        reload_started_at = time.perf_counter()
        busy = self._coordinator.is_busy() or self._action_backend_busy()
        with self._lock:
            if busy:
                if self._reload_pending:
                    self._reload_pending_silent = self._reload_pending_silent and silent
                else:
                    self._reload_pending_silent = silent
                self._reload_pending = True
        if busy:
            if not silent:
                self.hud.show("Settings saved", "Will apply after current action", "warning")
            return False

        try:
            new_config = load_config(self.config_path)
        except Exception as exc:
            log_runtime_error("settings reload", exc, self.config_path)
            self.hud.show("Reload failed", friendly_error_message(exc), "error")
            return False

        old_config = self.config
        old_vocabulary = effective_vocabulary(old_config)
        new_vocabulary = effective_vocabulary(new_config)
        storage_changed = old_config.model_storage != new_config.model_storage
        configure_model_storage(new_config.model_storage.path)
        self.config = new_config
        context_changed = old_config.profiles != new_config.profiles or old_config.browser_context != new_config.browser_context
        speech_changed = (
            storage_changed
            or old_config.speech != new_config.speech
            or old_config.dictation.ramble_model != new_config.dictation.ramble_model
            or old_config.dictation.polish_enabled != new_config.dictation.polish_enabled
            or old_vocabulary != new_vocabulary
        )
        speech_runtime_changed = storage_changed or (
            speech_changed and primary_speech_runtime_key(old_config) != primary_speech_runtime_key(new_config)
        )
        rewrite_changed = storage_changed or old_config.rewrite != new_config.rewrite or old_vocabulary != new_vocabulary
        polish_became_enabled = not old_config.dictation.polish_enabled and new_config.dictation.polish_enabled
        hotkeys_changed = (
            old_config.hotkeys != new_config.hotkeys or old_config.dictation.polish_enabled != new_config.dictation.polish_enabled
        )

        if context_changed:
            self.context_detector = AppContextDetector(new_config)
        if old_config.audio != new_config.audio:
            self.recorder.close()
            self.recorder = create_audio_recorder(new_config.audio)
            self.recorder.warm_up()
        if speech_changed:
            if speech_runtime_changed:
                old_runtime = primary_speech_runtime_key(old_config)
                new_runtime = primary_speech_runtime_key(new_config)
                logger.info(
                    "Changing speech runtime from %s to %s; yielding optional Polish warm-up.",
                    old_runtime,
                    new_runtime,
                )
                # Native speech replacement can temporarily hold both model
                # runtimes in memory. Do not overlap that work with the
                # optional embedded Polish warm-up.
                self._cancel_rewrite_preload(defer=True)
                self._replace_transcriber(new_config)
            else:
                self.transcriber.update_config(new_config.speech, new_vocabulary)
                if not old_config.speech.preload_on_startup and new_config.speech.preload_on_startup:
                    self._start_background_preloads()
        if old_config.paste != new_config.paste:
            self.inserter = TextInserter(new_config.paste)
        if rewrite_changed:
            self._cancel_rewrite_preload(defer=False)
            self.rewriter.close()
            self.rewriter = TextRewriter(new_config.rewrite, new_vocabulary)
            self._rewrite_preloaded_for = None
        if rewrite_changed or polish_became_enabled:
            if not speech_runtime_changed or not new_config.speech.preload_on_startup:
                self._queue_or_start_rewrite_preload()
        if old_config.correction_memory != new_config.correction_memory:
            self.corrections = CorrectionStore.for_config(
                self.config_path,
                max_rules=new_config.correction_memory.max_rules,
                enabled=new_config.correction_memory.enabled,
            )
        else:
            self.corrections.reload()
        if old_config.history != new_config.history:
            self.history = HistoryStore.for_config(
                self.config_path,
                max_items=new_config.history.max_items,
                enabled=new_config.history.enabled,
                retention_days=new_config.history.retention_days,
            )
            self.history.prune()
        if hotkeys_changed:
            self._reload_hotkeys()
        recording_chime = getattr(self, "recording_chime", None)
        if recording_chime is not None:
            recording_chime.set_enabled(new_config.hud.recording_chimes)
        self._reload_hud(old_config, new_config)
        self._reload_tray(old_config, new_config)
        with self._lock:
            self._reload_pending = False
            self._reload_pending_silent = True
        if not silent:
            self.hud.show("Settings saved", "Applied instantly", "success")
        logger.info(
            "Settings reload completed in %.1f ms (speech_runtime_changed=%s, hotkeys_changed=%s).",
            (time.perf_counter() - reload_started_at) * 1000,
            speech_runtime_changed,
            hotkeys_changed,
        )
        return True

    def _reload_hotkeys(self) -> None:
        if self.hotkeys is not None:
            self.hotkeys.stop()
        self.hotkeys = self._create_hotkeys()
        self.hotkeys.start()
        if self.hotkeys.unavailable_modes:
            self.hud.show(
                "Shortcut needs attention",
                "Open Settings to change the unavailable shortcut",
                "warning",
            )

    def _reload_hud(self, old_config: AppConfig, new_config: AppConfig) -> None:
        presentation_fields = ("enabled", "opacity", "show_idle", "auto_hide_seconds", "theme", "mode", "position")
        if all(getattr(old_config.hud, field) == getattr(new_config.hud, field) for field in presentation_fields):
            return
        try:
            self.hud.stop()
        except Exception:
            pass
        self.hud = create_status_hud(new_config.hud) if new_config.hud.enabled else ConsoleHUD()
        self.hud.start()

    def _reload_tray(self, old_config: AppConfig, new_config: AppConfig) -> None:
        theme_changed = old_config.hud.theme != new_config.hud.theme
        if old_config.tray == new_config.tray and not theme_changed:
            if hasattr(self.tray, "config"):
                self.tray.config = new_config
                self.tray.set_paused(self._coordinator.query().paused)
            return
        try:
            self.tray.stop()
        except Exception:
            pass
        self.tray = (
            WinsperTray(
                new_config,
                self.config_path,
                self.request_stop,
                self.pause_listening,
                self.resume_listening,
                self._copy_last_output,
            )
            if new_config.tray.enabled
            else NoopTray()
        )
        self.tray.start()
        self.tray.set_paused(self._coordinator.query().paused)

    def undo_last_insertion(self) -> None:
        context = self.last.context
        if not self.last.text or context is None or not context.window_hwnd:
            self.hud.show("Nothing to undo", "Undo works for the latest insertion in this session", "warning")
            return

        current = get_foreground_window_details()
        if current.hwnd != context.window_hwnd:
            if not focus_window(context.window_hwnd):
                self.hud.show("Undo unavailable", "Original app is no longer available", "warning")
                return
            time.sleep(0.12)
            current = get_foreground_window_details()
            if current.hwnd != context.window_hwnd:
                self.hud.show("Undo blocked", "Could not safely focus the original app", "warning")
                return

        try:
            self.inserter.undo_last_paste()
        except Exception as exc:
            log_runtime_error("undo", exc, self.config_path)
            self.hud.show("Undo failed", str(exc), "error")
            return
        word_count = len(self.last.text.split())
        self.last = type(self.last)()
        self.hud.show("Undone", f"{word_count} words in {context.hud_context_label}", "success")

    def pause_listening(self) -> None:
        active_action_id = self._coordinator.current_action_id()
        outcome = self._coordinator.pause()
        if outcome is PauseOutcome.REJECTED:
            return
        with self._lock:
            self._action_context = None
        self.tray.set_paused(True)
        if outcome is PauseOutcome.PAUSED_CAPTURING:
            self._cancel_capture_monitor(active_action_id)
            try:
                with self._capture_audio_guard():
                    self.recorder.stop()
            except Exception:
                pass
            self._play_recording_chime("stop", active_action_id)
            self._write_runtime_state("paused", "Listening paused", paused=True)
            self.hud.show("Paused", "Resume from tray or Settings", "paused")
        elif outcome in {PauseOutcome.PAUSED_IDLE, PauseOutcome.ALREADY_PAUSED}:
            self._write_runtime_state("paused", "Listening paused", paused=True)
            self.hud.show("Paused", "Resume from tray or Settings", "paused")
        elif outcome is PauseOutcome.PAUSE_PROCESSING:
            action_id = self._coordinator.current_action_id()
            worker = getattr(self, "_action_worker", None)
            if worker is not None:
                worker.discard_pending(lambda _callback, args: bool(args) and args[-1] == action_id)
            self._cancel_transcriber()
            self._schedule_cancel_recovery(action_id, worker)
            self._write_runtime_state("pausing", "Finishing current action before pause", paused=True)
            self._show_action_message(action_id, "Pausing", "Finishing current action", "warning")

    def resume_listening(self) -> None:
        if not self._coordinator.resume():
            return
        self.tray.set_paused(False)
        self._write_runtime_state("listening", "Hotkeys active")
        self.hud.show("Ready", "Hotkeys active", "success")

    def cancel_current_action(self) -> None:
        action_id = self._coordinator.current_action_id()
        if not action_id:
            self.hud.show("Nothing in progress", "Winsper is ready", "idle")
            return

        worker = getattr(self, "_action_worker", None)
        outcome = self._coordinator.cancel(action_id)
        self._publish_latest_action_event(action_id)

        if outcome is CancelOutcome.CANCEL_CAPTURING:
            self._cancel_capture_monitor(action_id)
            with self._lock:
                self._action_context = None
            try:
                with self._capture_audio_guard():
                    self.recorder.stop()
            except Exception:
                pass
            self._play_recording_chime("stop", action_id)
            self._set_idle(action_id)
        elif outcome is CancelOutcome.CANCEL_PROCESSING:
            if worker is not None:
                worker.discard_pending(lambda _callback, args: bool(args) and args[-1] == action_id)
            self._cancel_transcriber()
            self._schedule_cancel_recovery(action_id, worker)

    def _schedule_cancel_recovery(self, action_id: int, worker) -> None:
        if not action_id or worker is None:
            return
        timer = threading.Timer(CANCEL_BACKEND_GRACE_SECONDS, self._recover_cancelled_backend, args=(action_id, worker))
        timer.daemon = True
        timer.start()

    def _recover_cancelled_backend(self, action_id: int, worker) -> None:
        pending_reload = False
        pending_reload_silent = True

        state = self._coordinator.query()
        current_worker = getattr(self, "_action_worker", None)
        still_cancelled = self._coordinator.is_cancelled(action_id)
        still_processing = state.phase is ActionPhase.PROCESSING and state.action and state.action.action_id == action_id
        worker_still_busy = bool(getattr(worker, "busy", False))

        if current_worker is not worker or not still_cancelled or not still_processing or not worker_still_busy:
            return

        with self._lock:
            self._action_worker = BoundedWorker("WinsperAction")
            self._close_transcriber()
            self.transcriber = self._create_transcriber(self.config)
            self._coordinator.complete_action(action_id)
            self._publish_latest_action_event(action_id)
            pending_reload = self._reload_pending
            pending_reload_silent = self._reload_pending_silent
        write_runtime_log(
            self.config_path,
            "cancel recovery",
            f"Detached stuck backend worker for action {action_id}.",
        )
        if self._coordinator.query().paused:
            self.tray.set_paused(True)
            self._write_runtime_state("paused", "Listening paused", paused=True)
            self.hud.show("Paused", "Resume from tray or Settings", "paused")
        if pending_reload:
            self.reload_config(silent=pending_reload_silent)

    def _write_runtime_state(self, status: str, detail: str = "", paused: bool | None = None) -> None:
        try:
            is_paused = self._coordinator.query().paused if paused is None else paused
            write_runtime_state(self.config_path, status, detail, paused=is_paused)
        except Exception:
            pass
