import weakref
from pathlib import Path

from voicepilot.config import AppConfig, ProfileStyle, load_config
from voicepilot.app_context import (
    ForegroundContext,
)
from voicepilot.paste import _paste_strategy, _process_is_elevated


def test_audio_retries_same_safe_wasapi_route_after_start_failure():
    import sys
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

    safe_wasapi = "Microphone Array, Windows WASAPI"
    opened = []
    streams = []

    class Stream:
        def __init__(self, callback, fail: bool) -> None:
            self.callback = callback
            self.fail = fail
            self.closed = 0

        def start(self) -> None:
            if self.fail:
                raise RuntimeError("WASAPI unavailable")
            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self) -> None:
            pass

        def close(self) -> None:
            self.closed += 1

    devices = [
        {"name": "Microphone Array", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 16000},
        {"name": "Microphone Array", "hostapi": 1, "max_input_channels": 2, "default_samplerate": 48000},
    ]

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return [
                {"name": "MME", "default_input_device": 0},
                {"name": "Windows WASAPI", "default_input_device": 1},
            ]

        @staticmethod
        def query_devices(*, device=None, **_kwargs):
            if device is None and not _kwargs:
                return devices
            if device == safe_wasapi:
                return devices[1]
            return devices[device]

        @staticmethod
        def check_input_settings(**_kwargs):
            pass

        @staticmethod
        def InputStream(**kwargs):
            opened.append(kwargs["device"])
            stream = Stream(kwargs["callback"], len(streams) == 0)
            streams.append(stream)
            return stream

    config = AppConfig().audio
    config.input_device = safe_wasapi
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        assert recorder.warm_up()
        first = recorder.start()
        recorder.stop()
        second = recorder.start()
        recorder.stop()
        recorder.close()

    assert opened == [safe_wasapi, safe_wasapi]
    assert first.attempts == 2
    assert first.used_fallback_device
    assert second.attempts == 1
    assert [stream.closed for stream in streams] == [1, 1]


def test_audio_device_parser_persists_named_selector():
    from voicepilot.audio import AudioRecorder
    from voicepilot.audio_safety import (
        is_ambiguous_microphone_name,
        is_bluetooth_microphone_name,
        is_muted_microphone_error,
        is_unsafe_microphone_name,
    )
    from voicepilot.system_audio import parse_input_device

    assert is_bluetooth_microphone_name("Headset (AirPods Hands-Free), Windows WASAPI")
    assert is_bluetooth_microphone_name("Headset (OnePlus Buds 3)")
    assert is_unsafe_microphone_name("Headset (AirPods Hands-Free), Windows WASAPI")
    assert not is_bluetooth_microphone_name("Microphone Array (Realtek(R) Audio)")
    assert not is_ambiguous_microphone_name("Headset (AirPods Hands-Free), Windows WASAPI")
    assert is_muted_microphone_error("The selected microphone is muted in Windows.")
    assert is_muted_microphone_error("The microphone input level is set to zero in Windows.")
    assert not is_muted_microphone_error("Only silence was captured.")
    assert is_unsafe_microphone_name("Microsoft Sound Mapper - Input, MME")
    assert AudioRecorder._same_physical_device_name(
        "Microphone Array (Realtek(R) Audio)",
        "Microphone Array (Realtek(R) Au",
    )
    assert parse_input_device("9: Microphone Array, Windows WASAPI") == "Microphone Array, Windows WASAPI"
    assert parse_input_device("Microphone Array, Windows WASAPI") == "Microphone Array, Windows WASAPI"
    assert parse_input_device("10") == 10
    assert parse_input_device("Windows default") is None


