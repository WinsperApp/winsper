from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from voicepilot.action_state import ActionCoordinator
from voicepilot.app import WinsperApp
from voicepilot.app_lifecycle import ListenerLifecycleMixin
from voicepilot.app_speech_backend import SpeechBackendLifecycleMixin
from voicepilot.config import AppConfig, RewriteConfig, load_config, save_config
from voicepilot.llama_server import (
    LlamaServerModelMissing,
    LlamaServerStartupCancelled,
    ManagedLlamaServer,
)
from voicepilot.polish_service import TextRewriter
from voicepilot.transcribe import FasterWhisperTranscriber


class _PreloadHarness(SpeechBackendLifecycleMixin):
    pass


def test_background_preloads_primary_dictation_then_embedded_polish():
    harness = _PreloadHarness()
    harness.config = AppConfig()
    harness.config.speech.preload_on_startup = True
    harness.config.dictation.ramble_model = "small.en"
    harness.config.dictation.rewrite_instruction_model = "base.en"
    harness.config.dictation.polish_model = "tiny.en"
    harness._stop_event = threading.Event()
    harness._preload_thread = None
    harness._preload_transcriber = None
    harness._preload_runtime_key = None
    harness._lock = threading.Lock()
    harness.config_path = Path("config.yaml")
    harness.hud = Mock()
    speech_started = threading.Event()
    release_speech = threading.Event()
    transcriber = Mock()
    transcriber.mode_config.side_effect = lambda model: replace(harness.config.speech, model=model)

    def preload_model(*_args, **_kwargs):
        speech_started.set()
        assert release_speech.wait(1)
        return True

    transcriber.preload_model.side_effect = preload_model
    harness.transcriber = transcriber
    harness._queue_or_start_rewrite_preload = Mock()

    harness._start_background_preloads()
    assert speech_started.wait(1)
    harness._queue_or_start_rewrite_preload.assert_not_called()
    release_speech.set()
    harness._preload_thread.join(timeout=1)

    assert not harness._preload_thread.is_alive()
    transcriber.preload_model.assert_called_once()
    speech_config = transcriber.preload_model.call_args.args[0]
    assert speech_config.model == "small.en"
    harness.hud.show.assert_called_once_with(
        "Ready",
        "Hold the hotkey to speak",
        "idle",
    )
    harness._queue_or_start_rewrite_preload.assert_called_once()


def test_completed_preload_does_not_overwrite_active_action_hud():
    harness = _PreloadHarness()
    harness.config = AppConfig()
    harness._stop_event = threading.Event()
    harness._lock = threading.Lock()
    harness.transcriber = Mock()
    harness._coordinator = Mock()
    harness._coordinator.is_busy.return_value = True
    harness.hud = Mock()
    harness._preload_models = Mock(return_value=True)
    harness._queue_or_start_rewrite_preload = Mock()

    harness._run_preload_sequence(harness.transcriber, harness.config.speech)

    harness.hud.show.assert_not_called()
    harness._queue_or_start_rewrite_preload.assert_called_once()


def test_all_voice_modes_share_one_model_with_instruction_specific_decoding():
    harness = _PreloadHarness()
    harness.config = AppConfig()
    harness.config.dictation.ramble_model = "parakeet-tdt-0.6b-v2-int8"
    harness.config.dictation.polish_model = "small.en"
    harness.config.dictation.rewrite_instruction_model = "base.en"
    transcriber = Mock()
    transcriber.mode_config.side_effect = lambda model: replace(harness.config.speech, model=model)
    harness.transcriber = transcriber

    dictate = harness._speech_config_for_mode("dictate")
    polish = harness._speech_config_for_mode("polish")
    instruction = harness._speech_config_for_mode("rewrite")

    assert {dictate.model, polish.model, instruction.model} == {"parakeet-tdt-0.6b-v2-int8"}
    assert dictate.purpose == "dictation"
    assert polish.purpose == "dictation"
    assert instruction.purpose == "polish_instruction"


