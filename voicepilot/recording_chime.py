from __future__ import annotations

import io
import math
import queue
import struct
import sys
import threading
import wave
from collections.abc import Callable


_SAMPLE_RATE = 48_000
# The start cue finishes before capture opens. Its short silent tail gives
# laptop speakers time to settle before the microphone becomes authoritative.
_START_TONES = ((523.25, 0.016), (660.0, 0.020))
_STOP_TONES = ((660.0, 0.026), (523.25, 0.030))
_START_AMPLITUDE = 0.075
_STOP_AMPLITUDE = 0.065
_START_TAIL_SECONDS = 0.006


def _tone_wav(
    tones: tuple[tuple[float, float], ...],
    amplitude: float,
    *,
    tail_seconds: float = 0.0,
) -> bytes:
    """Build one quiet PCM chime without shipping or reading an asset file."""

    frames: list[bytes] = []
    for frequency, duration in tones:
        count = max(1, round(_SAMPLE_RATE * duration))
        for index in range(count):
            envelope = 0.5 - 0.5 * math.cos(2.0 * math.pi * index / max(1, count - 1))
            sample = amplitude * envelope * math.sin(2.0 * math.pi * frequency * index / _SAMPLE_RATE)
            frames.append(struct.pack("<h", round(sample * 32_767)))
    frames.extend(b"\x00\x00" for _ in range(max(0, round(_SAMPLE_RATE * tail_seconds))))

    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(_SAMPLE_RATE)
        stream.writeframes(b"".join(frames))
    return output.getvalue()


def _play_windows_wav(payload: bytes) -> None:
    import winsound

    # Start playback is deliberately synchronous when the HUD is hidden: the
    # sound is the user's readiness signal, so capture must not open early and
    # record it. Stop playback uses the disposable worker below.
    winsound.PlaySound(payload, winsound.SND_MEMORY | winsound.SND_NODEFAULT)


class RecordingChimePlayer:
    """A synchronous start readiness gate plus non-blocking stop feedback."""

    def __init__(
        self,
        enabled: bool = True,
        *,
        playback: Callable[[bytes], None] | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._playback = playback or _play_windows_wav
        self._supported = playback is not None or sys.platform == "win32"
        self._payloads = {
            "start": _tone_wav(
                _START_TONES,
                _START_AMPLITUDE,
                tail_seconds=_START_TAIL_SECONDS,
            ),
            "stop": _tone_wav(_STOP_TONES, _STOP_AMPLITUDE),
        }
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=4)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._started_actions: set[int] = set()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)

    def play_start_before_capture(self, action_id: int = 0) -> bool:
        with self._lock:
            if self._closed or not self._enabled or not self._supported:
                return False
            if action_id and action_id in self._started_actions:
                return False
            if action_id:
                self._started_actions.add(action_id)
            payload = self._payloads["start"]
        try:
            self._playback(payload)
        except (OSError, RuntimeError):
            self.discard_action(action_id)
            return False
        return True

    def discard_action(self, action_id: int) -> None:
        if not action_id:
            return
        with self._lock:
            self._started_actions.discard(action_id)

    def play_stop(self, action_id: int = 0) -> None:
        with self._lock:
            if self._closed or not self._enabled or not self._supported:
                self._started_actions.discard(action_id)
                return
            if action_id and action_id not in self._started_actions:
                return
            if action_id:
                self._started_actions.discard(action_id)
        self._enqueue("stop")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
        if thread is not None:
            thread.join(timeout=0.4)

    def _enqueue(self, kind: str) -> None:
        with self._lock:
            if self._closed or not self._enabled or not self._supported:
                return
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    name="WinsperRecordingChime",
                    daemon=True,
                )
                self._thread.start()
        try:
            self._queue.put_nowait(kind)
        except queue.Full:
            # Feedback is disposable. Never make capture wait for old sounds.
            pass

    def _run(self) -> None:
        while True:
            kind = self._queue.get()
            if kind is None:
                return
            try:
                self._playback(self._payloads[kind])
            except (OSError, RuntimeError):
                # Missing/disabled Windows output must never break recording.
                continue


__all__ = ["RecordingChimePlayer"]