def test_settings_audio_devices_only_show_supported_unique_input_routes(monkeypatch):
    import sys
    from types import SimpleNamespace

    class PortAudioError(Exception):
        pass

    devices = [
        {"name": "Microphone Array (Realtek(R) Au", "hostapi": 0, "max_input_channels": 2},
        {"name": "Microphone Array (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 2},
        {"name": "Microphone Array (Realtek(R) Audio)", "hostapi": 2, "max_input_channels": 2},
        {"name": "USB Conference Mic", "hostapi": 0, "max_input_channels": 1},
        {"name": "Rode NT-USB+", "hostapi": 1, "max_input_channels": 2},
        {"name": "AirPods Hands-Free", "hostapi": 1, "max_input_channels": 1},
        {"name": "Speakers", "hostapi": 1, "max_input_channels": 0},
    ]
    hosts = [
        {"name": "MME"},
        {"name": "Windows WASAPI"},
        {"name": "Windows DirectSound"},
    ]

    def query_devices(selector=None, *, kind=None):
        if selector is None:
            return devices
        assert kind == "input"
        return next(
            device
            for device in devices
            if f"{device['name']}, {hosts[device['hostapi']]['name']}" == selector
        )

    fake_sounddevice = SimpleNamespace(
        PortAudioError=PortAudioError,
        query_devices=query_devices,
        query_hostapis=lambda: hosts,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)

    from voicepilot.system_audio import list_audio_devices

    assert list_audio_devices() == [
        "Microphone Array (Realtek(R) Audio), Windows WASAPI",
        "Rode NT-USB+, Windows WASAPI",
    ]


def test_audio_recorder_callback_does_not_prevent_immediate_cleanup():
    import sys
    from unittest.mock import patch

    from voicepilot.audio import AudioRecorder

    streams = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback
            self.stopped = 0
            self.closed = 0

        def start(self):
            import numpy as np

            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            self.stopped += 1

        def close(self):
            self.closed += 1

    class SoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            stream = Stream(kwargs["callback"])
            streams.append(stream)
            return stream

    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(AppConfig().audio)
        recorder.warm_up()
        recorder_ref = weakref.ref(recorder)
        del recorder

    assert recorder_ref() is None
    assert streams[0].closed == 1


def test_audio_resolves_saved_device_identity_after_windows_reindexes_it():
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

    devices = [
        {"name": "Other mic", "hostapi": 0, "max_input_channels": 1, "default_samplerate": 16000},
        {"name": "USB mic", "hostapi": 1, "max_input_channels": 2, "default_samplerate": 48000},
    ]

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return [{"name": "MME"}, {"name": "Windows WASAPI"}]

        @staticmethod
        def query_devices(*, device=None, **_kwargs):
            if device is None and not _kwargs:
                return devices
            if device == "USB mic, Windows WASAPI":
                return devices[1]
            return devices[device]

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

        @staticmethod
        def InputStream(**kwargs):
            opened.append(kwargs["device"])
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.input_device = 9  # stale Windows index
    config.input_device_name = "USB mic"
    config.input_device_host_api = "Windows WASAPI"
    config.input_device_fingerprint = "usb mic|windows wasapi|2|48000"
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        recorder.start()
        recorder.stop()
        recorder.close()

    assert opened == ["USB mic, Windows WASAPI"]
    assert config.last_successful_input_at > 0
    assert config.input_device_fingerprint == "usb mic|windows wasapi|2|48000"


def test_audio_capture_diagnostics_report_signal_and_stop_cost():
    import sys
    from unittest.mock import patch

    import numpy as np
    import pytest

    from voicepilot.audio import AudioRecorder

    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def start(self):
            self.callback(np.array([[0.0], [0.5], [0.0]], dtype="float32"), 3, None, None)

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
        recorder.start()
        recorder.stop()

    diagnostics = recorder.last_capture_diagnostics
    assert diagnostics.peak_level == 0.5
    assert diagnostics.silent_sample_ratio == pytest.approx(2 / 3)
    assert diagnostics.stop_ms >= 0


def test_wasapi_capture_uses_native_mix_rate_when_configured_rate_is_rejected():
    from voicepilot.audio import AudioRecorder

    checked = []

    class SoundDevice:
        @staticmethod
        def query_devices(*, device=None, **_kwargs):
            return {
                "name": "Microphone Array (Realtek)",
                "hostapi": 0,
                "max_input_channels": 4,
                "default_samplerate": 44100,
            }

        @staticmethod
        def query_hostapis():
            return [{"name": "Windows WASAPI"}]

        @staticmethod
        def check_input_settings(*, samplerate, channels, **_kwargs):
            checked.append((samplerate, channels))
            if samplerate == 16000:
                raise ValueError("unsupported rate")

    recorder = AudioRecorder(AppConfig().audio)
    sample_rate, channels = recorder._supported_capture_format(
        SoundDevice,
        "Microphone Array (Realtek), Windows WASAPI",
    )

    assert (sample_rate, channels) == (44100, 1)
    assert checked == [(16000, 1), (16000, 4), (44100, 1)]


def test_audio_refuses_to_open_when_only_bluetooth_input_exists():
    import sys
    from unittest.mock import patch

    import numpy as np
    import pytest

    from voicepilot.audio import AudioRecorder, MicrophoneUnavailable

    selector = "Headset (AirPods), Windows WASAPI"
    streams = []

    class Stream:
        def __init__(self, callback):
            self.callback = callback
            self.closed = 0

        def start(self):
            self.callback(np.ones((320, 1), dtype="float32"), 320, None, None)

        def stop(self):
            pass

        def close(self):
            self.closed += 1

    class SoundDevice:
        @staticmethod
        def query_hostapis():
            return [{"name": "Windows WASAPI", "default_input_device": 0}]

        @staticmethod
        def query_devices(*, device=None, **_kwargs):
            if device is None and not _kwargs:
                return [{"name": "Headset (AirPods)", "hostapi": 0, "max_input_channels": 1, "default_samplerate": 16000}]
            return {"name": "Headset (AirPods)", "hostapi": 0, "max_input_channels": 1, "default_samplerate": 16000}

        @staticmethod
        def check_input_settings(**_kwargs):
            pass

        @staticmethod
        def InputStream(**kwargs):
            assert kwargs["device"] == selector
            stream = Stream(kwargs["callback"])
            streams.append(stream)
            return stream

    config = AppConfig().audio
    config.input_device = selector
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        with pytest.raises(MicrophoneUnavailable):
            recorder.start()

    assert streams == []


def test_audio_identity_update_persists_without_blocking_capture(tmp_path):
    from voicepilot.config import AppConfig, persist_audio_device_identity, save_config

    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    persist_audio_device_identity(
        path,
        name="USB mic",
        host_api="Windows WASAPI",
        fingerprint="usb mic|windows wasapi|2|48000",
        channels=2,
        sample_rate=48000,
        successful_at=123.0,
    )

    audio = load_config(path).audio
    assert audio.input_device_name == "USB mic"
    assert audio.input_device_host_api == "Windows WASAPI"
    assert audio.input_device_fingerprint == "usb mic|windows wasapi|2|48000"
    assert audio.input_device_channels == 2
    assert audio.input_device_sample_rate == 48000
    assert audio.last_successful_input_at == 123.0


def test_stale_audio_identity_cannot_overwrite_new_settings_choice(tmp_path):
    from voicepilot.config import AppConfig, persist_audio_device_identity, save_config

    path = tmp_path / "config.yaml"
    config = AppConfig()
    config.audio.input_device = "Microphone Array, Windows WASAPI"
    save_config(config, path)

    persist_audio_device_identity(
        path,
        name="Microphone Array",
        host_api="MME",
        fingerprint="microphone array|mme|2|44100",
        channels=2,
        sample_rate=44100,
        successful_at=123.0,
    )

    audio = load_config(path).audio
    assert audio.input_device == "Microphone Array, Windows WASAPI"
    assert audio.input_device_name == ""
    assert audio.input_device_host_api == ""
    assert audio.input_device_fingerprint == ""


def test_audio_recorder_survives_five_hundred_healthy_capture_cycles():
    import sys
    from unittest.mock import patch

    import numpy as np

    from voicepilot.audio import AudioRecorder

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
            return Stream(kwargs["callback"])

    config = AppConfig().audio
    config.min_record_seconds = 0
    with patch.dict(sys.modules, {"sounddevice": SoundDevice}):
        recorder = AudioRecorder(config)
        for _ in range(500):
            metrics = recorder.start()
            assert metrics.first_frame_received
            recorder.stop()
        recorder.close()


def test_qt_hud_queues_messages_without_audio_side_effects():
    from voicepilot.hud_qt import QtStatusHUD

    queued = []

    class Queue:
        def put(self, message):
            queued.append(message)

    hud = QtStatusHUD(AppConfig().hud)
    hud._queue = Queue()
    hud.show("Saved", "", "success")
    hud.show("Saved again", "", "success")

    assert [message.title for message in queued] == ["Saved", "Saved again"]


def test_painted_hud_exposes_equivalent_screen_reader_text():
    from voicepilot.hud_core import HudMessage
    from voicepilot.hud_qt import hud_accessible_text

    assert hud_accessible_text(HudMessage("Nothing heard", "Try again", "warning")) == (
        "Nothing heard",
        "Try again",
    )
    title, detail = hud_accessible_text(HudMessage("Listening", "", "listening"))
    assert title == "Listening"
    assert detail


def test_painted_hud_announces_stage_changes_without_repeating_partial_updates():
    from voicepilot.hud_core import HudMessage
    from voicepilot.hud_qt import hud_accessibility_announcement

    ready = HudMessage("Ready", "Hold the hotkey to speak", "idle")
    listening = HudMessage("Listening", "Notepad", "record")
    first_partial = HudMessage("Live transcript", "Hello", "process")
    next_partial = HudMessage("Live transcript", "Hello world", "process")
    warning = HudMessage("Nothing heard", "No speech was detected", "warning")

    assert hud_accessibility_announcement(ready, listening) == (
        "Listening. Notepad",
        False,
    )
    assert hud_accessibility_announcement(listening, first_partial) == (
        "Transcribing. Hello",
        False,
    )
    assert hud_accessibility_announcement(first_partial, next_partial) is None
    assert hud_accessibility_announcement(next_partial, warning) == (
        "Nothing heard. No speech was detected",
        True,
    )


def test_example_hud_defaults_match_runtime_defaults():
    import yaml

    example = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    defaults = AppConfig().hud
    assert example["hud"]["auto_hide_seconds"] == defaults.auto_hide_seconds


def test_hud_auto_hide_uses_short_success_and_readable_failures():
    from unittest.mock import patch

    from voicepilot.hud_core import hide_deadline

    config = AppConfig().hud
    with patch("voicepilot.hud_core.time.monotonic", return_value=10.0):
        assert hide_deadline("success", config) == 10.35
        assert hide_deadline("warning", config) == 12.5
        assert hide_deadline("error", config) == 14.0
        assert hide_deadline("process", config) == 0.0


def test_example_performance_defaults_match_runtime_defaults():
    import yaml

    example = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    defaults = AppConfig()
    assert example["speech"]["max_cached_models"] == defaults.speech.max_cached_models
    assert example["rewrite"]["ollama_keep_alive"] == defaults.rewrite.ollama_keep_alive
    assert example["rewrite"]["llama_gpu_layers"] == defaults.rewrite.llama_gpu_layers
    assert example["rewrite"]["llama_context_size"] == defaults.rewrite.llama_context_size
    assert example["rewrite"]["llama_idle_seconds"] == defaults.rewrite.llama_idle_seconds
    assert example["paste"]["restore_mode"] == defaults.paste.restore_mode
    assert example["paste"]["restore_delay_ms"] == defaults.paste.restore_delay_ms


def test_undo_targets_latest_session_insertion_and_clears_it():
    from unittest.mock import patch

    from voicepilot.app import LastInsertion
    from voicepilot.app_context import WindowInfo
    from voicepilot.app_lifecycle import ListenerLifecycleMixin

    class Hud:
        def show(self, *_args):
            pass

    class Inserter:
        def __init__(self):
            self.undo_calls = 0

        def undo_last_paste(self):
            self.undo_calls += 1

    class Harness(ListenerLifecycleMixin):
        pass

    context = ForegroundContext(
        process_name="notepad.exe",
        window_title="Notes",
        profile_name="general",
        profile=ProfileStyle(label="General"),
        window_hwnd=123,
    )
    harness = Harness()
    harness.last = LastInsertion(text="hello world", context=context)
    harness.inserter = Inserter()
    harness.hud = Hud()
    with patch(
        "voicepilot.lifecycle_control.get_foreground_window_details",
        return_value=WindowInfo(123, "notepad.exe", "Notes"),
    ):
        harness.undo_last_insertion()
    assert harness.inserter.undo_calls == 1
    assert harness.last.text == ""


def test_paste_strategy_uses_terminal_safe_shortcuts():
    assert _paste_strategy("WindowsTerminal.exe", "") == ("terminal", ("ctrl", "shift", "v"))
    assert _paste_strategy("Code.exe", "Terminal - project") == ("ide-terminal", ("shift", "insert"))
    assert _paste_strategy("notepad.exe", "Notes") == ("standard", ("ctrl", "v"))


def test_incomplete_clipboard_snapshot_returns_recoverable_paste_result():
    from types import SimpleNamespace
    from unittest.mock import patch

    from voicepilot.paste import DeliveryStatus, TextInserter

    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(object(), object())),
        patch("voicepilot.paste.ClipboardSnapshot.capture", return_value=SimpleNamespace(complete=False)),
        patch("voicepilot.paste._type_unicode", return_value=False),
    ):
        result = TextInserter(AppConfig().paste).paste_text("keep this transcript")

    assert result.inserted is False
    assert result.sent is False
    assert result.delivery is DeliveryStatus.BLOCKED
    assert result.copied is False
    assert result.strategy == "blocked"
    assert "preserve the clipboard" in result.reason


