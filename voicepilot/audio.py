from __future__ import annotations

import time
import wave
import weakref
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, RLock

from .audio_safety import is_unsafe_microphone_name
from .audio_devices import (
    host_api_name_from_device,
    named_selector,
    safe_default_input,
    safe_input_candidates,
    same_physical_device_name,
)
from .config import AudioConfig

# The warm stream is opened but inactive. Windows therefore keeps the selected
# endpoint prepared without showing the microphone privacy indicator while idle.
STOP_FIRST_FRAME_GRACE_SECONDS = 0.50


class RecordingTooShort(RuntimeError):
    pass


class MicrophoneUnavailable(RuntimeError):
    """No usable Windows input endpoint could be opened for recording."""


@dataclass(frozen=True)
class AudioStartMetrics:
    stream_start_ms: float
    first_frame_ms: float
    attempts: int
    first_frame_received: bool = False
    used_fallback_device: bool = False
    device_label: str = ""


@dataclass(frozen=True)
class AudioCaptureDiagnostics:
    """Local-only timing and signal facts for the most recent capture."""

    device_label: str = ""
    host_api: str = ""
    sample_rate: int = 0
    channels: int = 0
    clip_duration_seconds: float = 0.0
    peak_level: float = 0.0
    silent_sample_ratio: float = 0.0
    stop_ms: float = 0.0


@dataclass(frozen=True)
class AudioDeviceIdentity:
    name: str
    host_api: str
    fingerprint: str
    channels: int
    sample_rate: int
    successful_at: float


@dataclass
class AudioClip:
    samples: object
    sample_rate: int
    duration_seconds: float
    raw_duration_seconds: float | None = None


