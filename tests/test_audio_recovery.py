from voicepilot.config import AppConfig


def test_audio_starts_prepared_inactive_stream_without_reopening():
    import sys
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

    streams = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback
            self.started = 0
            self.closed = 0

        def start(self):
            self.started += 1
            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            pass

        def close(self):
            self.closed += 1

    class SoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            stream = Stream(kwargs["callback"])
            streams.append(stream)
            return stream

    config = AppConfig().audio
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        assert recorder.warm_up()

        metrics = recorder.start()
        clip = recorder.stop()
        recorder.close()

    assert metrics.attempts == 1
    assert metrics.first_frame_received
    assert clip.samples.size == 320
    assert len(streams) == 1
    assert streams[0].started == 1
    assert streams[0].closed == 1


def test_audio_start_is_nonblocking_and_stop_keeps_first_packet():
    import sys
    import threading
    import time
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

    class Stream:
        def __init__(self, callback):
            self.callback = callback
            self.timer = None

        def start(self):
            self.timer = threading.Timer(
                0.03,
                self.callback,
                args=(np.ones((320, 1), dtype="float32"), 320, None, None),
            )
            self.timer.daemon = True
            self.timer.start()

        def stop(self):
            pass

        def close(self):
            if self.timer is not None:
                self.timer.cancel()

    class SoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            return Stream(kwargs["callback"])

    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        config = AppConfig().audio
        config.min_record_seconds = 0
        recorder = AudioRecorder(config)
        started_at = time.perf_counter()
        metrics = recorder.start()
        elapsed = time.perf_counter() - started_at
        assert elapsed < 0.02
        assert not metrics.first_frame_received
        clip = recorder.stop()
        assert clip.samples.size == 320
        recorder.close()


def test_audio_silent_stream_fails_at_stop_and_ignores_late_callback():
    import sys
    import threading
    import time
    from unittest.mock import patch

    import numpy as np
    import pytest

    from voicepilot.audio import AudioRecorder, MicrophoneUnavailable

    streams = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback
            self.closed = 0
            self.timer = None

        def start(self):
            self.timer = threading.Timer(
                0.2,
                self.callback,
                args=(np.full((320, 1), 0.5, dtype="float32"), 320, None, None),
            )
            self.timer.daemon = True
            self.timer.start()

        def stop(self):
            pass

        def close(self):
            self.closed += 1

    class SoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            stream = Stream(kwargs["callback"])
            streams.append(stream)
            return stream

    with patch.dict(sys.modules, {"sounddevice": SoundDevice}), patch(
        "voicepilot.audio.STOP_FIRST_FRAME_GRACE_SECONDS", 0.02
    ):
        config = AppConfig().audio
        config.min_record_seconds = 0
        recorder = AudioRecorder(config)
        metrics = recorder.start()
        assert not metrics.first_frame_received
        with pytest.raises(MicrophoneUnavailable, match="delivered no audio"):
            recorder.stop()
        recorder.close()
        time.sleep(0.22)

    assert metrics.attempts == 1
    assert len(streams) == 1
    assert streams[0].closed == 1


def test_audio_silent_start_rearms_same_route_and_keeps_first_recovery_packet():
    import sys
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

    streams = []

    class Stream:
        def __init__(self, callback, index):
            self.callback = callback
            self.index = index
            self.closed = 0

        def start(self):
            if self.index == 1:
                self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            pass

        def close(self):
            self.closed += 1

    class SoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            stream = Stream(kwargs["callback"], len(streams))
            streams.append(stream)
            return stream

    config = AppConfig().audio
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        metrics = recorder.start()
        assert not metrics.first_frame_received
        assert recorder.restart_if_silent()
        assert recorder.wait_for_first_frame(0.1)
        clip = recorder.stop()
        recorder.close()

    assert clip.samples.size == 320
    assert recorder.start_attempts == 2
    assert len(streams) == 2
    assert streams[0].closed == 1
    assert streams[1].closed == 1


def test_audio_does_not_rearm_after_first_packet_arrives():
    import sys
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

    streams = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    class SoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            stream = Stream(kwargs["callback"])
            streams.append(stream)
            return stream

    config = AppConfig().audio
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        recorder.start()
        assert not recorder.restart_if_silent()
        recorder.stop()
        recorder.close()

    assert len(streams) == 1


