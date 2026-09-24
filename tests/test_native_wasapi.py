from __future__ import annotations

import threading
from pathlib import Path

import pytest

from voicepilot.audio import MicrophoneUnavailable
from voicepilot.config import AudioConfig
from voicepilot.native_wasapi import NativeWasapiRecorder, _safe_native_preference


ROOT = Path(__file__).resolve().parents[1]


def test_native_graph_warmer_is_internal_silent_and_fail_open():
    source = (ROOT / "native" / "winsper_audio" / "winsper_audio.cpp").read_text(
        encoding="utf-8"
    )

    assert "IAudioRenderClient" in source
    assert "EnumAudioEndpoints(eRender" in source
    assert "GetDefaultAudioEndpoint(eRender" not in source
    assert "PKEY_Device_ContainerId" in source
    assert "IsEqualGUID(capture_container, render_container)" in source
    assert "internal_capture_device(device_.Get())" in source
    assert "internal_render_device(candidate.Get())" in source
    warmer = source[source.index("bool initialize_graph_warmer") : source.index("void run()")]
    assert warmer.count("AUDCLNT_BUFFERFLAGS_SILENT") == 2
    assert warmer.count("graph_render_->ReleaseBuffer(") == 2
    assert "initialize_graph_warmer(enumerator.Get());" in source
    assert "if (!initialize_graph_warmer" not in source
    assert "result == WAIT_OBJECT_0 + 4 && !refill_graph_warmer()" in source
    assert "disable_graph_warmer();" in source
    assert "std::vector" not in warmer
    assert "samples_" not in warmer
    assert "bool unsafe_input_name" in source
    assert "bool bluetooth_input_device" in source
    assert "name.empty() || bluetooth_input_device(device.Get())" in source
    assert "No supported Windows microphone" in source
    assert "        if (!refresh_route_if_needed()) return false;" in source.splitlines()
    assert "winsper_audio_create_ex" not in source
    assert "winsper_audio_is_bluetooth_capture" not in source


def test_native_route_notifications_ignore_output_and_bluetooth_endpoints():
    source = (ROOT / "native" / "winsper_audio" / "winsper_audio.cpp").read_text(
        encoding="utf-8"
    )

    assert "is_supported_capture_endpoint(device_id)" in source
    assert "flow != eCapture || bluetooth_input_device(device.Get())" in source
    assert "was_supported_capture_endpoint(device_id)" in source
    assert "OnDeviceStateChanged(LPCWSTR device_id" in source
    assert "OnDeviceAdded(LPCWSTR device_id" in source
    assert "OnDeviceRemoved(LPCWSTR device_id" in source


def test_native_preference_rejects_bluetooth_but_keeps_usb():
    config = AudioConfig()
    config.input_device = "Headset (AirPods Pro), Windows WASAPI"
    assert _safe_native_preference(config) == ""

    config.input_device = "Rode NT-USB+, Windows WASAPI"
    assert _safe_native_preference(config) == "Rode NT-USB+, Windows WASAPI"

    config.input_device_name = "AirPods Pro"
    assert _safe_native_preference(config) == ""


class _FakeNativeLibrary:
    def __init__(self, *, started: bool = True, fallback: bool = False) -> None:
        self.started = started
        self.fallback = fallback

    @staticmethod
    def winsper_audio_device_name(_handle, output, _capacity):
        output.value = "Microphone Array (Realtek(R) Audio)"

    @staticmethod
    def winsper_audio_sample_rate(_handle):
        return 48_000

    @staticmethod
    def winsper_audio_channels(_handle):
        return 4

    def winsper_audio_using_fallback(self, _handle):
        return int(self.fallback)

    def winsper_audio_start(self, _handle):
        return int(self.started)

    @staticmethod
    def winsper_audio_last_error(_handle, output, _capacity):
        output.value = "The selected microphone is muted in Windows. Unmute it and try again."


def _recorder(library: _FakeNativeLibrary, *, preferred: str) -> NativeWasapiRecorder:
    recorder = NativeWasapiRecorder.__new__(NativeWasapiRecorder)
    recorder._library = library
    recorder._handle = 1
    recorder._lock = threading.RLock()
    recorder._closed = False
    recorder._recording = False
    recorder._generation = 0
    recorder._first_frame = threading.Event()
    recorder._first_frame_latency_ms = 0.0
    recorder._start_attempts = 0
    recorder._started_at = 0.0
    recorder._preferred_device = preferred
    recorder._using_fallback_device = False
    recorder._fallback_warning_reported = False
    recorder._warnings = []
    recorder._device_label = "Windows default microphone"
    recorder._sample_rate = 1
    recorder._channels = 1
    return recorder


def test_native_route_state_reports_explicit_fallback_once():
    recorder = _recorder(
        _FakeNativeLibrary(fallback=True),
        preferred="Headset (AirPods), Windows WASAPI",
    )

    recorder._refresh_device_state()
    recorder._report_fallback_once()
    recorder._report_fallback_once()

    assert recorder._device_label == "Microphone Array (Realtek(R) Audio)"
    assert recorder._using_fallback_device
    assert recorder._warnings == [
        'Selected microphone "Headset (AirPods), Windows WASAPI" is not currently '
        'available; using "Microphone Array (Realtek(R) Audio)" until it reconnects.'
    ]


def test_native_route_error_names_unavailable_selection_and_muted_fallback():
    recorder = _recorder(
        _FakeNativeLibrary(started=False, fallback=True),
        preferred="Headset (AirPods), Windows WASAPI",
    )

    with pytest.raises(MicrophoneUnavailable) as raised:
        recorder.start()

    message = str(raised.value)
    assert "Headset (AirPods), Windows WASAPI" in message
    assert "Microphone Array (Realtek(R) Audio)" in message
    assert "not available to Windows" in message
    assert "fallback" in message
