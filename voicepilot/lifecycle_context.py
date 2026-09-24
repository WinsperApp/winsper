from __future__ import annotations

import threading
import time

from .app_context import ForegroundContext, WindowInfo
from .config import persist_audio_device_identity
from .runtime_log import write_runtime_log
from .app_helpers import (
    log_runtime_error,
)


class ActionContextMixin:
    def _start_context_refresh(
        self,
        window: WindowInfo,
        mode: str,
        action_id: int,
        microphone_ms: float = 0.0,
        listening_queued_ms: float = 0.0,
        stream_start_ms: float = 0.0,
        first_frame_ms: float = 0.0,
        audio_attempts: int = 1,
    ) -> None:
        with self._lock:
            self._context_result = None
            self._context_action_id = action_id
        thread = threading.Thread(
            target=self._refresh_action_context,
            args=(
                window,
                mode,
                action_id,
                microphone_ms,
                listening_queued_ms,
                stream_start_ms,
                first_frame_ms,
                audio_attempts,
            ),
            name="WinsperContextRefresh",
            daemon=True,
        )
        self._context_thread = thread
        thread.start()

    def _refresh_action_context(
        self,
        window: WindowInfo,
        mode: str,
        action_id: int,
        microphone_ms: float = 0.0,
        listening_queued_ms: float = 0.0,
        stream_start_ms: float = 0.0,
        first_frame_ms: float = 0.0,
        audio_attempts: int = 1,
    ) -> None:
        context_started_at = time.perf_counter()
        try:
            context = self.context_detector.detect_fast(window)
            fast_context_ms = (time.perf_counter() - context_started_at) * 1000
            self._publish_action_context(context, mode, action_id)
            context = self.context_detector.refresh_window(window)
            self._publish_action_context(context, mode, action_id)
            full_context_ms = (time.perf_counter() - context_started_at) * 1000
            recorder = getattr(self, "recorder", None)
            first_frame_ms = getattr(recorder, "first_frame_latency_ms", first_frame_ms)
            audio_attempts = getattr(recorder, "start_attempts", audio_attempts)
            write_runtime_log(
                self.config_path,
                "hotkey startup timing",
                (
                    f"mode={mode}; microphone={microphone_ms:.1f}ms; "
                    f"stream_start={stream_start_ms:.1f}ms; first_frame={first_frame_ms:.1f}ms; "
                    f"audio_attempts={audio_attempts}; "
                    f"listening_queued={listening_queued_ms:.1f}ms; "
                    f"context_fast={fast_context_ms:.1f}ms; context_full={full_context_ms:.1f}ms"
                ),
            )
        except Exception as exc:
            log_runtime_error("context refresh", exc, self.config_path)

    def _log_audio_warnings(self, stage: str) -> None:
        drain = getattr(self.recorder, "drain_warnings", None)
        if drain is None:
            return
        warnings = drain()
        if warnings:
            write_runtime_log(self.config_path, f"{stage} audio warning", " | ".join(warnings))

    def _persist_audio_identity_async(self) -> None:
        take_update = getattr(self.recorder, "take_device_identity_update", None)
        identity = take_update() if callable(take_update) else None
        if identity is None:
            return

        def persist() -> None:
            try:
                persist_audio_device_identity(
                    self.config_path,
                    name=identity.name,
                    host_api=identity.host_api,
                    fingerprint=identity.fingerprint,
                    channels=identity.channels,
                    sample_rate=identity.sample_rate,
                    successful_at=identity.successful_at,
                )
            except Exception as exc:
                log_runtime_error("audio identity persistence", exc, self.config_path)

        threading.Thread(target=persist, name="WinsperAudioIdentitySave", daemon=True).start()

    def _publish_action_context(self, context: ForegroundContext, mode: str, action_id: int) -> None:
        update_hud = False
        previous_label = ""
        with self._lock:
            if self._context_action_id == action_id:
                self._context_result = context
            if self._action_context is not None:
                previous_label = self._action_context.hud_context_label
            # Always update the fallback context with the newly resolved one
            if action_id == self._coordinator.current_action_id():
                self._action_context = context

        # Only update the HUD if we are still actively capturing for this action
        if action_id == self._coordinator.current_action_id():
            self._coordinator.set_context(action_id, context.hud_context_label)
            update_hud = context.hud_context_label != previous_label
            first_audio_ready = self._first_audio_ready(0)
            if update_hud and first_audio_ready:
                self._show_listening_hud(mode, context.hud_context_label, action_id)

    def _resolve_action_context(self, fallback: ForegroundContext, action_id: int) -> ForegroundContext:
        thread = self._context_thread
        if thread is not None and thread.is_alive():
            thread.join(0.05)
        with self._lock:
            if self._context_action_id == action_id and self._context_result is not None:
                return self._context_result
        return fallback

    def _action_cancelled(self, action_id: int) -> bool:
        if not action_id:
            return False
        # A late worker callback must never become live again after its action
        # completed and a newer action has started.
        return self._coordinator.is_cancelled(action_id) or not self._coordinator.is_active_action(action_id)
