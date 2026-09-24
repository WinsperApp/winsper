from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import threading
import time
import uuid
from collections.abc import Callable

from .audio import AudioClip
from .config import ProfileStyle, SpeechConfig
from .models import DownloadProgress, DownloadProgressCallback
from .transcribe import FasterWhisperTranscriber, ModelRuntimeKey, model_runtime_key
from .speech_worker_process import _speech_worker_main


class SpeechWorkerInterrupted(RuntimeError):
    """A request was cancelled because its isolated worker was replaced."""


class SpeechResourceError(RuntimeError):
    """Native speech inference could not obtain enough system memory."""


_NATIVE_ALLOCATION_ERROR_MARKERS = (
    "mkl_malloc",
    "failed to allocate memory",
    "cannot allocate memory",
    "out of memory",
    "std::bad_alloc",
    "bad allocation",
    "not enough memory resources",
)

RECEIVE_TIMEOUT_SECONDS = 120  # GPU inference hard deadline; prevents app freeze on kernel hang.
SPEECH_CLOSE_TIMEOUT_SECONDS = 1.0
logger = logging.getLogger(__name__)


def is_native_allocation_error(error: BaseException | str) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in _NATIVE_ALLOCATION_ERROR_MARKERS)


class IsolatedSpeechTranscriber:
    """Run native STT inference outside the GUI/listener process.

    faster-whisper, CTranslate2, CUDA, and sherpa-onnx can block inside native
    calls. Threads cannot safely interrupt that. A child process can be killed
    and recreated, which keeps Winsper recoverable after bad model/device states.
    """

    def __init__(
        self,
        config: SpeechConfig,
        vocabulary: list[str],
        on_device_fallback: Callable[[SpeechConfig, SpeechConfig], None] | None = None,
    ) -> None:
        self.config = config
        self.vocabulary = vocabulary
        self.on_device_fallback = on_device_fallback
        self._ctx = mp.get_context("spawn")
        self._process: mp.Process | None = None
        self._requests = None
        self._responses = None
        self._state_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._generation = 0
        self._cancel_epoch = 0
        self._closed = False
        self._foreground_waiters = 0
        self._active_preload_token: object | None = None
        self._active_preload_runtime: ModelRuntimeKey | None = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def mode_config(self, model: str | None) -> SpeechConfig:
        return FasterWhisperTranscriber(self.config, self.vocabulary).mode_config(model)

    def transcribe(
        self,
        clip: AudioClip,
        on_partial: Callable[[str], None] | None = None,
        profile: ProfileStyle | None = None,
        config: SpeechConfig | None = None,
        progress_callback: DownloadProgressCallback | None = None,
    ) -> str:
        speech_config = config or self.config
        request_epoch, resources = self._begin_foreground_request(speech_config)
        waiting = True
        try:
            if any(resource is not None for resource in resources):
                self._dispose_process(*resources, force=True)
            with self._request_lock:
                self._finish_foreground_wait()
                waiting = False
                return self._transcribe_locked(
                    clip,
                    on_partial=on_partial,
                    profile=profile,
                    config=config,
                    progress_callback=progress_callback,
                    request_epoch=request_epoch,
                )
        finally:
            if waiting:
                self._finish_foreground_wait()

    def _transcribe_locked(
        self,
        clip: AudioClip,
        on_partial: Callable[[str], None] | None = None,
        profile: ProfileStyle | None = None,
        config: SpeechConfig | None = None,
        progress_callback: DownloadProgressCallback | None = None,
        *,
        request_epoch: int,
    ) -> str:
        speech_config = config or self.config
        for attempt in range(2):
            request_id = uuid.uuid4().hex
            session = self._send(
                {
                    "kind": "transcribe",
                    "id": request_id,
                    "clip": clip,
                    "config": speech_config,
                    "profile": profile,
                    "vocabulary": list(self.vocabulary),
                },
                request_epoch=request_epoch,
            )
            while True:
                message = self._receive(request_id, session)
                kind = message.get("kind")
                if kind == "partial":
                    if on_partial is not None:
                        on_partial(str(message.get("text") or ""))
                elif kind == "progress":
                    progress = message.get("progress")
                    if progress_callback is not None and isinstance(progress, DownloadProgress):
                        progress_callback(progress)
                elif kind == "fallback":
                    self._forward_device_fallback(message)
                elif kind == "result":
                    return str(message.get("text") or "")
                elif kind == "error":
                    error = str(message.get("error") or "Speech worker failed.")
                    if not is_native_allocation_error(error):
                        raise RuntimeError(error)
                    process, generation = session[2], session[3]
                    if not self._stop_process_if_current(process, generation, force=True):
                        raise SpeechWorkerInterrupted(
                            "Speech worker was replaced while recovering from low memory."
                        )
                    if attempt == 0:
                        logger.warning(
                            "Speech inference ran out of memory; retrying once with a fresh worker."
                        )
                        break
                    raise SpeechResourceError(
                        "Windows could not provide enough memory for speech processing."
                    )
        raise SpeechResourceError("Windows could not provide enough memory for speech processing.")

    def load_model(
        self,
        config: SpeechConfig | None = None,
        progress_callback: DownloadProgressCallback | None = None,
    ) -> bool:
        request_epoch = self._capture_request_epoch()
        with self._request_lock:
            return self._load_model_locked(
                config=config,
                progress_callback=progress_callback,
                request_epoch=request_epoch,
                warm_up=False,
            )

    def preload_model(
        self,
        config: SpeechConfig | None = None,
        progress_callback: DownloadProgressCallback | None = None,
    ) -> bool:
        """Load a model only while no foreground transcription is waiting."""
        request_epoch = self._capture_request_epoch()
        with self._state_lock:
            if self._foreground_waiters:
                raise SpeechWorkerInterrupted("Speech preload yielded to a foreground request.")
        with self._request_lock:
            token = object()
            with self._state_lock:
                if self._closed:
                    raise SpeechWorkerInterrupted("Speech transcriber is closed.")
                if request_epoch != self._cancel_epoch or self._foreground_waiters:
                    raise SpeechWorkerInterrupted("Speech preload yielded to a foreground request.")
                self._active_preload_token = token
                self._active_preload_runtime = model_runtime_key(config or self.config)
            try:
                return self._load_model_locked(
                    config=config,
                    progress_callback=progress_callback,
                    request_epoch=request_epoch,
                    warm_up=True,
                )
            finally:
                with self._state_lock:
                    if self._active_preload_token is token:
                        self._active_preload_token = None
                        self._active_preload_runtime = None

    def _load_model_locked(
        self,
        config: SpeechConfig | None = None,
        progress_callback: DownloadProgressCallback | None = None,
        *,
        request_epoch: int,
        warm_up: bool,
    ) -> bool:
        request_id = uuid.uuid4().hex
        speech_config = config or self.config
        session = self._send(
            {
                "kind": "warm_up_model" if warm_up else "load_model",
                "id": request_id,
                "config": speech_config,
                "vocabulary": list(self.vocabulary),
            },
            request_epoch=request_epoch,
        )
        while True:
            message = self._receive(request_id, session)
            kind = message.get("kind")
            if kind == "progress":
                progress = message.get("progress")
                if progress_callback is not None and isinstance(progress, DownloadProgress):
                    progress_callback(progress)
            elif kind == "fallback":
                self._forward_device_fallback(message)
            elif kind == "result":
                return True
            elif kind == "error":
                error = str(message.get("error") or "Speech worker failed.")
                if is_native_allocation_error(error):
                    self._stop_process_if_current(session[2], session[3], force=True)
                    raise SpeechResourceError(
                        "Windows could not provide enough memory to load the speech model."
                    )
                raise RuntimeError(error)

    def cancel(self) -> None:
        with self._state_lock:
            self._cancel_epoch += 1
            self._active_preload_token = None
            self._active_preload_runtime = None
            resources = self._detach_process_locked()
        self._dispose_process(*resources, force=True)

    def close(self) -> None:
        # Do not wait for a native request holding _request_lock. Detaching the
        # generation interrupts that caller, and _closed prevents a queued
        # preload from creating a replacement worker after shutdown.
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._cancel_epoch += 1
            self._active_preload_token = None
            self._active_preload_runtime = None
            resources = self._detach_process_locked()
        self._dispose_process(*resources, force=False)

    def update_config(self, config: SpeechConfig, vocabulary: list[str]) -> None:
        """Update request-time speech settings without discarding warm models."""
        with self._state_lock:
            if self._closed:
                raise SpeechWorkerInterrupted("Speech transcriber is closed.")
            self.config = config
            self.vocabulary = list(vocabulary)

    def _forward_device_fallback(self, message: dict) -> None:
        requested = message.get("requested")
        fallback = message.get("fallback")
        if (
            self.on_device_fallback is not None
            and isinstance(requested, SpeechConfig)
            and isinstance(fallback, SpeechConfig)
        ):
            self.on_device_fallback(requested, fallback)

    def _capture_request_epoch(self) -> int:
        with self._state_lock:
            if self._closed:
                raise SpeechWorkerInterrupted("Speech transcriber is closed.")
            return self._cancel_epoch

    def _begin_foreground_request(
        self,
        speech_config: SpeechConfig,
    ) -> tuple[int, tuple[mp.Process | None, object, object]]:
        resources: tuple[mp.Process | None, object, object] = (None, None, None)
        requested_runtime = model_runtime_key(speech_config)
        with self._state_lock:
            if self._closed:
                raise SpeechWorkerInterrupted("Speech transcriber is closed.")
            self._foreground_waiters += 1
            if (
                self._active_preload_token is not None
                and self._active_preload_runtime != requested_runtime
            ):
                # Model loading is optional background work. Replace that
                # worker generation only when it blocks a different model.
                # If the same model is loading, finishing it is the fastest
                # path because the foreground request can reuse it immediately.
                self._cancel_epoch += 1
                self._active_preload_token = None
                self._active_preload_runtime = None
                resources = self._detach_process_locked()
            return self._cancel_epoch, resources

    def _finish_foreground_wait(self) -> None:
        with self._state_lock:
            self._foreground_waiters = max(0, self._foreground_waiters - 1)

    def _send(
        self,
        payload: dict,
        *,
        request_epoch: int,
    ) -> tuple[object, object, mp.Process, int]:
        for _attempt in range(2):
            with self._state_lock:
                if request_epoch != self._cancel_epoch:
                    raise SpeechWorkerInterrupted("Speech request was cancelled before it started.")
                self._ensure_process_locked()
                requests = self._requests
                responses = self._responses
                process = self._process
                generation = self._generation
                assert requests is not None and responses is not None and process is not None
                try:
                    requests.put(payload)
                    return requests, responses, process, generation
                except Exception:
                    resources = self._detach_process_locked()
            self._dispose_process(*resources, force=True)
        raise SpeechWorkerInterrupted("Speech worker could not accept the request.")

    def _receive(self, request_id: str, session: tuple[object, object, mp.Process, int]) -> dict:
        _requests, responses, process, generation = session
        deadline = time.monotonic() + RECEIVE_TIMEOUT_SECONDS
        while True:
            with self._state_lock:
                active = self._generation == generation and self._process is process
            if not active:
                raise SpeechWorkerInterrupted("Speech worker was replaced before the request completed.")
            try:
                process_alive = process.is_alive()
                exitcode = None if process_alive else process.exitcode
            except ValueError:
                # close()/cancel() may dispose the Windows process handle after
                # the generation check above. Treat that narrow race as the
                # same intentional worker replacement, not as an app error.
                raise SpeechWorkerInterrupted(
                    "Speech worker was closed before the request completed."
                ) from None
            if not process_alive:
                self._stop_process_if_current(process, generation, force=True)
                raise RuntimeError(f"Speech worker exited unexpectedly with code {exitcode}.")
            if time.monotonic() >= deadline:
                self._stop_process_if_current(process, generation, force=True)
                raise SpeechWorkerInterrupted(
                    f"Speech worker did not respond within {RECEIVE_TIMEOUT_SECONDS}s. "
                    "It may have hung during GPU inference."
                )
            try:
                message = responses.get(timeout=0.05)
            except queue.Empty:
                continue
            except (EOFError, OSError, ValueError):
                raise SpeechWorkerInterrupted("Speech worker was closed before the request completed.") from None
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            return message

    def _ensure_process(self) -> None:
        with self._state_lock:
            self._ensure_process_locked()

    def _ensure_process_locked(self) -> None:
        if self._closed:
            raise SpeechWorkerInterrupted("Speech transcriber is closed.")
        if self._process is not None and self._process.is_alive():
            return
        resources = self._detach_process_locked()
        self._dispose_process(*resources, force=True)
        self._requests = self._ctx.Queue()
        self._responses = self._ctx.Queue()
        self._process = self._ctx.Process(
            target=_speech_worker_main,
            args=(self._requests, self._responses, self.config, list(self.vocabulary)),
            name="WinsperSpeechWorker",
            daemon=True,
        )
        self._process.start()

    def _stop_process(self, force: bool) -> None:
        with self._state_lock:
            resources = self._detach_process_locked()
        self._dispose_process(*resources, force=force)

    def _stop_process_if_current(self, process: mp.Process, generation: int, force: bool) -> bool:
        with self._state_lock:
            if self._process is not process or self._generation != generation:
                return False
            resources = self._detach_process_locked()
        self._dispose_process(*resources, force=force)
        return True

    def _detach_process_locked(self) -> tuple[mp.Process | None, object, object]:
        process = self._process
        requests = self._requests
        responses = self._responses
        self._process = None
        self._requests = None
        self._responses = None
        self._generation += 1
        return process, requests, responses

    @staticmethod
    def _dispose_process(process: mp.Process | None, requests, responses, *, force: bool) -> None:
        graceful_exit = False
        if process is not None and process.is_alive():
            if not force and requests is not None:
                try:
                    requests.put({"kind": "stop"})
                    process.join(timeout=SPEECH_CLOSE_TIMEOUT_SECONDS)
                    graceful_exit = not process.is_alive()
                except Exception:
                    pass
            if process.is_alive():
                process.terminate()
                process.join(timeout=SPEECH_CLOSE_TIMEOUT_SECONDS)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=SPEECH_CLOSE_TIMEOUT_SECONDS)
        for pipe in (requests, responses):
            if pipe is not None:
                try:
                    # Forced cancellation may leave a large audio payload in the
                    # request feeder. Never block shutdown waiting for it to
                    # flush into a worker that has already been terminated.
                    if force or not graceful_exit:
                        pipe.cancel_join_thread()
                    pipe.close()
                    if graceful_exit:
                        pipe.join_thread()
                except Exception:
                    pass
        if process is not None and not process.is_alive():
            try:
                process.close()
            except Exception:
                pass
