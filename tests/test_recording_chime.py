import io
import time
import wave
from unittest.mock import Mock, patch

import numpy as np

from voicepilot.config import AppConfig
from voicepilot.lifecycle_control import LifecycleControlMixin
from voicepilot.recording_chime import _START_TONES, RecordingChimePlayer


def _wait_until(predicate, timeout: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_start_chime_is_a_short_synchronous_readiness_gate():
    payloads = []

    def playback(payload: bytes) -> None:
        payloads.append(payload)
        time.sleep(0.01)

    player = RecordingChimePlayer(playback=playback)
    started = time.perf_counter()
    assert player.play_start_before_capture(4)
    elapsed = time.perf_counter() - started

    assert elapsed >= 0.01
    assert elapsed < 0.05
    assert payloads[0][:4] == b"RIFF"
    assert payloads[0][8:12] == b"WAVE"
    with wave.open(io.BytesIO(payloads[0]), "rb") as chime:
        sample_rate = chime.getframerate()
        duration = chime.getnframes() / sample_rate
        samples = np.frombuffer(chime.readframes(chime.getnframes()), dtype="<i2").astype("float32") / 32_768
        peak = float(np.max(np.abs(samples)))
    assert sample_rate == 48_000
    assert 0.04 <= duration <= 0.045
    assert 0.07 <= peak <= 0.076
    assert all(400 < frequency < 1_000 for frequency, _duration in _START_TONES)
    player.close()


def test_recording_chimes_are_action_deduplicated_and_disable_cleanly():
    payloads = []
    player = RecordingChimePlayer(playback=payloads.append)

    assert player.play_start_before_capture(8)
    assert not player.play_start_before_capture(8)
    player.play_stop(8)
    player.play_stop(8)
    assert _wait_until(lambda: len(payloads) == 2)
    assert payloads[0] != payloads[1]

    player.set_enabled(False)
    assert not player.play_start_before_capture(9)
    player.play_stop(9)
    time.sleep(0.03)
    player.close()
    assert len(payloads) == 2


def test_failed_or_aborted_start_does_not_leave_stop_chime_armed():
    failed_attempts = []

    def fail_playback(payload: bytes) -> None:
        failed_attempts.append(payload)
        raise OSError("output unavailable")

    failed = RecordingChimePlayer(playback=fail_playback)
    assert not failed.play_start_before_capture(12)
    failed.play_stop(12)
    time.sleep(0.03)
    failed.close()
    assert len(failed_attempts) == 1

    payloads = []
    aborted = RecordingChimePlayer(playback=payloads.append)
    assert aborted.play_start_before_capture(13)
    aborted.discard_action(13)
    aborted.play_stop(13)
    time.sleep(0.03)
    aborted.close()
    assert len(payloads) == 1


def test_hud_position_change_restarts_only_the_hud_process():
    old = AppConfig()
    new = AppConfig()
    new.hud.position = "right"
    previous = Mock()
    replacement = Mock()
    harness = LifecycleControlMixin()
    harness.hud = previous

    with patch("voicepilot.lifecycle_control.create_status_hud", return_value=replacement) as factory:
        harness._reload_hud(old, new)

    previous.stop.assert_called_once_with()
    factory.assert_called_once_with(new.hud)
    replacement.start.assert_called_once_with()
    assert harness.hud is replacement


def test_chime_preference_change_does_not_restart_the_hud_process():
    old = AppConfig()
    new = AppConfig()
    new.hud.recording_chimes = not old.hud.recording_chimes
    harness = LifecycleControlMixin()
    harness.hud = Mock()

    harness._reload_hud(old, new)

    harness.hud.stop.assert_not_called()