def test_audio_configured_wasapi_uses_native_sample_rate():
    import sys
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

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

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return (
                {"name": "MME", "default_input_device": 1},
                {"name": "Windows WASAPI", "default_input_device": 9},
            )

        @staticmethod
        def query_devices(*, device=None, **_kwargs):
            assert device in {9, "Microphone Array, Windows WASAPI"}
            return {
                "name": "Microphone Array",
                "hostapi": 1,
                "max_input_channels": 4,
                "default_samplerate": 48000,
            }

        @staticmethod
        def check_input_settings(*, device, samplerate, channels, **_kwargs):
            assert device == "Microphone Array, Windows WASAPI"
            if samplerate != 48000 or channels != 4:
                raise RuntimeError("Unsupported capture format")

        @staticmethod
        def InputStream(**kwargs):
            opened.append(kwargs)
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.input_device = 9
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        assert recorder.warm_up() is True
        recorder.start()
        clip = recorder.stop()

    assert opened[0]["device"] == "Microphone Array, Windows WASAPI"
    assert opened[0]["samplerate"] == 48000
    assert opened[0]["channels"] == 4
    assert clip.sample_rate == 48000
    assert clip.duration_seconds == 0.01


def test_audio_default_pins_builtin_wasapi_endpoint():
    import sys
    from unittest.mock import patch

    from voicepilot.audio import AudioRecorder

    opened = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            import numpy as np

            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    wasapi = "Microphone Array (Realtek), Windows WASAPI"
    device_info = {
        "name": "Microphone Array (Realtek)",
        "hostapi": 0,
        "max_input_channels": 4,
        "default_samplerate": 44100,
    }

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return [{"name": "Windows WASAPI"}]

        @staticmethod
        def query_devices(*, device=None, kind=None, **_kwargs):
            if device is None and kind is None:
                return [device_info]
            return device_info

        @staticmethod
        def check_input_settings(*, device, samplerate, channels, **_kwargs):
            assert device == wasapi
            if samplerate != 16000 or channels != 1:
                raise RuntimeError("Unsupported capture format")

        @staticmethod
        def InputStream(**kwargs):
            opened.append(kwargs)
            return Stream(kwargs["callback"])

    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(AppConfig().audio)
        assert recorder.warm_up() is True
        recorder.close()

    assert opened[0]["device"] == wasapi
    assert opened[0]["samplerate"] == 16000
    assert opened[0]["channels"] == 1


def test_audio_recorder_falls_back_when_saved_device_is_incompatible():
    import sys
    from types import SimpleNamespace
    from unittest.mock import patch

    from voicepilot.audio import AudioRecorder

    opened_devices = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            import numpy as np

            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    wasapi = "Microphone Array (Realtek), Windows WASAPI"
    device_info = {
        "name": "Microphone Array (Realtek)",
        "hostapi": 0,
        "max_input_channels": 1,
        "default_samplerate": 16000,
    }

    class SoundDevice:
        default = SimpleNamespace(device=(1, 2))

        @staticmethod
        def query_hostapis():
            return [{"name": "Windows WASAPI"}]

        @staticmethod
        def check_input_settings(*, device, **_kwargs):
            assert device == wasapi

        @staticmethod
        def query_devices(*, device=None, kind=None, **_kwargs):
            if device == 10:
                raise RuntimeError("stale device")
            if device is None and kind is None:
                return [device_info]
            return device_info

        @staticmethod
        def InputStream(**kwargs):
            opened_devices.append(kwargs["device"])
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.input_device = 10
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        assert recorder.warm_up() is True
        recorder.close()

    assert opened_devices == [wasapi]