def test_paste_delivery_status_never_equates_sent_with_verified():
    from voicepilot.paste import DeliveryStatus, InsertResult

    sent = InsertResult(True, False, "standard")
    copied = InsertResult(False, True, "clipboard", "Target changed")

    assert sent.sent
    assert sent.inserted  # compatibility alias only
    assert sent.delivery is DeliveryStatus.SENT
    assert sent.delivery is not DeliveryStatus.VERIFIED
    assert copied.delivery is DeliveryStatus.COPIED


def test_selection_read_reports_elevated_target_before_touching_clipboard():
    from unittest.mock import patch

    from voicepilot.paste import TextInserter
    from voicepilot.selection import SelectionStatus

    with (
        patch("voicepilot.paste._target_is_elevated", return_value=True),
        patch("voicepilot.paste._clipboard_modules") as clipboard_modules,
    ):
        result = TextInserter(AppConfig().paste).read_selection(window_hwnd=42)

    assert result.status is SelectionStatus.TARGET_ELEVATED
    assert clipboard_modules.call_count == 0


def test_elevated_target_is_copied_without_attempting_input_or_clipboard_restore():
    from unittest.mock import Mock, patch

    from voicepilot.paste import DeliveryStatus, ELEVATED_TARGET_REASON, TextInserter

    for restore_clipboard in (True, False):
        config = AppConfig().paste
        config.restore_clipboard = restore_clipboard
        clipboard = Mock()
        automation = Mock()
        with (
            patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, automation)),
            patch("voicepilot.paste._target_is_elevated", return_value=True),
            patch("voicepilot.paste._target_is_current", return_value=True),
            patch("voicepilot.paste.ClipboardSnapshot.capture") as capture,
        ):
            result = TextInserter(config).paste_text("recoverable transcript", window_hwnd=42)

        assert result.delivery is DeliveryStatus.TARGET_ELEVATED
        assert result.sent is False
        assert result.copied is True
        assert result.reason == ELEVATED_TARGET_REASON
        clipboard.copy.assert_called_once_with("recoverable transcript")
        automation.hotkey.assert_not_called()
        capture.assert_not_called()


