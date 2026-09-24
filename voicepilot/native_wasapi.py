from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from pathlib import Path

from .audio import (
    AudioCaptureDiagnostics,
    AudioClip,
    AudioDeviceIdentity,
    AudioStartMetrics,
    MicrophoneUnavailable,
    RecordingTooShort,
)
from .audio_safety import is_bluetooth_microphone_name, is_muted_microphone_error
from .config import AudioConfig

_ERROR_BUFFER_CHARS = 512
_FIRST_PACKET_STOP_GRACE_SECONDS = 0.50
_WARMUP_PACKET_TIMEOUT_MS = 2000
_WARMUP_TARGET_MS = 40.0
_WARMUP_MAX_ATTEMPTS = 4


def _safe_native_preference(config: AudioConfig) -> str:
    preferred = str(config.input_device_name or config.input_device or "")
    if is_bluetooth_microphone_name(preferred):
        return ""
    return preferred


def native_audio_dll_path() -> Path:
    """Locate the bundled native recorder without probing Windows audio."""

    override = os.environ.get("WINSPER_NATIVE_AUDIO_DLL", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    frozen_root = getattr(sys, "_MEIPASS", "")
    if frozen_root:
        candidates.append(Path(frozen_root) / "voicepilot" / "runtime" / "audio" / "winsper_audio.dll")
    module_root = Path(__file__).resolve().parent
    candidates.extend(
        (
            module_root / "runtime" / "audio" / "winsper_audio.dll",
            module_root.parent / "build" / "native-audio" / "winsper_audio.dll",
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise MicrophoneUnavailable(
        "Winsper's Windows microphone component is missing. Reinstall Winsper and try again."
    )


def _configure_library(library) -> None:
    void_pointer = ctypes.c_void_p
    library.winsper_audio_create.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    library.winsper_audio_create.restype = void_pointer
    library.winsper_audio_destroy.argtypes = [void_pointer]
    library.winsper_audio_destroy.restype = None
    library.winsper_audio_start.argtypes = [void_pointer]
    library.winsper_audio_start.restype = ctypes.c_int
    library.winsper_audio_stop.argtypes = [void_pointer]
    library.winsper_audio_stop.restype = ctypes.c_int
    library.winsper_audio_wait_first_frame.argtypes = [void_pointer, ctypes.c_uint]
    library.winsper_audio_wait_first_frame.restype = ctypes.c_int
    library.winsper_audio_first_frame_ms.argtypes = [void_pointer]
    library.winsper_audio_first_frame_ms.restype = ctypes.c_double
    library.winsper_audio_sample_rate.argtypes = [void_pointer]
    library.winsper_audio_sample_rate.restype = ctypes.c_int
    library.winsper_audio_channels.argtypes = [void_pointer]
    library.winsper_audio_channels.restype = ctypes.c_int
    library.winsper_audio_using_fallback.argtypes = [void_pointer]
    library.winsper_audio_using_fallback.restype = ctypes.c_int
    library.winsper_audio_sample_count.argtypes = [void_pointer]
    library.winsper_audio_sample_count.restype = ctypes.c_size_t
    library.winsper_audio_copy_samples.argtypes = [
        void_pointer,
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_size_t,
    ]
    library.winsper_audio_copy_samples.restype = ctypes.c_size_t
    library.winsper_audio_peak.argtypes = [void_pointer]
    library.winsper_audio_peak.restype = ctypes.c_float
    library.winsper_audio_device_name.argtypes = [void_pointer, ctypes.c_wchar_p, ctypes.c_int]
    library.winsper_audio_device_name.restype = None
    library.winsper_audio_last_error.argtypes = [void_pointer, ctypes.c_wchar_p, ctypes.c_int]
    library.winsper_audio_last_error.restype = None


class NativeWasapiRecorder:
    """Event-driven Windows recorder owned by the isolated audio process."""

    def __init__(self, config: AudioConfig, *, first_frame_signal=None) -> None:
        self.config = config
        self._first_frame = first_frame_signal if first_frame_signal is not None else threading.Event()
        self._lock = threading.RLock()
        self._generation = 0
        self._recording = False
        self._closed = False
        self._started_at = 0.0
        self._first_frame_latency_ms = 0.0
        self._start_attempts = 0
        self._warnings: list[str] = []
        self._last_capture_diagnostics = AudioCaptureDiagnostics()
        self._pending_device_identity: AudioDeviceIdentity | None = None
        self._warmed = False
        self._preferred_device = _safe_native_preference(config)
        self._using_fallback_device = False
        self._fallback_warning_reported = False
        try:
            self._library = ctypes.CDLL(str(native_audio_dll_path()))
            _configure_library(self._library)
        except MicrophoneUnavailable:
            raise
        except (OSError, AttributeError) as exc:
            raise MicrophoneUnavailable(
                "Winsper's Windows microphone component could not start. Reinstall Winsper and try again."
            ) from exc

        error = ctypes.create_unicode_buffer(_ERROR_BUFFER_CHARS)
        self._handle = self._library.winsper_audio_create(
            self._preferred_device,
            error,
            _ERROR_BUFFER_CHARS,
        )
        if not self._handle:
            raise MicrophoneUnavailable(error.value or "No usable Windows microphone is available.")
        self._device_label = "Windows default microphone"
        self._sample_rate = 1
        self._channels = 1
        self._refresh_device_state()
        self._report_fallback_once()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @property
    def first_frame_latency_ms(self) -> float:
        with self._lock:
            return self._first_frame_latency_ms

    @property
    def start_attempts(self) -> int:
        with self._lock:
            return self._start_attempts

    @property
    def last_capture_diagnostics(self) -> AudioCaptureDiagnostics:
        with self._lock:
            return self._last_capture_diagnostics

    @property
    def current_peak_level(self) -> float:
        with self._lock:
            handle = self._handle
        return max(0.0, min(1.0, float(self._library.winsper_audio_peak(handle)))) if handle else 0.0

    def warm_up(self) -> bool:
        with self._lock:
            if self._closed or not self._handle:
                return False
            if self._recording:
                return True
            if self._warmed:
                return True
            handle = self._handle
            # Condition the native shared-mode graph before hotkeys are enabled;
            # real dictation never pays this cost and the microphone remains
            # stopped after conditioning.
            best_latency = float("inf")
            for _attempt in range(_WARMUP_MAX_ATTEMPTS):
                if not self._library.winsper_audio_start(handle):
                    self._warnings.append(self._last_error())
                    return False
                self._refresh_device_state()
                self._report_fallback_once()
                received = bool(
                    self._library.winsper_audio_wait_first_frame(
                        handle,
                        _WARMUP_PACKET_TIMEOUT_MS,
                    )
                )
                latency = (
                    max(0.0, float(self._library.winsper_audio_first_frame_ms(handle)))
                    if received
                    else float("inf")
                )
                if not self._library.winsper_audio_stop(handle):
                    self._warnings.append(self._last_error())
                    return False
                best_latency = min(best_latency, latency)
                if received and latency <= _WARMUP_TARGET_MS:
                    self._warmed = True
                    return True
            if best_latency < float("inf"):
                self._warnings.append(
                    f"Windows microphone startup remained slow after conditioning "
                    f"({best_latency:.0f} ms)."
                )
            else:
                self._warnings.append(
                    "Windows microphone delivered no audio during startup conditioning."
                )
            return False

    def start(self) -> AudioStartMetrics:
        with self._lock:
            if self._closed or not self._handle:
                raise MicrophoneUnavailable("Windows microphone service is closed.")
            if self._recording:
                return AudioStartMetrics(0.0, self._first_frame_latency_ms, 0, self._first_frame.is_set())
            self._generation += 1
            generation = self._generation
            self._first_frame.clear()
            self._first_frame_latency_ms = 0.0
            self._start_attempts = 1
            self._started_at = time.perf_counter()
            started_at = self._started_at
            if not self._library.winsper_audio_start(self._handle):
                error = self._last_error()
                self._refresh_device_state()
                if (
                    self._preferred_device
                    and self._using_fallback_device
                    and is_muted_microphone_error(error)
                ):
                    raise MicrophoneUnavailable(
                        f'The selected microphone "{self._preferred_device}" is not available to '
                        f'Windows, and the fallback "{self._device_label}" is muted. Reconnect the '
                        "selected microphone or unmute the fallback microphone."
                    )
                raise MicrophoneUnavailable(error)
            self._refresh_device_state()
            self._report_fallback_once()
            self._recording = True
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        threading.Thread(
            target=self._publish_first_packet,
            args=(generation,),
            name=f"WinsperNativeFirstAudio-{generation}",
            daemon=True,
        ).start()
        return AudioStartMetrics(
            stream_start_ms=elapsed_ms,
            first_frame_ms=0.0,
            attempts=1,
            first_frame_received=False,
            used_fallback_device=self._using_fallback_device,
            device_label=self._device_label,
        )

    def _publish_first_packet(self, generation: int) -> None:
        while True:
            with self._lock:
                if self._closed or not self._recording or self._generation != generation:
                    return
                handle = self._handle
            if self._library.winsper_audio_wait_first_frame(handle, 50):
                latency = max(0.0, float(self._library.winsper_audio_first_frame_ms(handle)))
                with self._lock:
                    if self._closed or not self._recording or self._generation != generation:
                        return
                    self._first_frame_latency_ms = latency
                    self._first_frame.set()
                return

    def wait_for_first_frame(self, timeout_seconds: float) -> bool:
        return self._first_frame.wait(max(0.0, timeout_seconds))

    def stop(self) -> AudioClip:
        import numpy as np

        stop_started_at = time.perf_counter()
        with self._lock:
            if not self._recording or not self._handle:
                raise RuntimeError("Recorder was not running.")
            handle = self._handle
            started_at = self._started_at
        if not self._first_frame.is_set():
            self._first_frame.wait(_FIRST_PACKET_STOP_GRACE_SECONDS)
        if not self._library.winsper_audio_stop(handle):
            raise MicrophoneUnavailable(self._last_error())
        with self._lock:
            self._recording = False
            self._generation += 1

        elapsed = time.perf_counter() - started_at
        if elapsed < self.config.min_record_seconds:
            raise RecordingTooShort("Hold the hotkey a little longer.")
        count = int(self._library.winsper_audio_sample_count(handle))
        if count <= 0:
            raise MicrophoneUnavailable("Microphone started but delivered no audio. Try again.")
        values = (ctypes.c_float * count)()
        copied = int(self._library.winsper_audio_copy_samples(handle, values, count))
        if copied <= 0:
            raise MicrophoneUnavailable("Microphone started but delivered no audio. Try again.")
        samples = np.ctypeslib.as_array(values)[:copied].copy()
        duration = copied / float(self._sample_rate)
        if duration < self.config.min_record_seconds:
            raise RecordingTooShort("Only silence was captured.")
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        silent_ratio = float(np.mean(np.abs(samples) < 0.003)) if samples.size else 1.0
        with self._lock:
            self._last_capture_diagnostics = AudioCaptureDiagnostics(
                device_label=self._device_label,
                host_api="Windows WASAPI",
                sample_rate=self._sample_rate,
                channels=1,
                clip_duration_seconds=duration,
                peak_level=peak,
                silent_sample_ratio=silent_ratio,
                stop_ms=(time.perf_counter() - stop_started_at) * 1000.0,
            )
            self._pending_device_identity = None
            # "Windows default" must remain dynamic, and an unavailable
            # explicit device must not be silently replaced in saved config by
            # the temporary fallback that happened to capture this clip.
            if self._preferred_device and not self._using_fallback_device:
                self._pending_device_identity = AudioDeviceIdentity(
                    name=self._device_label,
                    host_api="Windows WASAPI",
                    fingerprint=f"{self._device_label.casefold()}|windows-wasapi|1|{self._sample_rate}",
                    channels=1,
                    sample_rate=self._sample_rate,
                    successful_at=time.time(),
                )
        return AudioClip(
            samples=samples,
            sample_rate=self._sample_rate,
            duration_seconds=duration,
            raw_duration_seconds=duration,
        )

    def take_device_identity_update(self) -> AudioDeviceIdentity | None:
        with self._lock:
            value = self._pending_device_identity
            self._pending_device_identity = None
            return value

    def drain_warnings(self) -> tuple[str, ...]:
        with self._lock:
            values = tuple(self._warnings)
            self._warnings.clear()
            return values

    def _refresh_device_state(self) -> None:
        if not self._handle:
            return
        self._device_label = self._read_device_name() or "Windows default microphone"
        self._sample_rate = max(1, int(self._library.winsper_audio_sample_rate(self._handle)))
        self._channels = max(1, int(self._library.winsper_audio_channels(self._handle)))
        self._using_fallback_device = bool(
            self._library.winsper_audio_using_fallback(self._handle)
        )

    def _report_fallback_once(self) -> None:
        if (
            not self._preferred_device
            or not self._using_fallback_device
            or self._fallback_warning_reported
        ):
            return
        self._fallback_warning_reported = True
        self._warnings.append(
            f'Selected microphone "{self._preferred_device}" is not currently available; '
            f'using "{self._device_label}" until it reconnects.'
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            handle = self._handle
            self._handle = None
            self._recording = False
            self._first_frame.clear()
        if handle:
            self._library.winsper_audio_destroy(handle)

    def _read_device_name(self) -> str:
        output = ctypes.create_unicode_buffer(_ERROR_BUFFER_CHARS)
        self._library.winsper_audio_device_name(self._handle, output, _ERROR_BUFFER_CHARS)
        return output.value.strip()

    def _last_error(self) -> str:
        output = ctypes.create_unicode_buffer(_ERROR_BUFFER_CHARS)
        self._library.winsper_audio_last_error(self._handle, output, _ERROR_BUFFER_CHARS)
        return output.value.strip() or "Windows microphone service failed."
