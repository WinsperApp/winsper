from __future__ import annotations

import pytest

from voicepilot.audio import AudioClip
from voicepilot.config import AppConfig
from voicepilot.instruction_quality import assess_instruction, instruction_language_for_selection
from voicepilot.transcribe import FasterWhisperTranscriber


@pytest.mark.parametrize(
    "instruction",
    [
        "answer it",
        "replace this with a synonym",
        "translate this to French",
        "make it more professional",
        "delete",
        "make bold",
        "use SQL",
        "SQL",
        "CSS",
        "summarize",
        "fix API",
        "create a JSON with a key as x and value as 12",
        "इसे छोटा करें",
        "rends-le plus professionnel",
    ],
)
def test_arbitrary_short_instructions_are_accepted(instruction):
    assert assess_instruction(instruction).accepted


@pytest.mark.parametrize(
    ("instruction", "code"),
    [
        ("", "empty"),
        ("um uh hmm", "filler_only"),
        ("change change change change", "repetition"),
        ("������", "corrupted"),
        ("thank you for watching", "hallucination"),
        ("HTP TP.", "unclear_short"),
        ("इसे बदलें", "language_mismatch"),
    ],
)
def test_suspicious_instruction_transcripts_are_rejected(instruction, code):
    assessment = assess_instruction(instruction, language="en")
    assert not assessment.accepted
    assert assessment.code == code


def test_almost_silent_instruction_audio_is_rejected():
    import numpy as np

    clip = AudioClip(np.zeros(1600, dtype="float32"), 16000, 0.1)
    assessment = assess_instruction("make it shorter", clip, "en")

    assert not assessment.accepted
    assert assessment.code == "low_energy"


def test_normal_quiet_instruction_audio_is_not_over_rejected():
    import numpy as np

    clip = AudioClip(np.full(1600, 0.001, dtype="float32"), 16000, 0.1)
    assert assess_instruction("make it shorter", clip, "en").accepted


def test_selected_text_echo_is_rejected_but_arbitrary_instruction_is_allowed():
    echo = assess_instruction("What is product management?", context_text="What is product management?")

    assert not echo.accepted
    assert echo.code == "context_echo"
    assert assess_instruction("Answer this", context_text="What is product management?").accepted


def test_selection_script_guides_auto_instruction_language_only():
    assert instruction_language_for_selection("", "यह चयनित पाठ है") == "hi"
    assert instruction_language_for_selection("", "Please बदलें this text") == "mix-hi-en"
    assert instruction_language_for_selection("", "plain English text") == ""
    assert instruction_language_for_selection("fr", "यह चयनित पाठ है") == "fr"


def test_instruction_purpose_uses_short_utterance_decode_policy():
    from types import SimpleNamespace

    import numpy as np

    captured = {}

    class Model:
        def transcribe(self, _audio, **kwargs):
            captured.update(kwargs)
            return iter([SimpleNamespace(text=" make it shorter")]), None

    config = AppConfig().speech
    config.purpose = "polish_instruction"
    transcriber = FasterWhisperTranscriber(config, [])
    transcriber.load_model = lambda *_args, **_kwargs: Model()
    clip = AudioClip(np.ones(16000, dtype="float32"), 16000, 1.0)

    assert transcriber.transcribe(clip) == "make it shorter"
    assert captured["beam_size"] == 3
    assert captured["vad_parameters"] == {
        "min_speech_duration_ms": 96,
        "min_silence_duration_ms": 320,
        "speech_pad_ms": 160,
        "threshold": 0.35,
    }
    assert captured["no_speech_threshold"] == 0.35
    assert captured["compression_ratio_threshold"] == 2.2
    assert captured["log_prob_threshold"] == -0.8
    assert "bullet points" in captured["hotwords"]
    assert "proofread" in captured["hotwords"]


def test_runtime_assigns_instruction_purpose_only_to_selected_text_asr():
    from voicepilot.app_speech_backend import SpeechBackendLifecycleMixin

    class Transcriber:
        @staticmethod
        def mode_config(model):
            config = AppConfig().speech
            config.model = model
            return config

    class Harness(SpeechBackendLifecycleMixin):
        pass

    harness = Harness()
    harness.config = AppConfig()
    harness.transcriber = Transcriber()

    assert harness._speech_config_for_mode("dictate").purpose == "dictation"
    assert harness._speech_config_for_mode("polish").purpose == "dictation"
    assert harness._speech_config_for_mode("rewrite").purpose == "polish_instruction"


def test_suspicious_instruction_never_reaches_rewrite_model():
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    from voicepilot.app_context import ForegroundContext
    from voicepilot.app_pipeline import DictationPipelineMixin
    from voicepilot.config import ProfileStyle

    class Harness(DictationPipelineMixin):
        @staticmethod
        def _action_cancelled(_action_id):
            return False

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
    harness.config_path = SimpleNamespace(parent=None)
    harness.hud = Mock()
    harness.transcriber = Mock()
    harness.transcriber.transcribe.return_value = "change change change change"
    harness.rewriter = Mock()
    context = ForegroundContext("notepad.exe", "Notes", "general", ProfileStyle(label="General"))

    with patch("voicepilot.app_pipeline.write_runtime_log") as runtime_log:
        harness._process_rewrite(None, context, selection="original", action_id=7)

    harness.rewriter.rewrite.assert_not_called()
    runtime_log.assert_called_once()
    assert harness.hud.show_action_message.call_args.args == (
        7,
        "Instruction unclear",
        "Nothing changed",
        "warning",
    )