class AudioRecorder:
    _host_api_name_from_device = staticmethod(host_api_name_from_device)
    _named_selector = staticmethod(named_selector)
    _safe_default_input = staticmethod(safe_default_input)
    _safe_input_candidates = staticmethod(safe_input_candidates)
    _same_physical_device_name = staticmethod(same_physical_device_name)

    def __init__(
        self,
        config: AudioConfig,
        *,
        first_frame_signal=None,
    ) -> None:
        self.config = config
        self._stream = None
        self._stream_guard = RLock()
        self._stream_generation = 0
        self._capture_sample_rate = config.sample_rate
        self._capture_channels = config.channels
        self._active_input_device: int | str | None = None
        self._active_device_label = "Windows default microphone"
        self._active_host_api = ""
        self._using_fallback_device = False
        self._frames: list[object] = []
        self._lock = Lock()
        # The isolated recorder passes a multiprocessing Event so the app can
        # observe the first real audio packet without delaying the start RPC.
        self._first_frame = first_frame_signal if first_frame_signal is not None else Event()
        self._warnings: list[str] = []
        self._started_at = 0.0
        self._recording = False
        self._first_frame_latency_ms = 0.0
        self._start_attempts = 0
        self._last_capture_diagnostics = AudioCaptureDiagnostics()
        self._pending_device_identity: AudioDeviceIdentity | None = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def warm_up(self) -> bool:
        """Prepare one inactive route without acquiring the microphone."""
        with self._stream_guard:
            try:
                self._ensure_stream()
                return True
            except Exception as primary_error:
                self.close()
                try:
                    self._open_recovery_stream()
                    return True
                except Exception as recovery_error:
                    self.close()
                    self._warnings.append(
                        f"Microphone warm-up unavailable: {self._format_open_error(recovery_error or primary_error)}"
                    )
                    return False

    def start(self) -> AudioStartMetrics:
        with self._stream_guard:
            with self._lock:
                if self._recording:
                    return AudioStartMetrics(0.0, 0.0, 0)
                self._frames = []
                self._warnings = []
                self._first_frame_latency_ms = 0.0
                self._start_attempts = 0
            handshake_started_at = time.perf_counter()
            primary_error: Exception | None = None
            for attempt, recovery in ((1, False), (2, True)):
                attempt_started_at = time.perf_counter()
                recovery_device = self._active_input_device
                if recovery:
                    self.close()
                with self._lock:
                    self._frames = []
                    self._recording = True
                    self._start_attempts = attempt
                self._first_frame.clear()
                self._started_at = time.perf_counter()
                try:
                    if recovery:
                        self._open_recovery_stream(recovery_device)
                    else:
                        self._ensure_stream()
                    self._stream.start()
                    stream_start_ms = (time.perf_counter() - handshake_started_at) * 1000
                    first_frame_state = (
                        f"{self.first_frame_latency_ms:.1f}ms" if self._first_frame.is_set() else "pending"
                    )
                    self._warnings.append(
                        "Audio start "
                        f"attempt={attempt}; device={self._active_device_label}; host={self._active_host_api or 'unknown'}; "
                        f"first_frame={first_frame_state}; "
                        f"attempt_total={(time.perf_counter() - attempt_started_at) * 1000:.1f}ms"
                    )
                    if recovery and self.config.input_device is not None:
                        self._warnings.append(
                            f"Configured microphone unavailable; using {self._active_device_label}."
                        )
                    return AudioStartMetrics(
                        stream_start_ms=stream_start_ms,
                        first_frame_ms=self.first_frame_latency_ms,
                        attempts=attempt,
                        first_frame_received=self._first_frame.is_set(),
                        used_fallback_device=self._using_fallback_device,
                        device_label=self._active_device_label,
                    )
                except Exception as exc:
                    primary_error = primary_error or exc
                    target = self._active_device_label or str(self.config.input_device or "Windows default")
                    self._warnings.append(
                        f"Audio start attempt={attempt} failed; device={target}; "
                        f"host={self._active_host_api or 'unknown'}; error={self._format_open_error(exc)}"
                    )
                    with self._lock:
                        self._recording = False

            self.close()
            raise MicrophoneUnavailable("No usable microphone. Reconnect it or choose Windows default in Settings.") from primary_error

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
        """Return the newest frame peak for opt-in UI meters.

        Production capture pays no extra callback cost: the peak is measured
        only when a caller, such as onboarding, asks for it.
        """
        with self._lock:
            if not self._frames:
                return 0.0
            newest = self._frames[-1]
        try:
            return max(0.0, min(1.0, float(abs(newest).max())))
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def take_device_identity_update(self) -> AudioDeviceIdentity | None:
        """Return one successful identity update for non-hotkey persistence."""
        with self._lock:
            identity = self._pending_device_identity
            self._pending_device_identity = None
            return identity

    def wait_for_first_frame(self, timeout_seconds: float) -> bool:
        """Wait for diagnostics or tests without blocking the hotkey path."""
        return self._first_frame.wait(timeout_seconds)

    def restart_if_silent(self) -> bool:
        """Re-arm one active capture whose stream delivered no packets.

        Some Windows endpoints report a successful ``start()`` yet never invoke
        the callback. Recovery recreates the exact same safe WASAPI endpoint;
        it never switches to Bluetooth, MME, or DirectSound. The lifecycle
        monitor calls this off the hotkey thread after a bounded grace period.
        """
        with self._stream_guard:
            with self._lock:
                if not self._recording or self._first_frame.is_set():
                    return False
                preferred_device = self._active_input_device
                capture_started_at = self._started_at
                next_attempt = self._start_attempts + 1

            self.close()
            with self._lock:
                self._frames = []
                self._recording = True
                self._start_attempts = next_attempt
                self._first_frame_latency_ms = 0.0
                self._started_at = capture_started_at
            self._first_frame.clear()
            try:
                self._open_recovery_stream(preferred_device)
                self._stream.start()
                self._warnings.append(
                    "Audio silent-start rearm "
                    f"attempt={next_attempt}; device={self._active_device_label}; "
                    f"host={self._active_host_api or 'unknown'}"
                )
                return True
            except Exception as exc:
                self._warnings.append(
                    "Audio silent-start rearm failed; "
                    f"device={self._active_device_label}; "
                    f"host={self._active_host_api or 'unknown'}; "
                    f"error={self._format_open_error(exc)}"
                )
                self.close()
                raise MicrophoneUnavailable(
                    "No usable microphone. Reconnect it or choose Windows default in Settings."
                ) from exc

    def _ensure_stream(
        self,
        input_device: int | str | None = None,
        *,
        fallback: bool = False,
    ) -> None:
        if self._stream is not None:
            return
        if input_device is None and not fallback:
            input_device = self.config.input_device
        requested_device = input_device
        recorder_ref = weakref.ref(self)
        stream_generation = self._stream_generation + 1

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info
            recorder = recorder_ref()
            if recorder is None:
                return
            with recorder._lock:
                if recorder._recording and recorder._stream_generation == stream_generation:
                    if status:
                        recorder._warnings.append(str(status))
                    recorder._frames.append(indata.copy())
                    if not recorder._first_frame.is_set():
                        recorder._first_frame_latency_ms = (
                            time.perf_counter() - recorder._started_at
                        ) * 1000
                    recorder._first_frame.set()

        import sounddevice as sd

        requested_device_was_unsafe = (
            requested_device is not None
            and not self._selector_is_safe(sd, requested_device)
        )
        input_device, capture_sample_rate, capture_channels = self._resolve_capture_settings(
            sd,
            input_device,
            honor_persisted=not fallback,
        )
        stream = sd.InputStream(
            samplerate=capture_sample_rate,
            channels=capture_channels,
            dtype="float32",
            device=input_device,
            callback=callback,
        )
        self._stream = stream
        self._stream_generation = stream_generation
        self._capture_sample_rate = capture_sample_rate
        self._capture_channels = capture_channels
        self._active_input_device = input_device
        self._active_device_label = self._device_label(input_device)
        self._active_host_api = self._host_api_name(sd, input_device)
        self._using_fallback_device = fallback or requested_device_was_unsafe

    def _open_recovery_stream(self, preferred_device: int | str | None = None) -> None:
        """Retry the safe WASAPI route with a newly created stream.

        A failed PortAudio stream is discarded. Recovery deliberately does not
        switch host APIs or chase Bluetooth aliases: both caused intermittent
        latency and empty captures while the physical laptop microphone was
        healthy.
        """
        import sounddevice as sd

        candidate = (
            preferred_device
            if preferred_device is not None and self._selector_is_safe(sd, preferred_device)
            else self._safe_default_input(sd)
        )
        if (
            candidate is None
            or not self._selector_is_safe(sd, candidate)
        ) and hasattr(sd, "query_devices"):
            raise RuntimeError("No safe fallback microphone is available.")
        self._ensure_stream(candidate, fallback=True)

    def _resolve_capture_settings(
        self,
        sounddevice,
        configured: int | str | None,
        *,
        honor_persisted: bool = True,
    ) -> tuple[int | str | None, int, int]:
        """Resolve the saved/proven Windows endpoint and its native format.

        Only Windows WASAPI is accepted in production. MME and DirectSound
        aliases are intentionally not recovery routes.
        """
        persisted = self._resolve_persisted_device(sounddevice) if honor_persisted else None
        configured = persisted or self._stable_named_selector(sounddevice, configured)
        if configured is None and not hasattr(sounddevice, "query_devices"):
            # Unit-test backends may implement only InputStream. Production
            # sounddevice always exposes endpoint enumeration, so this branch
            # cannot bypass Windows microphone safety.
            pass
        elif configured is None or not self._selector_is_safe(sounddevice, configured):
            # Pin one explicit, safe input route. Leaving PortAudio on the
            # Windows default lets a Bluetooth output connection silently move
            # capture to a slow/empty hands-free endpoint.
            configured = self._safe_default_input(sounddevice)
            if configured is None or not self._selector_is_safe(sounddevice, configured):
                raise MicrophoneUnavailable(
                    "No safe microphone is available. Bluetooth microphones are disabled on Windows."
                )
        sample_rate, channels = self._supported_capture_format(sounddevice, configured)
        return configured, sample_rate, channels

    def _resolve_persisted_device(self, sounddevice) -> str | None:
        """Resolve saved endpoint metadata to stable name + host selector.

        Indexes frequently change after Bluetooth/USB changes. The last proven
        safe endpoint is reused for both automatic and explicit selection.
        """
        name = self.config.input_device_name.strip()
        fingerprint = self.config.input_device_fingerprint.strip()
        selected_name = ""
        selected_host = ""
        if isinstance(self.config.input_device, str):
            selected_name, separator, selected_host = self.config.input_device.rpartition(", ")
            if separator:
                if name and not self._same_physical_device_name(selected_name, name):
                    return None
                if self.config.input_device_host_api and (
                    selected_host.casefold() != self.config.input_device_host_api.casefold()
                ):
                    return None
            else:
                selected_name = self.config.input_device
                selected_host = ""
        if not name and not fingerprint:
            return None
        try:
            devices = sounddevice.query_devices()
            host_apis = sounddevice.query_hostapis()
        except Exception:
            return None
        for device in devices:
            if int(device.get("max_input_channels") or 0) <= 0:
                continue
            if is_unsafe_microphone_name(str(device.get("name") or "")):
                continue
            host = self._host_api_name_from_device(host_apis, device)
            if host != "Windows WASAPI":
                continue
            device_name = str(device.get("name") or "")
            if selected_host and host.casefold() != selected_host.casefold():
                continue
            if selected_name and not self._same_physical_device_name(selected_name, device_name):
                continue
            candidate = self._device_fingerprint(device, host)
            if fingerprint and candidate == fingerprint:
                return self._named_selector(device, host)
            if name and device_name.casefold() == name.casefold() and (
                not self.config.input_device_host_api or host.casefold() == self.config.input_device_host_api.casefold()
            ):
                return self._named_selector(device, host)
        return None

    @classmethod
    def _stable_named_selector(cls, sounddevice, configured: int | str | None) -> int | str | None:
        """Convert legacy numeric indexes before PortAudio can observe re-enumeration."""
        if not isinstance(configured, int):
            return configured
        try:
            device = sounddevice.query_devices(device=configured, kind="input")
            host = cls._host_api_name_from_device(sounddevice.query_hostapis(), device)
            return cls._named_selector(device, host)
        except Exception:
            return None

    def _host_api_name(self, sounddevice, input_device: int | str | None) -> str:
        try:
            device = sounddevice.query_devices(device=input_device, kind="input")
            return self._host_api_name_from_device(sounddevice.query_hostapis(), device)
        except Exception:
            return ""

    @staticmethod
    def _device_fingerprint(device, host_api: str) -> str:
        name = str(device.get("name") or "").strip().casefold()
        channels = int(device.get("max_input_channels") or 0)
        rate = int(round(float(device.get("default_samplerate") or 0)))
        return f"{name}|{host_api.strip().casefold()}|{channels}|{rate}"

    def _persist_active_device_identity(self) -> None:
        """Persist the endpoint only after it has delivered a usable capture."""
        try:
            import sounddevice as sd

            if not self._selector_is_safe(sd, self._active_input_device):
                return
            device = sd.query_devices(device=self._active_input_device, kind="input")
        except Exception:
            return
        identity = AudioDeviceIdentity(
            name=str(device.get("name") or ""),
            host_api=self._active_host_api,
            channels=int(device.get("max_input_channels") or 0),
            sample_rate=int(round(float(device.get("default_samplerate") or 0))),
            fingerprint=self._device_fingerprint(device, self._active_host_api),
            successful_at=time.time(),
        )
        self.config.input_device_name = identity.name
        self.config.input_device_host_api = identity.host_api
        selector = self._named_selector(device, identity.host_api)
        if selector:
            self.config.input_device = selector
        self.config.input_device_channels = identity.channels
        self.config.input_device_sample_rate = identity.sample_rate
        self.config.input_device_fingerprint = identity.fingerprint
        self.config.last_successful_input_at = identity.successful_at
        with self._lock:
            self._pending_device_identity = identity

    @classmethod
    def _selector_is_safe(cls, sounddevice, selector: int | str | None) -> bool:
        if isinstance(selector, str) and is_unsafe_microphone_name(selector):
            return False
        if isinstance(selector, str) and not selector.casefold().endswith(
            ", windows wasapi"
        ):
            return False
        if not hasattr(sounddevice, "query_devices"):
            # Lightweight test/fake backends have no device catalogue. Real
            # sounddevice always does, so production safety still fails closed.
            return True
        try:
            device = sounddevice.query_devices(device=selector, kind="input")
        except Exception:
            return False
        if is_unsafe_microphone_name(str(device.get("name") or "")):
            return False
        if not hasattr(sounddevice, "query_hostapis"):
            # Lightweight test backends do not model host APIs. Production
            # sounddevice always does and therefore follows the strict branch.
            return True
        host = cls._host_api_name_from_device(sounddevice.query_hostapis(), device)
        return host == "Windows WASAPI"

    @staticmethod
    def _device_label(input_device: int | str | None) -> str:
        return "Windows default microphone" if input_device is None else str(input_device)

    @staticmethod
    def _format_open_error(error: Exception | None) -> str:
        return str(error).strip() if error is not None else "unknown audio error"

    def _supported_capture_format(
        self,
        sounddevice,
        input_device: int | str | None,
    ) -> tuple[int, int]:
        rates = [self.config.sample_rate]
        channels = [self.config.channels]
        try:
            device = sounddevice.query_devices(device=input_device, kind="input")
            native_rate = int(round(float(device.get("default_samplerate") or 0)))
            if native_rate > 0 and native_rate not in rates:
                rates.append(native_rate)
            native_channels = int(device.get("max_input_channels") or 0)
            if native_channels > 0 and native_channels not in channels:
                channels.append(native_channels)
        except Exception:
            pass
        check_input_settings = getattr(sounddevice, "check_input_settings", None)
        if not callable(check_input_settings):
            return rates[0], channels[0]
        last_error: Exception | None = None
        for sample_rate in rates:
            for channel_count in channels:
                try:
                    check_input_settings(
                        device=input_device,
                        channels=channel_count,
                        dtype="float32",
                        samplerate=sample_rate,
                    )
                    return sample_rate, channel_count
                except Exception as exc:
                    last_error = exc
        if last_error is not None:
            raise last_error
        return self.config.sample_rate, self.config.channels

    def stop(self) -> AudioClip:
        import numpy as np

        stop_started_at = time.perf_counter()
        with self._stream_guard:
            if not self._recording:
                raise RuntimeError("Recorder was not running.")

            stream = self._stream
            if stream is not None:
                try:
                    # Slow Windows endpoints can batch their first buffer. Wait
                    # only at release, and only when nothing arrived yet, so a
                    # short utterance is not discarded. Hotkey start stays instant.
                    if not self._first_frame.is_set():
                        self._first_frame.wait(STOP_FIRST_FRAME_GRACE_SECONDS)
                    stream.stop()
                except Exception:
                    self.close()
                    raise
            with self._lock:
                self._recording = False

            elapsed = time.perf_counter() - self._started_at
            if elapsed < self.config.min_record_seconds:
                raise RecordingTooShort("Hold the hotkey a little longer.")

            with self._lock:
                frames = list(self._frames)
                self._frames = []
            capture_sample_rate = self._capture_sample_rate

            if not frames:
                self.close()
                raise MicrophoneUnavailable("Microphone started but delivered no audio. Try again.")

            samples = np.concatenate(frames, axis=0)
            if samples.ndim > 1:
                samples = samples[:, 0]
            raw_duration = len(samples) / float(capture_sample_rate)

            duration = len(samples) / float(capture_sample_rate)
            if duration < self.config.min_record_seconds:
                raise RecordingTooShort("Only silence was captured.")

            clip = AudioClip(
                samples=samples,
                sample_rate=capture_sample_rate,
                duration_seconds=duration,
                raw_duration_seconds=raw_duration,
            )
            peak_level = float(np.max(np.abs(samples))) if samples.size else 0.0
            silent_sample_ratio = float(np.mean(np.abs(samples) < 0.003)) if samples.size else 1.0
            with self._lock:
                self._last_capture_diagnostics = AudioCaptureDiagnostics(
                    device_label=self._active_device_label,
                    host_api=self._active_host_api,
                    sample_rate=capture_sample_rate,
                    channels=self._capture_channels,
                    clip_duration_seconds=duration,
                    peak_level=peak_level,
                    silent_sample_ratio=silent_sample_ratio,
                    stop_ms=(time.perf_counter() - stop_started_at) * 1000,
                )
            self._persist_active_device_identity()
            return clip

    def drain_warnings(self) -> tuple[str, ...]:
        with self._lock:
            warnings = tuple(self._warnings)
            self._warnings = []
        return warnings

    def close(self) -> None:
        with self._stream_guard:
            with self._lock:
                stream = self._stream
                was_recording = self._recording
                self._stream = None
                self._stream_generation += 1
                self._capture_sample_rate = self.config.sample_rate
                self._capture_channels = self.config.channels
                self._recording = False
                self._frames = []
                self._first_frame.clear()
            if stream is None:
                return
            if was_recording:
                try:
                    stream.stop()
                except Exception:
                    pass
            try:
                stream.close()
            except Exception:
                pass


def write_wav(clip: AudioClip, path: Path) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(clip.samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(clip.sample_rate)
        wav.writeframes(pcm.tobytes())


def read_wav(path: Path) -> AudioClip:
    import numpy as np

    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise RuntimeError(f"Only 16-bit PCM WAV files are supported: {path}")

    samples = np.frombuffer(frames, dtype="<i2").astype("float32") / 32767.0
    if channels > 1:
        samples = samples.reshape(-1, channels)[:, 0]
    duration = len(samples) / float(sample_rate)
    return AudioClip(samples=samples, sample_rate=sample_rate, duration_seconds=duration, raw_duration_seconds=duration)
