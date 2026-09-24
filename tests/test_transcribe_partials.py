from types import SimpleNamespace

import numpy as np

from voicepilot import transcribe as transcribe_module
from voicepilot.audio import AudioClip
from voicepilot.config import AppConfig
from voicepilot.transcribe import FasterWhisperTranscriber


def test_rapid_partials_are_coalesced_and_end_with_exact_final_text():
    segment_texts = [f"word{index}" for index in range(120)]

    class Model:
        @staticmethod
        def transcribe(_audio, **_kwargs):
            return iter(SimpleNamespace(text=f" {text}") for text in segment_texts), None

    transcriber = FasterWhisperTranscriber(AppConfig().speech, [])
    transcriber.load_model = lambda *_args, **_kwargs: Model()
    clip = AudioClip(np.zeros(16000, dtype="float32"), 16000, 1.0)
    partials = []

    result = transcriber.transcribe(clip, on_partial=partials.append)

    assert result == " ".join(segment_texts)
    assert partials[0] == "word0"
    assert partials[-1] == result
    assert len(partials) < len(segment_texts) // 2


def test_no_partial_callback_normalizes_only_final_text(monkeypatch):
    class Model:
        @staticmethod
        def transcribe(_audio, **_kwargs):
            return iter(SimpleNamespace(text=f" part{index}") for index in range(40)), None

    normalize_calls = []
    original_normalize = transcribe_module.normalize_transcript

    def count_normalize(text, vocabulary):
        normalize_calls.append(text)
        return original_normalize(text, vocabulary)

    monkeypatch.setattr(transcribe_module, "normalize_transcript", count_normalize)
    transcriber = FasterWhisperTranscriber(AppConfig().speech, [])
    transcriber.load_model = lambda *_args, **_kwargs: Model()
    clip = AudioClip(np.zeros(16000, dtype="float32"), 16000, 1.0)

    assert transcriber.transcribe(clip).endswith("part39")
    assert len(normalize_calls) == 1


def test_transcription_adds_silent_context_without_changing_recorded_audio():
    captured = {}

    class Model:
        @staticmethod
        def transcribe(audio, **_kwargs):
            captured["audio"] = audio
            return iter([SimpleNamespace(text="hello world")]), None

    original = np.linspace(-0.25, 0.25, 1_600, dtype="float32")
    transcriber = FasterWhisperTranscriber(AppConfig().speech, [])
    transcriber.load_model = lambda *_args, **_kwargs: Model()

    assert transcriber.transcribe(AudioClip(original, 16_000, 0.1)) == "hello world"

    padding = int(16_000 * transcribe_module.SPEECH_BOUNDARY_PADDING_SECONDS)
    padded = captured["audio"]
    assert padded.size == original.size + (2 * padding)
    assert not np.any(padded[:padding])
    np.testing.assert_array_equal(padded[padding : padding + original.size], original)
    assert not np.any(padded[-padding:])
