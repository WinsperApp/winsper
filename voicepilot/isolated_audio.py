from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time
import uuid
from dataclasses import replace

from .audio import (
    AudioCaptureDiagnostics,
    AudioDeviceIdentity,
    AudioStartMetrics,
    MicrophoneUnavailable,
    RecordingTooShort,
)
from .audio_worker_process import _audio_worker_main
from .audio_safety import is_muted_microphone_error
from .config import AudioConfig

AUDIO_REQUEST_TIMEOUT_SECONDS = 8.0
AUDIO_WARMUP_TIMEOUT_SECONDS = 9.0
AUDIO_START_TIMEOUT_SECONDS = 1.5
AUDIO_STOP_TIMEOUT_SECONDS = 2.0
AUDIO_CLOSE_TIMEOUT_SECONDS = 1.5


class AudioWorkerInterrupted(RuntimeError):
    """Native audio worker exited or was replaced during a request."""


class IsolatedAudioRecorder:
    """Keep Windows audio activation outside Winsper's app process.

    All stream operations execute on the worker process main thread. Hotkey,
    health-monitor, settings, and shutdown threads only send serialized RPCs.
    A native driver hang can therefore be terminated without poisoning Winsper.
    """

    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self._ctx = mp.get_context("spawn")
        self._process: mp.Process | None = None
        self._requests = None
        self._responses = None
        self._state_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._warnings_lock = threading.Lock()
        self._generation = 0
        self._closed = False
        self._cached_warnings: list[str] = []
        # Child audio callback signals this cross-process event directly.
        self._first_frame = self._ctx.Event()
        self._first_frame_latency_ms = 0.0
        self._start_attempts = 0
        self._last_capture_diagnostics = AudioCaptureDiagnostics()
        # Spawn from creator thread (normally app/Qt main thread), not from a
        # global hotkey callback. Native WASAPI stays outside the app process.
        with self._state_lock:
            self._ensure_process_locked()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @property
    def first_frame_latency_ms(self) -> float:
        return self._first_frame_latency_ms

    @property
    def start_attempts(self) -> int:
        return self._start_attempts

    @property
    def last_capture_diagnostics(self) -> AudioCaptureDiagnostics:
        return self._last_capture_diagnostics

    def warm_up(self) -> bool:
        return bool(self._request("warm_up", timeout_seconds=AUDIO_WARMUP_TIMEOUT_SECONDS))

    def start(self) -> AudioStartMetrics:
        self._first_frame.clear()
        last_error: MicrophoneUnavailable | AudioWorkerInterrupted | None = None
        for attempt in (1, 2):
            try:
                value = self._request("start", timeout_seconds=AUDIO_START_TIMEOUT_SECONDS)
            except (MicrophoneUnavailable, AudioWorkerInterrupted) as exc:
                last_error = exc
                if isinstance(exc, MicrophoneUnavailable) and is_muted_microphone_error(exc):
                    raise
                if attempt == 1:
                    continue
                raise
            if not isinstance(value, AudioStartMetrics):
                raise AudioWorkerInterrupted("Audio worker returned invalid start metrics.")
            if attempt == 2:
                return replace(
                    value,
                    attempts=max(2, value.attempts),
                )
            return value
        assert last_error is not None
        raise last_error

    def stop(self):
        return self._request("stop", timeout_seconds=AUDIO_STOP_TIMEOUT_SECONDS)

    def drain_warnings(self) -> tuple[str, ...]:
        with self._warnings_lock:
            cached = tuple(self._cached_warnings)
            self._cached_warnings = []
        with self._state_lock:
            worker_available = self._process is not None and self._process.is_alive()
        if not worker_available:
            return cached
        value = self._request("drain_warnings")
        return cached + tuple(value or ())

    def take_device_identity_update(self) -> AudioDeviceIdentity | None:
        value = self._request("take_device_identity_update")
        if value is None:
            return None
        if not isinstance(value, AudioDeviceIdentity):
            raise AudioWorkerInterrupted("Audio worker returned invalid device identity.")
        self._apply_identity(value)
        return value

    def wait_for_first_frame(self, timeout_seconds: float) -> bool:
        return self._first_frame.wait(timeout_seconds)

    def close(self) -> None:
        # Do not wait behind a native call holding _request_lock. Detaching the
        # generation wakes its caller; terminating child keeps app shutdown
        # bounded even when a Windows driver is hung.
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            process, requests, responses = self._detach_process_locked()
        self._dispose_process(process, requests, responses, graceful=True)

    def _request(self, kind: str, *, timeout_seconds: float | None = None, **payload):
        with self._request_lock:
            return self._request_locked(kind, timeout_seconds=timeout_seconds, **payload)

    def _request_locked(self, kind: str, *, timeout_seconds: float | None = None, **payload):
        request_id = uuid.uuid4().hex
        with self._state_lock:
            if self._closed:
                raise AudioWorkerInterrupted("Audio recorder is closed.")
            self._ensure_process_locked()
            process = self._process
            requests = self._requests
            responses = self._responses
            generation = self._generation
        assert process is not None and requests is not None and responses is not None
        try:
            requests.put({"kind": kind, "id": request_id, **payload})
        except Exception as exc:
            self._replace_failed_process(process, generation)
            raise AudioWorkerInterrupted("Audio worker could not accept the request.") from exc

        request_timeout = AUDIO_REQUEST_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        deadline = time.monotonic() + request_timeout
        while True:
            with self._state_lock:
                active = self._process is process and self._generation == generation
            if not active:
                raise AudioWorkerInterrupted("Audio worker was replaced before the request completed.")
            try:
                process_alive = process.is_alive()
                exitcode = None if process_alive else process.exitcode
            except ValueError:
                raise AudioWorkerInterrupted(
                    "Audio worker was closed before the request completed."
                ) from None
            if not process_alive:
                self._replace_failed_process(process, generation)
                raise AudioWorkerInterrupted(f"Audio worker exited unexpectedly with code {exitcode}.")
            if time.monotonic() >= deadline:
                self._replace_failed_process(process, generation)
                raise MicrophoneUnavailable(
                    "Microphone service stopped responding. Winsper reset it; try once more."
                )
            try:
                message = responses.get(timeout=0.05)
            except queue.Empty:
                continue
            except (EOFError, OSError, ValueError) as exc:
                self._replace_failed_process(process, generation)
                raise AudioWorkerInterrupted("Audio worker closed before the request completed.") from exc
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            self._apply_state(message.get("state"))
            if message.get("kind") == "result":
                return message.get("value")
            warnings = message.get("warnings")
            if isinstance(warnings, (list, tuple)):
                with self._warnings_lock:
                    self._cached_warnings.extend(str(item) for item in warnings)
            if kind == "start" and message.get("error_type") == "MicrophoneUnavailable":
                # A fresh worker reacquires the Windows endpoint after an
                # unplug, resume, or default-device change. A mute is a stable,
                # user-actionable state; keep the healthy worker ready for the
                # next hotkey after Windows is unmuted.
                if not is_muted_microphone_error(message.get("error")):
                    self._replace_failed_process(process, generation)
            self._raise_remote_error(message)

    def _ensure_process_locked(self) -> None:
        if self._closed:
            raise AudioWorkerInterrupted("Audio recorder is closed.")
        if self._process is not None and self._process.is_alive():
            return
        process, requests, responses = self._detach_process_locked()
        self._dispose_process(process, requests, responses, graceful=False)
        self._requests = self._ctx.Queue()
        self._responses = self._ctx.Queue()
        self._process = self._ctx.Process(
            target=_audio_worker_main,
            args=(self._requests, self._responses, self.config, self._first_frame),
            name="WinsperAudioWorker",
            daemon=True,
        )
        self._process.start()

    def _replace_failed_process(self, process, generation: int) -> None:
        with self._state_lock:
            if self._process is not process or self._generation != generation:
                return
            detached = self._detach_process_locked()
        self._dispose_process(*detached, graceful=False)

    def _detach_process_locked(self):
        process = self._process
        requests = self._requests
        responses = self._responses
        self._process = None
        self._requests = None
        self._responses = None
        self._generation += 1
        return process, requests, responses

    @staticmethod
    def _dispose_process(process, requests, responses, *, graceful: bool) -> None:
        graceful_exit = False
        if process is not None and process.is_alive():
            if graceful and requests is not None:
                try:
                    requests.put({"kind": "close", "id": uuid.uuid4().hex})
                    process.join(timeout=AUDIO_CLOSE_TIMEOUT_SECONDS)
                    graceful_exit = not process.is_alive()
                except Exception:
                    pass
            if process.is_alive():
                process.terminate()
                process.join(timeout=AUDIO_CLOSE_TIMEOUT_SECONDS)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=AUDIO_CLOSE_TIMEOUT_SECONDS)
        for channel in (requests, responses):
            if channel is not None:
                try:
                    if not graceful_exit:
                        channel.cancel_join_thread()
                    channel.close()
                    if graceful_exit:
                        channel.join_thread()
                except Exception:
                    pass
        if process is not None and not process.is_alive():
            try:
                process.close()
            except Exception:
                pass

    def _apply_state(self, state) -> None:
        if not isinstance(state, dict):
            return
        self._first_frame_latency_ms = float(state.get("first_frame_latency_ms") or 0.0)
        self._start_attempts = int(state.get("start_attempts") or 0)
        diagnostics = state.get("last_capture_diagnostics")
        if isinstance(diagnostics, AudioCaptureDiagnostics):
            self._last_capture_diagnostics = diagnostics

    def _apply_identity(self, identity: AudioDeviceIdentity) -> None:
        if identity.name and identity.host_api:
            self.config.input_device = f"{identity.name}, {identity.host_api}"
        self.config.input_device_name = identity.name
        self.config.input_device_host_api = identity.host_api
        self.config.input_device_channels = identity.channels
        self.config.input_device_sample_rate = identity.sample_rate
        self.config.input_device_fingerprint = identity.fingerprint
        self.config.last_successful_input_at = identity.successful_at

    @staticmethod
    def _raise_remote_error(message: dict) -> None:
        error_type = str(message.get("error_type") or "RuntimeError")
        error = str(message.get("error") or "Audio worker failed.")
        if error_type == "RecordingTooShort":
            raise RecordingTooShort(error)
        if error_type == "MicrophoneUnavailable":
            raise MicrophoneUnavailable(error)
        detail = str(message.get("traceback") or "").strip()
        raise RuntimeError(f"{error}\n{detail}" if detail else error)