def test_faster_whisper_warm_up_primes_production_paths_privately():
    import numpy as np

    calls = []

    class Model:
        def transcribe(self, audio, **kwargs):
            calls.append((audio, kwargs))
            return iter([SimpleNamespace(text="discard me")]), None

    transcriber = FasterWhisperTranscriber(AppConfig().speech, ["Winsper"])
    transcriber.load_model = Mock(return_value=Model())

    assert transcriber.warm_up()
    assert len(calls) == 2
    for audio, options in calls:
        assert audio.dtype == np.float32
        assert audio.size == 16_000
        assert not np.any(audio)
        assert options["beam_size"] == 1
        assert options["max_new_tokens"] == 1
        assert "Winsper" in options["initial_prompt"]
        assert options["hotwords"] is None
    assert calls[0][1]["vad_filter"] is True
    assert calls[0][1]["vad_parameters"]["speech_pad_ms"] == 200
    assert calls[1][1]["vad_filter"] is False
    assert calls[1][1]["vad_parameters"] is None


def test_parakeet_warm_up_runs_private_decode():
    config = AppConfig().speech
    config.engine = "sherpa_onnx"
    stream = Mock()
    stream.result.text = "discard me"
    recognizer = Mock()
    recognizer.create_stream.return_value = stream
    transcriber = FasterWhisperTranscriber(config, ["Winsper"])
    transcriber.load_model = Mock(return_value=recognizer)

    assert transcriber.warm_up()
    stream.accept_waveform.assert_called_once()
    sample_rate, samples = stream.accept_waveform.call_args.args
    assert sample_rate == 16_000
    assert len(samples) == 23_680
    recognizer.decode_stream.assert_called_once_with(stream)


def test_warm_up_uses_existing_cuda_to_cpu_recovery():
    config = AppConfig().speech
    config.device = "cuda"
    config.compute_type = "float16"
    attempted_devices = []
    fallback = Mock()

    class Model:
        def transcribe(self, _audio, **_kwargs):
            if attempted_devices[-1] == "cuda":
                raise RuntimeError("cuBLAS initialization failed")
            return iter(()), None

    transcriber = FasterWhisperTranscriber(config, [], on_device_fallback=fallback)

    def load_model(speech_config, **_kwargs):
        attempted_devices.append(speech_config.device)
        return Model()

    transcriber.load_model = load_model

    assert transcriber.warm_up()
    assert attempted_devices == ["cuda", "cpu"]
    requested, recovered = fallback.call_args.args
    assert requested.device == "cuda"
    assert recovered.device == "cpu"
    assert recovered.compute_type == "int8"


def test_optional_speech_preload_failure_recovers_startup_ready_state():
    harness = _PreloadHarness()
    harness.config = AppConfig()
    harness._stop_event = threading.Event()
    harness._lock = threading.Lock()
    harness.config_path = Path("config.yaml")
    harness.hud = Mock()
    transcriber = Mock()
    transcriber.mode_config.side_effect = lambda _model: harness.config.speech
    transcriber.preload_model.side_effect = RuntimeError("model warm-up failed")
    harness.transcriber = transcriber

    harness._coordinator = Mock()
    harness._coordinator.is_busy.return_value = False
    harness._queue_or_start_rewrite_preload = Mock()

    harness._run_preload_sequence(transcriber, harness.config.speech)

    harness.hud.show.assert_called_once_with(
        "Ready",
        "Hold the hotkey to speak",
        "idle",
    )
    harness._queue_or_start_rewrite_preload.assert_not_called()


