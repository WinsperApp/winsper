from __future__ import annotations

import os
import traceback

from .audio import AudioRecorder
from .config import AudioConfig


def _create_recorder(config: AudioConfig, first_frame_signal=None):
    """Select the production Windows engine while keeping unit tests isolated."""

    # Normal unit tests use the portable fake-friendly recorder. Explicit real
    # Windows certification must exercise the same native backend as the app.
    if (
        "PYTEST_CURRENT_TEST" in os.environ
        and os.environ.get("WINSPER_REAL_TESTS") != "1"
    ):
        return AudioRecorder(config, first_frame_signal=first_frame_signal)
    from .native_wasapi import NativeWasapiRecorder

    return NativeWasapiRecorder(config, first_frame_signal=first_frame_signal)


def _audio_worker_main(
    requests,
    responses,
    config: AudioConfig,
    first_frame_signal=None,
) -> None:
    """Own Windows audio for the worker lifetime on one process/main thread."""
    recorder = _create_recorder(config, first_frame_signal)
    try:
        while True:
            message = requests.get()
            if not isinstance(message, dict):
                continue
            request_id = str(message.get("id") or "")
            kind = str(message.get("kind") or "")
            try:
                if kind == "warm_up":
                    value = recorder.warm_up()
                elif kind == "start":
                    value = recorder.start()
                elif kind == "stop":
                    # Keep the native endpoint initialized and inactive for the
                    # next hotkey; stop never enumerates or rebuilds the route.
                    value = recorder.stop()
                elif kind == "drain_warnings":
                    value = recorder.drain_warnings()
                elif kind == "take_device_identity_update":
                    value = recorder.take_device_identity_update()
                elif kind == "close":
                    recorder.close()
                    responses.put({"kind": "result", "id": request_id, "value": True, "state": _state(recorder)})
                    return
                else:
                    raise RuntimeError(f"Unsupported audio worker command: {kind}")
                responses.put({"kind": "result", "id": request_id, "value": value, "state": _state(recorder)})
            except BaseException as exc:
                responses.put(
                    {
                        "kind": "error",
                        "id": request_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(limit=8),
                        "warnings": recorder.drain_warnings(),
                        "state": _state(recorder),
                    }
                )
    finally:
        recorder.close()


def _state(recorder) -> dict:
    return {
        "first_frame_latency_ms": recorder.first_frame_latency_ms,
        "start_attempts": recorder.start_attempts,
        "last_capture_diagnostics": recorder.last_capture_diagnostics,
    }
