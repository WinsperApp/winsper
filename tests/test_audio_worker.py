import os
import queue
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

from voicepilot.audio_worker_process import _audio_worker_main, _create_recorder
from voicepilot.config import AppConfig
from voicepilot.isolated_audio import IsolatedAudioRecorder


def test_startup_microphone_failure_keeps_app_available():
    from voicepilot.app_helpers import startup_microphone_ready
    from voicepilot.audio import MicrophoneUnavailable
    from voicepilot.isolated_audio import AudioWorkerInterrupted

    class Recorder:
        def __init__(self, failure=None):
            self.failure = failure

        def warm_up(self):
            if self.failure is not None:
                raise self.failure
            return True

    with patch("voicepilot.app_helpers.log_runtime_error") as log_error:
        assert startup_microphone_ready(Recorder(), Path("config.yaml")) is True
        for failure in (MicrophoneUnavailable("no input"), AudioWorkerInterrupted("worker exited")):
            assert startup_microphone_ready(Recorder(failure), Path("config.yaml")) is False
        assert log_error.call_count == 2


def test_real_windows_certification_uses_native_audio_backend():
    from voicepilot import native_wasapi

    config = AppConfig().audio
    first_frame = threading.Event()
    recorder = object()
    with (
        patch.dict(
            os.environ,
            {"PYTEST_CURRENT_TEST": "real hardware", "WINSPER_REAL_TESTS": "1"},
        ),
        patch.object(native_wasapi, "NativeWasapiRecorder", return_value=recorder) as factory,
    ):
        assert _create_recorder(config, first_frame) is recorder

    factory.assert_called_once_with(config, first_frame_signal=first_frame)


def test_audio_worker_reuses_healthy_inactive_stream_between_captures():
    requests = queue.Queue()
    responses = queue.Queue()
    operation_threads = []
    first_frame = threading.Event()

    class Stream:
        def __init__(self, callback):
            self.callback = callback
            operation_threads.append(("open", threading.get_ident()))

        def start(self):
            operation_threads.append(("start", threading.get_ident()))
            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            operation_threads.append(("stop", threading.get_ident()))

        def close(self):
            operation_threads.append(("close", threading.get_ident()))

    class SoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        worker = threading.Thread(
            target=_audio_worker_main,
            args=(requests, responses, config, first_frame),
        )
        worker.start()
        for request_id, kind in (
            ("1", "warm_up"),
            ("2", "start"),
            ("3", "stop"),
            ("4", "close"),
        ):
            requests.put({"id": request_id, "kind": kind})
            response = responses.get(timeout=2)
            assert response["id"] == request_id
            assert response["kind"] == "result"
            if kind == "start":
                assert first_frame.is_set()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert [name for name, _thread_id in operation_threads] == ["open", "start", "stop", "close"]
    assert len({thread_id for _name, thread_id in operation_threads}) == 1


def test_foreground_audio_requests_use_bounded_timeouts():
    recorder = IsolatedAudioRecorder.__new__(IsolatedAudioRecorder)
    recorder._first_frame = threading.Event()
    observed = []

    def request(kind, *, timeout_seconds=None, **_payload):
        observed.append((kind, timeout_seconds))
        if kind == "start":
            from voicepilot.audio import AudioStartMetrics

            return AudioStartMetrics(1.0, 0.0, 1)
        return object()

    recorder._request = request

    recorder.warm_up()
    recorder.start()
    recorder.stop()

    assert observed == [("warm_up", 9.0), ("start", 1.5), ("stop", 2.0)]


def test_audio_start_reacquires_endpoint_once_in_the_same_hotkey_action():
    from voicepilot.audio import AudioStartMetrics, MicrophoneUnavailable

    recorder = IsolatedAudioRecorder.__new__(IsolatedAudioRecorder)
    recorder._first_frame = threading.Event()
    calls = []

    def request(kind, *, timeout_seconds=None, **_payload):
        calls.append((kind, timeout_seconds))
        if len(calls) == 1:
            raise MicrophoneUnavailable("endpoint changed")
        return AudioStartMetrics(2.0, 0.0, 1, device_label="AirPods")

    recorder._request = request

    metrics = recorder.start()

    assert calls == [("start", 1.5), ("start", 1.5)]
    assert metrics.attempts == 2
    assert not metrics.used_fallback_device
    assert metrics.device_label == "AirPods"


def test_audio_start_reports_windows_mute_without_retrying():
    from voicepilot.audio import MicrophoneUnavailable

    recorder = IsolatedAudioRecorder.__new__(IsolatedAudioRecorder)
    recorder._first_frame = threading.Event()
    calls = []

    def request(kind, *, timeout_seconds=None, **_payload):
        calls.append((kind, timeout_seconds))
        raise MicrophoneUnavailable(
            "The selected microphone is muted in Windows. Unmute it and try again."
        )

    recorder._request = request

    import pytest

    with pytest.raises(MicrophoneUnavailable, match="muted in Windows"):
        recorder.start()

    assert calls == [("start", 1.5)]


def test_audio_request_timeout_replaces_hung_worker_quickly():
    class HungProcess:
        exitcode = None

        @staticmethod
        def is_alive():
            return True

    class Requests:
        @staticmethod
        def put(_message):
            return None

    class Responses:
        @staticmethod
        def get(timeout):
            time.sleep(min(timeout, 0.01))
            raise queue.Empty

    recorder = IsolatedAudioRecorder(AppConfig().audio)
    process = HungProcess()
    recorder._process = process
    recorder._requests = Requests()
    recorder._responses = Responses()
    recorder._ensure_process_locked = lambda: None
    recorder._replace_failed_process = lambda current, _generation: observed.append(current)
    observed = []

    from voicepilot.audio import MicrophoneUnavailable
    import pytest

    started = time.monotonic()
    with pytest.raises(MicrophoneUnavailable, match="stopped responding"):
        recorder._request_locked("stop", timeout_seconds=0.05)

    assert time.monotonic() - started < 0.25
    assert observed == [process]