def test_request_only_speech_reload_preserves_warm_worker(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = AppConfig()
    config.hud.enabled = False
    config.tray.enabled = False
    config.speech.preload_on_startup = False
    save_config(config, config_path)
    app = WinsperApp(config, config_path)
    original = app.transcriber

    changed = load_config(config_path)
    changed.speech.beam_size = 2
    changed.speech.vad_filter = not changed.speech.vad_filter
    save_config(changed, config_path)

    assert app.reload_config(silent=True)
    assert app.transcriber is original
    assert original.config.beam_size == 2
    assert original.config.vad_filter == changed.speech.vad_filter
    app._action_worker.stop()


def test_multilingual_language_reload_preserves_compatible_runtime(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = AppConfig()
    config.hud.enabled = False
    config.tray.enabled = False
    config.speech.preload_on_startup = False
    config.speech.model = "small"
    config.speech.language = "fr"
    config.dictation.ramble_model = "small"
    config.dictation.polish_model = "small"
    config.dictation.rewrite_instruction_model = "small"
    save_config(config, config_path)
    app = WinsperApp(config, config_path)
    original = app.transcriber

    changed = load_config(config_path)
    changed.speech.language = "es"
    save_config(changed, config_path)

    assert app.reload_config(silent=True)
    assert app.transcriber is original
    assert original.config.language == "es"
    app._action_worker.stop()


def test_optional_speech_model_reload_preserves_warm_dictation_worker(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = AppConfig()
    config.hud.enabled = False
    config.tray.enabled = False
    config.speech.preload_on_startup = False
    config.dictation.ramble_model = "small.en"
    config.dictation.polish_model = "small.en"
    config.dictation.rewrite_instruction_model = "small.en"
    save_config(config, config_path)
    app = WinsperApp(config, config_path)
    original = app.transcriber

    changed = load_config(config_path)
    changed.dictation.polish_model = "base.en"
    changed.dictation.rewrite_instruction_model = "tiny.en"
    save_config(changed, config_path)

    assert app.reload_config(silent=True)
    assert app.transcriber is original
    app._action_worker.stop()


def test_runtime_replacement_serializes_polish_cancel_and_speech_preload(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = AppConfig()
    config.hud.enabled = False
    config.tray.enabled = False
    config.speech.preload_on_startup = True
    save_config(config, config_path)
    app = WinsperApp(config, config_path)

    old_polish_started = threading.Event()
    release_old_polish = threading.Event()
    speech_preload_started = threading.Event()
    release_speech_preload = threading.Event()
    polish_preload_started = threading.Event()

    def old_polish_warmup() -> None:
        old_polish_started.set()
        assert release_old_polish.wait(2)

    old_polish_thread = threading.Thread(target=old_polish_warmup, daemon=True)
    app._rewrite_preload_thread = old_polish_thread
    old_polish_thread.start()
    assert old_polish_started.wait(1)

    replacement = Mock()
    app._create_transcriber = Mock(return_value=replacement)

    def start_speech_preload() -> bool:
        def speech_preload() -> None:
            speech_preload_started.set()
            assert release_speech_preload.wait(2)

        app._preload_thread = threading.Thread(target=speech_preload, daemon=True)
        app._preload_thread.start()
        return True

    app._start_preload_if_enabled = Mock(side_effect=start_speech_preload)
    app._start_rewrite_preload_if_enabled = Mock(
        side_effect=polish_preload_started.set
    )
    app._rewrite_preload_deferred = True

    app._replace_transcriber(config)
    replacement_thread = app._speech_replacement_thread
    assert replacement_thread is not None
    app._start_deferred_rewrite_preload()

    assert not speech_preload_started.wait(0.1)
    assert not polish_preload_started.is_set()

    release_old_polish.set()
    assert speech_preload_started.wait(1)
    app._start_deferred_rewrite_preload()
    assert not polish_preload_started.is_set()

    release_speech_preload.set()
    app._preload_thread.join(timeout=1)
    assert not app._preload_thread.is_alive()
    replacement_thread.join(timeout=1)
    assert not replacement_thread.is_alive()
    app._start_deferred_rewrite_preload()
    assert polish_preload_started.wait(1)

    app._action_worker.stop()


def test_rapid_runtime_replacements_retire_in_order_and_only_preload_latest(tmp_path):
    harness = _PreloadHarness()
    harness._lock = threading.Lock()
    harness._stop_event = threading.Event()
    harness.config_path = tmp_path / "config.yaml"
    harness._rewrite_preload_thread = None
    harness._speech_replacement_thread = None

    first_retirement_started = threading.Event()
    allow_first_retirement = threading.Event()
    second_retirement_started = threading.Event()
    original = Mock()
    first_replacement = Mock()
    latest_replacement = Mock()

    def retire_original() -> None:
        first_retirement_started.set()
        assert allow_first_retirement.wait(2)

    original.cancel.side_effect = retire_original
    first_replacement.cancel.side_effect = second_retirement_started.set
    harness.transcriber = original
    harness._create_transcriber = Mock(
        side_effect=[first_replacement, latest_replacement]
    )
    harness._start_preload_if_enabled = Mock(return_value=True)

    harness._replace_transcriber(AppConfig())
    first_thread = harness._speech_replacement_thread
    assert first_thread is not None
    assert first_retirement_started.wait(1)

    harness._replace_transcriber(AppConfig())
    latest_thread = harness._speech_replacement_thread
    assert latest_thread is not None and latest_thread is not first_thread
    assert harness.transcriber is latest_replacement
    assert not second_retirement_started.wait(0.1)

    allow_first_retirement.set()
    latest_thread.join(timeout=2)

    assert not latest_thread.is_alive()
    assert second_retirement_started.is_set()
    harness._start_preload_if_enabled.assert_called_once()
    assert harness._speech_replacement_thread is None


def test_hotkey_waits_while_speech_runtime_is_being_replaced():
    class Harness(ListenerLifecycleMixin):
        pass

    release_replacement = threading.Event()
    replacement_thread = threading.Thread(
        target=release_replacement.wait,
        daemon=True,
    )
    replacement_thread.start()
    harness = Harness()
    harness._speech_replacement_thread = replacement_thread
    harness.hud = Mock()

    harness._on_hotkey_start("dictate")

    harness.hud.show.assert_called_once_with(
        "Applying speech settings",
        "Ready in a moment",
        "process",
    )
    release_replacement.set()
    replacement_thread.join(timeout=1)


def test_enabling_polish_queues_embedded_warmup_without_replacing_speech_worker(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = AppConfig()
    config.hud.enabled = False
    config.tray.enabled = False
    config.speech.preload_on_startup = False
    config.dictation.polish_enabled = False
    save_config(config, config_path)
    app = WinsperApp(config, config_path)
    original = app.transcriber
    app._queue_or_start_rewrite_preload = Mock()
    # Enabling Polish also reloads the global shortcut. Keep this lifecycle
    # unit test independent from a developer's already-running Winsper copy.
    app._reload_hotkeys = Mock()

    changed = load_config(config_path)
    changed.dictation.polish_enabled = True
    save_config(changed, config_path)

    assert app.reload_config(silent=True)
    assert app.transcriber is original
    app._queue_or_start_rewrite_preload.assert_called_once()
    app._action_worker.stop()


def test_idle_poll_retries_deferred_embedded_polish_warmup(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = AppConfig()
    config.hud.enabled = False
    config.tray.enabled = False
    save_config(config, config_path)
    app = WinsperApp(config, config_path)
    app._rewrite_preload_deferred = True
    app._start_rewrite_preload_if_enabled = Mock()

    app._poll_control_command()

    assert app._rewrite_preload_deferred is False
    app._start_rewrite_preload_if_enabled.assert_called_once()
    app._action_worker.stop()


def test_embedded_polish_warmup_yields_when_cancelled():
    started = threading.Event()

    class Backend:
        def complete(self, _prompt, *, num_predict):
            return str(num_predict)

        def warm_up(self, cancel_event=None):
            started.set()
            assert cancel_event is not None
            assert cancel_event.wait(1)
            return False

        def close(self):
            return

    rewriter = TextRewriter(RewriteConfig(), [], backend=Backend())
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(rewriter.warm_up()), daemon=True)
    thread.start()
    assert started.wait(1)

    rewriter.cancel_warm_up()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert outcomes == [False]


def test_polish_preload_can_be_cancelled_before_thread_starts():
    harness = _PreloadHarness()
    harness._lock = threading.Lock()
    harness._stop_event = threading.Event()
    harness._rewrite_preload_deferred = False
    harness._rewrite_preload_thread = threading.Thread(target=lambda: None)
    harness._rewrite_preload_cancel_event = threading.Event()
    harness._rewrite_preload_rewriter = Mock()

    harness._cancel_rewrite_preload(defer=True)

    assert harness._rewrite_preload_cancel_event.is_set()
    harness._rewrite_preload_rewriter.cancel_warm_up.assert_called_once()
    assert harness._rewrite_preload_deferred is True


def test_concurrent_polish_preload_starters_register_only_one_worker(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = AppConfig()
    config.hud.enabled = False
    config.tray.enabled = False
    config.speech.preload_on_startup = False
    config.rewrite.provider = "embedded"
    save_config(config, config_path)
    app = WinsperApp(config, config_path)
    app.rewriter.close()
    started = threading.Event()
    release = threading.Event()
    rewriter = Mock()

    def warm_up(*, cancel_event=None):
        assert cancel_event is not None
        started.set()
        assert release.wait(1)
        return True

    rewriter.warm_up.side_effect = warm_up
    app.rewriter = rewriter
    callers_ready = threading.Barrier(2)

    def allow_preload(*_args, **_kwargs):
        callers_ready.wait(timeout=1)
        return True

    with (
        patch("voicepilot.app.available_ram_gb", return_value=16.0),
        patch("voicepilot.app.resolve_llama_model_path", return_value=tmp_path / "model.gguf"),
        patch("voicepilot.app.should_preload_polish_model", side_effect=allow_preload),
    ):
        callers = [
            threading.Thread(target=app._start_rewrite_preload_if_enabled)
            for _ in range(2)
        ]
        for caller in callers:
            caller.start()
        for caller in callers:
            caller.join(timeout=1)

    assert all(not caller.is_alive() for caller in callers)
    assert started.wait(1)
    assert rewriter.warm_up.call_count == 1
    release.set()
    app._rewrite_preload_thread.join(timeout=1)
    assert not app._rewrite_preload_thread.is_alive()
    app._action_worker.stop()


def test_missing_embedded_model_does_not_start_background_preload(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = AppConfig()
    config.hud.enabled = False
    config.tray.enabled = False
    config.speech.preload_on_startup = False
    config.rewrite.provider = "embedded"
    save_config(config, config_path)
    app = WinsperApp(config, config_path)
    app.rewriter.close()
    rewriter = Mock()
    app.rewriter = rewriter

    with patch(
        "voicepilot.app.resolve_llama_model_path",
        side_effect=LlamaServerModelMissing("model is not installed"),
    ):
        app._start_rewrite_preload_if_enabled()

    rewriter.warm_up.assert_not_called()
    assert app._rewrite_preload_thread is None
    app._action_worker.stop()


def test_closed_rewriter_cannot_restart_embedded_backend():
    backend = Mock()
    backend.warm_up.return_value = True
    rewriter = TextRewriter(RewriteConfig(), [], backend=backend)

    rewriter.close()

    assert rewriter.warm_up(threading.Event()) is False
    backend.warm_up.assert_not_called()


def test_llama_startup_wait_stops_immediately_when_warmup_is_cancelled():
    runtime = object.__new__(ManagedLlamaServer)
    runtime.config = RewriteConfig()
    runtime._process = Mock()
    runtime._process.poll.return_value = None
    runtime._stop_process = Mock()
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(LlamaServerStartupCancelled):
        runtime._wait_until_ready(cancel_event)

    runtime._stop_process.assert_called_once()


def test_foreground_hotkey_cancels_optional_polish_warmup():
    class Harness(ListenerLifecycleMixin):
        pass

    harness = Harness()
    harness._lock = threading.Lock()
    harness._coordinator = ActionCoordinator()
    harness._is_toggle = False
    harness._action_context = None
    harness._active_started_at = 0.0
    harness.config = AppConfig()
    harness.hud = Mock()
    harness.recorder = Mock()
    harness.recorder.start.return_value = SimpleNamespace(
        stream_start_ms=10.0,
        first_frame_ms=12.0,
        attempts=1,
        used_fallback_device=False,
    )
    harness._log_audio_warnings = Mock()
    harness._show_listening_hud = Mock()
    harness._start_context_refresh = Mock()
    harness._cancel_rewrite_preload = Mock()

    with patch(
        "voicepilot.lifecycle_capture.get_foreground_window_details",
        return_value=SimpleNamespace(hwnd=1, process_name="notepad.exe", title="Notes"),
    ):
        harness._on_hotkey_start("dictate")

    harness._cancel_rewrite_preload.assert_called_once_with(defer=True)
