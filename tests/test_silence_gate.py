from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from voicepilot import transcribe as transcribe_module
from voicepilot.app_context import ForegroundContext
from voicepilot.app_pipeline import DictationPipelineMixin
from voicepilot.audio import AudioClip
from voicepilot.config import AppConfig, ProfileStyle
from voicepilot.transcribe import FasterWhisperTranscriber, clip_has_speech_activity


def test_parakeet_silence_returns_empty_without_loading_asr(monkeypatch):
    config = AppConfig().speech
    config.engine = "sherpa_onnx"
    transcriber = FasterWhisperTranscriber(config, [])
    transcriber.load_model = Mock()
    monkeypatch.setattr(transcribe_module, "clip_has_speech_activity", lambda _clip: False)

    result = transcriber.transcribe(AudioClip(np.zeros(16_000, dtype="float32"), 16_000, 1.0))

    assert result == ""
    transcriber.load_model.assert_not_called()


def test_parakeet_short_real_speech_reaches_asr(monkeypatch):
    captured = {}

    class Recognizer:
        @staticmethod
        def create_stream(*, hotwords=None):
            captured["hotwords"] = hotwords
            return SimpleNamespace(
                accept_waveform=lambda *_args: None,
                result=SimpleNamespace(text="okay"),
            )

        @staticmethod
        def decode_stream(_stream):
            return None

    config = AppConfig().speech
    config.engine = "sherpa_onnx"
    transcriber = FasterWhisperTranscriber(config, [])
    transcriber.load_model = lambda *_args, **_kwargs: Recognizer()
    monkeypatch.setattr(transcribe_module, "clip_has_speech_activity", lambda _clip: True)

    result = transcriber.transcribe(AudioClip(np.ones(1_600, dtype="float32"), 16_000, 0.1))

    assert result == "okay"
    assert captured["hotwords"] is None


def test_parakeet_uses_dictionary_normalization_without_invalid_native_hotwords(monkeypatch):
    captured = {}

    class Recognizer:
        @staticmethod
        def create_stream(*, hotwords=None):
            captured["hotwords"] = hotwords
            return SimpleNamespace(
                accept_waveform=lambda *_args: None,
                result=SimpleNamespace(text="soumya uses json"),
            )

        @staticmethod
        def decode_stream(_stream):
            return None

    config = AppConfig().speech
    config.engine = "sherpa_onnx"
    transcriber = FasterWhisperTranscriber(config, ["Soumya", "JSON"])
    transcriber.load_model = lambda *_args, **_kwargs: Recognizer()
    monkeypatch.setattr(transcribe_module, "clip_has_speech_activity", lambda _clip: True)

    result = transcriber.transcribe(AudioClip(np.ones(1_600, dtype="float32"), 16_000, 0.1))

    assert result == "Soumya uses JSON"
    assert captured["hotwords"] is None


def test_parakeet_instruction_avoids_unsupported_plain_text_hotwords(monkeypatch):
    captured = {}

    class Recognizer:
        @staticmethod
        def create_stream(*, hotwords=None):
            captured["hotwords"] = hotwords
            return SimpleNamespace(
                accept_waveform=lambda *_args: None,
                result=SimpleNamespace(text="bullet points"),
            )

        @staticmethod
        def decode_stream(_stream):
            return None

    config = AppConfig().speech
    config.engine = "sherpa_onnx"
    config.purpose = "polish_instruction"
    transcriber = FasterWhisperTranscriber(config, [])
    transcriber.load_model = lambda *_args, **_kwargs: Recognizer()
    monkeypatch.setattr(transcribe_module, "clip_has_speech_activity", lambda _clip: True)

    result = transcriber.transcribe(AudioClip(np.ones(1_600, dtype="float32"), 16_000, 0.1))

    assert result == "bullet points"
    assert captured["hotwords"] is None


def test_speech_activity_gate_uses_short_utterance_safe_vad(monkeypatch):
    from faster_whisper import vad

    captured = {}

    def speech_timestamps(audio, options, *, sampling_rate):
        captured.update(audio=audio, options=options, sampling_rate=sampling_rate)
        return [{"start": 0, "end": len(audio)}]

    monkeypatch.setattr(vad, "get_speech_timestamps", speech_timestamps)
    clip = AudioClip(np.full(4_800, 0.02, dtype="float32"), 48_000, 0.1)

    assert clip_has_speech_activity(clip)
    assert captured["sampling_rate"] == 16_000
    assert len(captured["audio"]) == 1_600
    assert captured["options"].threshold == 0.5
    assert captured["options"].min_speech_duration_ms == 96


def test_speech_activity_gate_rejects_digital_silence_before_vad(monkeypatch):
    from faster_whisper import vad

    timestamps = Mock(return_value=[])
    monkeypatch.setattr(vad, "get_speech_timestamps", timestamps)

    assert not clip_has_speech_activity(AudioClip(np.zeros(16_000, dtype="float32"), 16_000, 1.0))
    timestamps.assert_not_called()


@pytest.mark.parametrize("polish", [False, True])
def test_silence_never_reaches_polish_insertion_or_history(polish):
    class Harness(DictationPipelineMixin):
        @staticmethod
        def _action_cancelled(_action_id):
            return False

        @staticmethod
        def _advance_action_stage(*_args):
            return None

        def _speech_config_for_mode(self, _mode):
            return self.config.speech

        @staticmethod
        def _model_status_text(_context_label, model):
            return model

        @staticmethod
        def _apply_corrections(text, _context):
            return text

    harness = Harness()
    harness.config = AppConfig()
    harness.hud = Mock()
    harness.transcriber = Mock()
    harness.transcriber.transcribe.return_value = ""
    harness.rewriter = Mock()
    harness.inserter = Mock()
    harness.history = Mock()
    context = ForegroundContext("notepad.exe", "Notes", "general", ProfileStyle(label="General"))

    harness._process_dictation(None, context, polish=polish, action_id=7)

    harness.rewriter.polish.assert_not_called()
    harness.inserter.paste_text.assert_not_called()
    harness.history.append.assert_not_called()
    assert harness.hud.show_action_message.call_args.args == (
        7,
        "Nothing heard",
        "No speech was detected",
        "warning",
    )