def test_audio_migrates_saved_directsound_route_to_wasapi():
    import sys
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

    configured = "Microphone Array (Realtek), Windows DirectSound"
    wasapi = "Microphone Array (Realtek), Windows WASAPI"
    opened_devices = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return [{"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}]

        @staticmethod
        def query_devices(*, device=None, kind=None, **_kwargs):
            direct = {
                "name": "Microphone Array (Realtek)", "hostapi": 0,
                "max_input_channels": 1, "default_samplerate": 16000,
            }
            safe = {**direct, "hostapi": 1}
            if device is None and kind is None:
                return [direct, safe]
            return direct if device == configured else safe

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

        @staticmethod
        def InputStream(**kwargs):
            opened_devices.append(kwargs["device"])
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.input_device = configured
    config.input_device_name = "Microphone Array (Realtek)"
    config.input_device_host_api = "Windows DirectSound"
    config.input_device_channels = 1
    config.input_device_sample_rate = 16000
    config.input_device_fingerprint = "microphone array (realtek)|windows directsound|1|16000"
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        metrics = recorder.start()
        clip = recorder.stop()
        recorder.close()

    assert opened_devices == [wasapi]
    assert metrics.attempts == 1
    assert metrics.used_fallback_device is True
    assert metrics.device_label == wasapi
    assert clip.samples.size == 320
    assert config.input_device == wasapi


def test_audio_runtime_retries_same_wasapi_route_without_legacy_fallback():
    import sys
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

    configured = "Microphone Array (Realtek), Windows WASAPI"
    opened_devices = []
    start_count = 0

    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            nonlocal start_count
            start_count += 1
            if start_count == 1:
                raise RuntimeError("WASAPI endpoint temporarily unavailable")
            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return [{"name": "Windows WASAPI"}, {"name": "MME"}]

        @staticmethod
        def query_devices(*, device=None, **_kwargs):
            if device is None and not _kwargs:
                return [
                    {"name": "Microphone Array (Realtek)", "hostapi": 0, "max_input_channels": 1},
                    {"name": "Microphone Array (Realtek)", "hostapi": 1, "max_input_channels": 1},
                ]
            return {
                "name": "Microphone Array (Realtek)",
                "hostapi": 0,
                "max_input_channels": 1,
                "default_samplerate": 16000,
            }

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

        @staticmethod
        def InputStream(**kwargs):
            opened_devices.append(kwargs["device"])
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.input_device = configured
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        metrics = recorder.start()
        recorder.stop()
        recorder.close()

    assert opened_devices == [configured, configured]
    assert metrics.attempts == 2
    assert metrics.used_fallback_device is True
    assert metrics.device_label == configured
    assert config.input_device == configured


def test_audio_runtime_reports_human_error_when_no_input_endpoint_is_usable():
    import sys
    from unittest.mock import patch

    import pytest

    from voicepilot.audio import AudioRecorder, MicrophoneUnavailable

    configured = "Microphone Array (Realtek), Windows DirectSound"
    opened_devices = []

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return [{"name": "Windows DirectSound"}, {"name": "MME"}]

        @staticmethod
        def query_devices(*, device=None, kind=None, **_kwargs):
            direct = {
                "name": "Microphone Array (Realtek)",
                "hostapi": 0,
                "max_input_channels": 1,
                "default_samplerate": 16000,
            }
            mme = {**direct, "hostapi": 1}
            if device is None and kind is None:
                return [direct, mme]
            return direct

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

        @staticmethod
        def InputStream(**kwargs):
            opened_devices.append(kwargs["device"])
            raise RuntimeError("DirectSound error -2005401480")

    config = AppConfig().audio
    config.input_device = configured
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        with pytest.raises(MicrophoneUnavailable, match="No usable microphone"):
            recorder.start()
        recorder.close()

    assert opened_devices == []


def test_audio_bluetooth_output_changes_do_not_reopen_safe_input_stream():
    import sys
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

    configured = "Headset (Avery’s AirPods Pro), Windows WASAPI"
    safe_wasapi = "Microphone Array (Realtek), Windows WASAPI"
    opened = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    devices = [
        {"name": "Headset (Avery’s AirPods Pro)", "hostapi": 0, "max_input_channels": 1, "default_samplerate": 16000},
        {"name": "Microphone Array (Realtek)", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 48000},
        {"name": "Microphone Array (Realtek)", "hostapi": 1, "max_input_channels": 2, "default_samplerate": 44100},
    ]

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return [
                {"name": "Windows WASAPI", "default_input_device": 0},
                {"name": "MME", "default_input_device": 2},
            ]

        @staticmethod
        def query_devices(*, device=None, **_kwargs):
            if device is None and not _kwargs:
                return devices
            if device == configured:
                return devices[0]
            if device == safe_wasapi:
                return devices[1]
            return devices[device]

        @staticmethod
        def check_input_settings(**_kwargs):
            pass

        @staticmethod
        def InputStream(**kwargs):
            opened.append(kwargs["device"])
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.input_device = configured
    config.input_device_name = "Selected AirPods"
    config.input_device_host_api = "Windows WASAPI"
    config.input_device_fingerprint = "selected"
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        assert recorder.warm_up()
        for output_name in ("Headphones (AirPods)", "AirPods AVRCP output", ""):
            metrics = recorder.start()
            recorder.stop()
            assert metrics.attempts == 1
            recorder.close()
            if output_name:
                devices.append(
                    {
                        "name": output_name,
                        "hostapi": 0,
                        "max_input_channels": 0,
                        "max_output_channels": 2,
                        "default_samplerate": 48000,
                    }
                )
            assert recorder.warm_up()
        recorder.close()

    assert opened and set(opened) == {safe_wasapi}
    assert config.input_device == safe_wasapi
    assert config.input_device_name == "Microphone Array (Realtek)"
    assert recorder.take_device_identity_update() is not None
    assert all("MME" not in str(candidate) for candidate in opened)
