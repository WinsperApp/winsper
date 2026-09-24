import sys
import threading
import time
from unittest.mock import patch

import numpy as np

from voicepilot.audio import AudioRecorder
from voicepilot.config import AppConfig


def test_audio_callback_records_warning_without_printing_from_realtime_thread():
    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            self.callback(np.ones((320, 1), dtype="float32"), 320, None, "input overflow")

        def stop(self):
            pass

        def close(self):
            pass

    class SoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}), patch("builtins.print") as print_mock:
        recorder = AudioRecorder(config)
        recorder.start()
        recorder.stop()
        warnings = recorder.drain_warnings()
        recorder.close()

    print_mock.assert_not_called()
    assert "input overflow" in warnings


def test_audio_migrates_legacy_mme_identity_to_wasapi():
    mme = "Microphone Array (Realtek(R) Au, MME"
    wasapi = "Microphone Array (Realtek(R) Audio), Windows WASAPI"
    opened = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            self.callback(np.ones((441, 1), dtype="float32"), 441, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    devices = [
        {
            "name": "Microphone Array (Realtek(R) Au",
            "hostapi": 0,
            "max_input_channels": 4,
            "default_samplerate": 44100,
        },
        {
            "name": "Microphone Array (Realtek(R) Audio)",
            "hostapi": 1,
            "max_input_channels": 4,
            "default_samplerate": 48000,
        },
    ]

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return [{"name": "MME"}, {"name": "Windows WASAPI"}]

        @staticmethod
        def query_devices(*, device=None, **_kwargs):
            if device is None and not _kwargs:
                return devices
            return devices[0] if device == mme else devices[1]

        @staticmethod
        def check_input_settings(*, device, samplerate, channels, **_kwargs):
            if device != wasapi or samplerate != 48000 or channels != 1:
                raise RuntimeError("Unsupported")

        @staticmethod
        def InputStream(**kwargs):
            opened.append(kwargs)
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.input_device = mme
    config.input_device_name = devices[0]["name"]
    config.input_device_host_api = "MME"
    config.input_device_channels = 4
    config.input_device_sample_rate = 44100
    config.input_device_fingerprint = "microphone array (realtek(r) au|mme|4|44100"
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        assert recorder.warm_up()
        recorder.start()
        recorder.stop()
        recorder.close()

    assert [item["device"] for item in opened] == [wasapi]
    assert config.input_device == wasapi


def test_explicit_wasapi_route_wins_over_stale_mme_identity():
    mme = "Microphone Array (Realtek(R) Au, MME"
    wasapi = "Microphone Array (Realtek(R) Audio), Windows WASAPI"
    opened = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            self.callback(np.ones((480, 1), dtype="float32"), 480, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    devices = [
        {
            "name": "Microphone Array (Realtek(R) Au",
            "hostapi": 0,
            "max_input_channels": 4,
            "default_samplerate": 44100,
        },
        {
            "name": "Microphone Array (Realtek(R) Audio)",
            "hostapi": 1,
            "max_input_channels": 4,
            "default_samplerate": 48000,
        },
    ]

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return [{"name": "MME"}, {"name": "Windows WASAPI"}]

        @staticmethod
        def query_devices(*, device=None, **_kwargs):
            if device is None and not _kwargs:
                return devices
            return devices[0] if device == mme else devices[1]

        @staticmethod
        def check_input_settings(*, device, samplerate, channels, **_kwargs):
            if device != wasapi or samplerate != 48000 or channels != 1:
                raise RuntimeError("Unsupported")

        @staticmethod
        def InputStream(**kwargs):
            opened.append(kwargs)
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.input_device = wasapi
    config.input_device_name = devices[0]["name"]
    config.input_device_host_api = "MME"
    config.input_device_channels = 4
    config.input_device_sample_rate = 44100
    config.input_device_fingerprint = "microphone array (realtek(r) au|mme|4|44100"
    config.min_record_seconds = 0

    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        assert recorder.warm_up()
        recorder.start()
        recorder.stop()
        recorder.close()

    assert [item["device"] for item in opened] == [wasapi]


def test_audio_accepts_slow_but_healthy_cold_first_frame():
    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            timer = threading.Timer(
                0.2,
                self.callback,
                args=(np.ones((320, 1), dtype="float32"), 320, None, None),
            )
            timer.daemon = True
            timer.start()

        def stop(self):
            pass

        def close(self):
            pass

    class SoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        started = time.perf_counter()
        metrics = recorder.start()
        clip = recorder.stop()
        recorder.close()

    assert metrics.first_frame_received is False
    assert metrics.first_frame_ms == 0
    assert 180 <= recorder.first_frame_latency_ms < 500
    assert time.perf_counter() - started < 0.6
    assert metrics.attempts == 1
    assert clip.samples.size == 320
