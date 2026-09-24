from __future__ import annotations

import logging
import threading
import time

from .app_context import ForegroundContext, get_foreground_window_details
from .action_state import ActionPhase
from .audio import AudioCaptureDiagnostics, MicrophoneUnavailable, RecordingTooShort
from .audio_safety import is_muted_microphone_error
from .selection import SelectionResult, SelectionStatus
from .runtime_log import write_runtime_log
from .action_presentation import prepare_capture_feedback
from .app_helpers import log_runtime_error, polish_setup_issue


from .lifecycle_types import PolishSelectionCapture

POLISH_SELECTION_SETTLE_SECONDS = 0.09
POLISH_SELECTION_MODIFIER_RELEASE_SECONDS = 1.0
POLISH_SELECTION_WAIT_SECONDS = 2.5
CAPTURE_PREPARING_THRESHOLD_SECONDS = 0.10
CAPTURE_FIRST_PACKET_TIMEOUT_SECONDS = 1.50

logger = logging.getLogger(__name__)


class CaptureLifecycleMixin:
    def _on_hotkey_start(self, mode: str) -> None:
        if mode == "cancel":
            self.cancel_current_action()
            return

        replacement_thread = getattr(self, "_speech_replacement_thread", None)
        if replacement_thread is not None and replacement_thread.is_alive():
            self.hud.show(
                "Applying speech settings",
                "Ready in a moment",
                "process",
            )
            return

        if mode == "polish":
            try:
                issue = polish_setup_issue(
                    self.config,
                    (self._speech_config_for_mode("polish"),),
                )
            except Exception as exc:
                log_runtime_error("Polish readiness", exc, self.config_path)
                issue = (
                    "Polish setup unavailable",
                    "Check Settings > Polish > Advanced",
                )
            if issue is not None:
                self.hud.show(*issue, "warning")
                return

        should_stop_toggle = False
        toggle_context: ForegroundContext | None = None
        action_id = 0
        capture_monitor_cancel: threading.Event | None = None
        paused = False
        busy = False

        state = self._coordinator.query()
        if state.paused or state.pause_requested:
            paused = True
        elif state.phase is ActionPhase.PROCESSING:
            busy = True

        with self._lock:
            if paused or busy:
                pass
            elif mode == "dictate" and self._is_toggle:
                toggle_context = self._action_context
                action_id = self._coordinator.current_action_id()
                self._is_toggle = False
                self._action_context = None
                if self._coordinator.capture_to_processing(action_id):
                    self._cancel_capture_monitor(action_id)
                    should_stop_toggle = True
            elif state.phase is not ActionPhase.IDLE:
                return
            else:
                record = self._coordinator.start_capture(mode)
                if not record:
                    return
                action_id = record.action_id
                self._active_started_at = time.perf_counter()
                self._is_toggle = False
                self._action_context = None
                capture_monitor_cancel = self._install_capture_monitor(action_id)

        if paused:
            title = "Pausing" if state.pause_requested else "Paused"
            detail = "Finishing current action" if state.pause_requested else "Click the tray icon to resume"
            self.hud.show(title, detail, "warning" if state.pause_requested else "paused")
            return
        if busy:
            self.hud.show("Still cancelling", "Previous model step is finishing. Try again in a moment.", "warning")
            return

        self._cancel_rewrite_preload(defer=True)

        if should_stop_toggle:
            fallback = toggle_context or self.context_detector.detect_fast()
            self._dispatch_recording_stop("dictate", self._resolve_action_context(fallback, action_id), action_id)
            return
        start_chime = prepare_capture_feedback(self, action_id)
        if callable(start_chime):
            start_chime(action_id)
        microphone_started_at = time.perf_counter()
        try:
            with self._capture_audio_guard():
                start_metrics = self.recorder.start()
            microphone_ms = (time.perf_counter() - microphone_started_at) * 1000
            stream_start_ms = getattr(start_metrics, "stream_start_ms", microphone_ms)
            first_frame_ms = getattr(start_metrics, "first_frame_ms", microphone_ms)
            audio_attempts = getattr(start_metrics, "attempts", 1)
            if not self._coordinator.capture_ready(action_id):
                self._cancel_capture_monitor(action_id)
                try:
                    with self._capture_audio_guard():
                        self.recorder.stop()
                except Exception:
                    pass
                self._play_recording_chime("stop", action_id)
                return
            self._log_audio_warnings("recording start")
            using_fallback = bool(getattr(start_metrics, "used_fallback_device", False))
            fallback_label = str(getattr(start_metrics, "device_label", "") or "")
            initial_label = "General"
            if using_fallback:
                initial_label = "Windows default mic" if fallback_label == "Windows default microphone" else "Microphone changed"
                write_runtime_log(self.config_path, "microphone fallback", f"Temporarily using {fallback_label}.")
            listening_queued_at = time.perf_counter()
            if self._first_audio_ready(0):
                self._show_listening_hud(mode, initial_label, action_id)
            else:
                self._start_capture_truth_monitor(
                    mode,
                    initial_label,
                    action_id,
                    capture_monitor_cancel or self._install_capture_monitor(action_id),
                )
            window = get_foreground_window_details()
            self._start_context_refresh(
                window,
                mode,
                action_id,
                microphone_ms,
                (listening_queued_at - microphone_started_at) * 1000,
                stream_start_ms,
                first_frame_ms,
                audio_attempts,
            )
        except MicrophoneUnavailable as exc:
            self._discard_recording_chime(action_id)
            self._cancel_capture_monitor(action_id)
            self._log_audio_warnings("recording start")
            outcome = "microphone_muted" if is_muted_microphone_error(exc) else "microphone_unavailable"
            self._fail_action(action_id, outcome)
            log_runtime_error("recording start", exc, self.config_path)
        except Exception as exc:
            self._discard_recording_chime(action_id)
            self._cancel_capture_monitor(action_id)
            self._log_audio_warnings("recording start")
            self._fail_action(action_id, "microphone_error")
            log_runtime_error("recording start", exc, self.config_path)

    def _start_capture_truth_monitor(
        self,
        mode: str,
        initial_label: str,
        action_id: int,
        cancel_event: threading.Event,
    ) -> None:
        """Publish Listening only after Windows delivers a real audio packet."""

        def monitor() -> None:
            if self._wait_for_first_audio(CAPTURE_PREPARING_THRESHOLD_SECONDS, cancel_event):
                if not cancel_event.is_set() and self._capture_is_active(action_id):
                    self._show_listening_hud(mode, initial_label, action_id)
                return
            if cancel_event.is_set() or not self._capture_is_active(action_id):
                return
            self._show_action_message(action_id, "Preparing Winsper", "Getting microphone ready", "preparing")

            remaining = max(
                0.0,
                CAPTURE_FIRST_PACKET_TIMEOUT_SECONDS - CAPTURE_PREPARING_THRESHOLD_SECONDS,
            )
            if self._wait_for_first_audio(remaining, cancel_event):
                if not cancel_event.is_set() and self._capture_is_active(action_id):
                    self._show_listening_hud(mode, initial_label, action_id)
                return
            if not self._claim_capture_failure(
                action_id,
                "microphone_unavailable",
                cancel_event,
            ):
                return
            try:
                with self._capture_audio_guard():
                    self.recorder.stop()
            except Exception:
                pass
            self._log_audio_warnings("recording start")
            self._finalize_failed_action(action_id)
            log_runtime_error(
                "recording start",
                MicrophoneUnavailable("Microphone started but delivered no audio."),
                self.config_path,
            )

        threading.Thread(
            target=monitor,
            name=f"WinsperFirstAudio-{action_id}",
            daemon=True,
        ).start()

    def _capture_audio_guard(self) -> threading.Lock:
        lock = getattr(self, "_capture_audio_lock", None)
        if lock is None:
            # Lightweight lifecycle harnesses do not run WinsperApp.__init__.
            lock = threading.Lock()
            self._capture_audio_lock = lock
        return lock

    def _install_capture_monitor(self, action_id: int) -> threading.Event:
        previous = getattr(self, "_capture_monitor_cancel", None)
        if previous is not None:
            previous.set()
        cancel_event = threading.Event()
        self._capture_monitor_cancel = cancel_event
        self._capture_monitor_action_id = action_id
        return cancel_event

    def _cancel_capture_monitor(self, action_id: int = 0) -> None:
        current_action_id = int(getattr(self, "_capture_monitor_action_id", 0) or 0)
        if action_id and current_action_id and current_action_id != action_id:
            return
        cancel_event = getattr(self, "_capture_monitor_cancel", None)
        if cancel_event is not None:
            cancel_event.set()

    def _wait_for_first_audio(self, timeout: float, cancel_event: threading.Event) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while not cancel_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._first_audio_ready(0)
            if self._first_audio_ready(min(0.02, remaining)):
                return True
        return False

    def _claim_capture_failure(
        self,
        action_id: int,
        outcome: str,
        cancel_event: threading.Event,
    ) -> bool:
        """Atomically claim capture failure before any recorder stop occurs."""
        with self._lock:
            if cancel_event.is_set() or not self._capture_is_active(action_id):
                return False
            cancel_event.set()
            return bool(self._coordinator.fail_action(action_id, outcome))

    def _first_audio_ready(self, timeout: float) -> bool:
        recorder = getattr(self, "recorder", None)
        wait_for_first_frame = getattr(recorder, "wait_for_first_frame", None)
        if not callable(wait_for_first_frame):
            # Lightweight test/compatibility recorders complete start only after
            # capture is ready, so their successful start remains authoritative.
            return True
        return bool(wait_for_first_frame(timeout))

    def _capture_is_active(self, action_id: int) -> bool:
        state = self._coordinator.query()
        return bool(
            state.phase is ActionPhase.CAPTURING
            and state.action is not None
            and state.action.action_id == action_id
        )

    def _on_hotkey_stop(self, mode: str) -> None:
        should_toggle = False
        state = self._coordinator.query()
        if state.phase is not ActionPhase.CAPTURING or state.action is None or state.action.mode != mode:
            return
        action_id = state.action.action_id

        hotkeys = getattr(self, "hotkeys", None)
        elapsed = getattr(hotkeys, "last_activation_seconds", 0.0) if hotkeys is not None else 0.0
        if elapsed <= 0:
            elapsed = time.perf_counter() - self._active_started_at
        with self._lock:
            if mode == "dictate" and self.config.hotkeys.tap_to_toggle_dictation and elapsed <= self.config.hotkeys.toggle_tap_seconds:
                self._is_toggle = True
                should_toggle = True
            else:
                context = self._action_context
                self._is_toggle = False
                self._action_context = None
                if not self._coordinator.capture_to_processing(action_id):
                    return
                self._cancel_capture_monitor(action_id)

        if should_toggle:
            self._show_action_message(action_id, "Dictation locked", "Tap again to finish and insert", "record")
            return

        fallback = context or self.context_detector.detect_fast()
        if mode == "polish" and action_id:
            self._start_polish_selection_capture(action_id, fallback.window_hwnd)
        self._dispatch_recording_stop(mode, self._resolve_action_context(fallback, action_id), action_id)

    def _dispatch_recording_stop(self, mode: str, context: ForegroundContext, action_id: int) -> None:
        """Finish audio outside pynput's global keyboard callback thread."""
        threading.Thread(
            target=self._stop_recording_and_process,
            args=(mode, context, action_id),
            name=f"WinsperCaptureStop-{action_id}",
            daemon=True,
        ).start()

    def _start_polish_selection_capture(self, action_id: int, expected_hwnd: int = 0) -> None:
        """Copy the selection after hotkey release, before ASR can delay it."""
        capture = PolishSelectionCapture(ready=threading.Event())
        with self._lock:
            self._polish_selection_captures[action_id] = capture

        def read_selection() -> None:
            # The release callback can run while Ctrl/Alt is still physically
            # down. Let Windows settle it before sending Ctrl+C.
            time.sleep(POLISH_SELECTION_SETTLE_SECONDS)
            if not _wait_for_hotkey_modifiers_release():
                result = SelectionResult.unavailable(
                    "Polish keys were still held, so Winsper did not send a conflicting Copy shortcut.",
                    method="modifier_guard",
                )
                with self._lock:
                    capture.result = result
                    capture.ready.set()
                write_runtime_log(
                    self.config_path,
                    "selection capture",
                    f"action={action_id}; status={result.status.value}; method={result.method}; reason=modifier_timeout",
                )
                return
            try:
                if expected_hwnd and get_foreground_window_details().hwnd != expected_hwnd:
                    result = SelectionResult.target_changed()
                else:
                    result = self.inserter.read_selection(window_hwnd=expected_hwnd)
                    if expected_hwnd and get_foreground_window_details().hwnd != expected_hwnd:
                        result = SelectionResult.target_changed()
            except Exception as exc:
                result = SelectionResult.unavailable(f"Winsper could not read selected text: {exc}")
            with self._lock:
                capture.result = result
                capture.ready.set()
            write_runtime_log(
                self.config_path,
                "selection capture",
                (
                    f"action={action_id}; status={result.status.value}; method={result.method or 'none'}; "
                    f"characters={len(result.text)}"
                ),
            )
            if result.status is SelectionStatus.CAPTURED:
                coordinator = getattr(self, "_coordinator", None)
                if coordinator is not None:
                    coordinator.set_selection_size(action_id, len(result.text))

        threading.Thread(
            target=read_selection,
            name=f"WinsperSelectionCapture-{action_id}",
            daemon=True,
        ).start()

    def _selection_for_polish_action(self, action_id: int) -> SelectionResult:
        with self._lock:
            capture = self._polish_selection_captures.get(action_id)
        if capture is None:
            result = SelectionResult.unavailable("Winsper could not capture the selected text for this action.")
            logger.warning("Polish selection unavailable action=%s reason=%s", action_id, result.reason)
            return result
        if not capture.ready.wait(POLISH_SELECTION_WAIT_SECONDS):
            result = SelectionResult.unavailable(
                "Selected text did not become available in time. Select it again and retry."
            )
            logger.warning("Polish selection unavailable action=%s reason=%s", action_id, result.reason)
            return result
        result = capture.result or SelectionResult.unavailable("Selected text capture ended without a result.")
        if result.status is SelectionStatus.UNAVAILABLE:
            logger.warning("Polish selection unavailable action=%s reason=%s", action_id, result.reason)
        return result

    def _stop_recording_and_process(self, mode: str, context: ForegroundContext, action_id: int = 0) -> None:
        state = self._coordinator.query()
        if state.phase is not ActionPhase.PROCESSING or state.action is None or state.action.action_id != action_id:
            return

        stop_attempted = False
        try:
            if mode in {"dictate", "polish"}:
                speech_config = self._speech_config_for_mode(mode)
                self._show_action_message(
                    action_id,
                    "Transcribing",
                    f"{context.hud_context_label} — {speech_config.model}",
                    "process",
                )
            else:
                speech_config = self._speech_config_for_mode("rewrite")
                self._show_action_message(
                    action_id,
                    "Listening to instruction",
                    f"{context.hud_context_label} — {speech_config.model}",
                    "process",
                )
            with self._capture_audio_guard():
                stop_attempted = True
                clip = self.recorder.stop()
            self._persist_audio_identity_async()
            self._coordinator.set_clip_duration(action_id, clip.duration_seconds)
            diagnostics = getattr(self.recorder, "last_capture_diagnostics", None)
            if isinstance(diagnostics, AudioCaptureDiagnostics):
                write_runtime_log(
                    self.config_path,
                    "audio capture",
                    (
                        f"device={diagnostics.device_label}; host_api={diagnostics.host_api or 'unknown'}; "
                        f"sample_rate={diagnostics.sample_rate}; duration={diagnostics.clip_duration_seconds:.3f}s; "
                        f"peak={diagnostics.peak_level:.3f}; silent_ratio={diagnostics.silent_sample_ratio:.3f}; "
                        f"stop={diagnostics.stop_ms:.1f}ms"
                    ),
                )
        except RecordingTooShort:
            self._fail_action(action_id, "too_short")
            return
        except Exception as exc:
            self._fail_action(action_id, "microphone_error")
            log_runtime_error("recording stop", exc, self.config_path)
            return
        finally:
            if stop_attempted:
                self._play_recording_chime("stop", action_id)
            self._log_audio_warnings("recording")

        if self._action_cancelled(action_id):
            self._set_idle(action_id)
            return

        if not self._action_worker.submit(
            self._process_clip,
            mode,
            clip,
            context,
            action_id,
            queue_if_busy=True,
        ):
            self._fail_action(action_id, "worker_unavailable")

    def _show_listening_hud(self, mode: str, profile_label: str, action_id: int = 0) -> None:
        hotkeys = getattr(self, "hotkeys", None)
        elevated_toggle_active = getattr(hotkeys, "elevated_toggle_active", None)
        if callable(elevated_toggle_active) and elevated_toggle_active(mode):
            if mode == "dictate":
                self.hud.show("Listening", f"{profile_label} - press the shortcut again to copy", "record")
            else:
                self.hud.show("Listening", "Admin app - speech Polish only - press again to copy", "rewrite")
            return
        coordinator = getattr(self, "_coordinator", None)
        show_event = getattr(self.hud, "show_action_event", None)
        if coordinator is not None and action_id and callable(show_event):
            coordinator.set_context(action_id, profile_label)
            event = coordinator.latest_event()
            if event is not None and event.action_id == action_id:
                show_event(event)
                return
        if mode == "dictate":
            self.hud.show("Listening", f"{profile_label} — release to insert", "record")
        elif mode == "polish":
            self.hud.show("Listening for polish", f"{profile_label} — release to polish", "rewrite")
        else:
            self.hud.show("Say your instruction", f"{profile_label} — release to transform", "rewrite")

    def _play_recording_chime(self, phase: str, action_id: int) -> None:
        player = getattr(self, "recording_chime", None)
        callback = getattr(player, f"play_{phase}", None)
        if callable(callback):
            callback(action_id)

    def _discard_recording_chime(self, action_id: int) -> None:
        callback = getattr(getattr(self, "recording_chime", None), "discard_action", None)
        if callable(callback):
            callback(action_id)


def _wait_for_hotkey_modifiers_release() -> bool:
    """Avoid sending Ctrl+C while the user still physically holds Polish keys."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
    except Exception:
        return True
    deadline = time.monotonic() + POLISH_SELECTION_MODIFIER_RELEASE_SECONDS
    virtual_keys = (0x11, 0x12, 0x10, 0x5B, 0x5C)  # Ctrl, Alt, Shift, left/right Win.
    while time.monotonic() < deadline:
        if not any(int(user32.GetAsyncKeyState(key)) & 0x8000 for key in virtual_keys):
            return True
        time.sleep(0.01)
    return False