def test_insert_below_elevated_target_copies_without_moving_the_selection():
    from unittest.mock import Mock, patch

    from voicepilot.paste import DeliveryStatus, ELEVATED_TARGET_REASON, TextInserter

    clipboard = Mock()
    automation = Mock()
    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, automation)),
        patch("voicepilot.paste._target_is_elevated", return_value=True),
        patch("voicepilot.paste._target_is_current", return_value=True),
    ):
        result = TextInserter(AppConfig().paste).insert_below_selection(
            "rewritten text",
            window_hwnd=42,
        )

    assert result.delivery is DeliveryStatus.TARGET_ELEVATED
    assert result.reason == ELEVATED_TARGET_REASON
    clipboard.copy.assert_called_once_with("rewritten text")
    automation.press.assert_not_called()


def test_elevated_fallback_rechecks_focus_before_copying():
    from unittest.mock import Mock, patch

    from voicepilot.paste import DeliveryStatus, TextInserter

    clipboard = Mock()
    with (
        patch("voicepilot.paste._clipboard_modules", return_value=(clipboard, Mock())),
        patch("voicepilot.paste._target_is_elevated", return_value=True),
        patch("voicepilot.paste._target_is_current", return_value=False),
    ):
        result = TextInserter(AppConfig().paste).paste_text("recoverable transcript", window_hwnd=42)

    assert result.delivery is DeliveryStatus.TARGET_CHANGED
    clipboard.copy.assert_called_once_with("recoverable transcript")


def test_selected_text_compatibility_wrapper_rejects_non_selection_outcomes():
    from unittest.mock import patch

    import pytest

    from voicepilot.paste import SelectionReadError, TextInserter
    from voicepilot.selection import SelectionResult

    inserter = TextInserter(AppConfig().paste)
    with patch.object(inserter, "read_selection", return_value=SelectionResult.target_changed()):
        with pytest.raises(SelectionReadError, match="Target app changed"):
            inserter.get_selected_text()


def test_paste_restore_policy_has_safe_delayed_default():
    from voicepilot.paste import TextInserter

    config = AppConfig().paste
    assert TextInserter(config)._restore_mode() == "delayed"
    config.restore_mode = "immediate"
    assert TextInserter(config)._restore_mode() == "immediate"
    config.restore_mode = "never"
    assert TextInserter(config)._restore_mode() == "never"
    config.restore_clipboard = False
    assert TextInserter(config)._restore_mode() == "never"


def test_windows_elevation_probe_accepts_64_bit_process_handle():
    import ctypes

    if not hasattr(ctypes, "windll"):
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    assert isinstance(_process_is_elevated(kernel32.GetCurrentProcess()), bool)
