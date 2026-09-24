from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from voicepilot.app_context import ForegroundContext
from voicepilot.app_pipeline import DictationPipelineMixin
from voicepilot.config import AppConfig, ProfileStyle
from voicepilot.paste import ELEVATED_TARGET_REASON, InsertResult
from voicepilot.voice_commands import VoiceCommand


class _Harness(DictationPipelineMixin):
    @staticmethod
    def _action_cancelled(_action_id):
        return False

    def _speech_config_for_mode(self, _mode):
        return self.config.speech

    @staticmethod
    def _model_status_text(_context_label, model):
        return model

    @staticmethod
    def _target_is_current(_context):
        return True

    @staticmethod
    def _apply_corrections(text, _context):
        return text

    @staticmethod
    def _parse_voice_command(instruction, *, allow_local_actions):
        del allow_local_actions
        return VoiceCommand(kind="custom", label="Custom", instruction=instruction)


def _harness() -> _Harness:
    harness = _Harness()
    harness.config = AppConfig()
    harness.config.snippets.enabled = False
    harness.config.dictation.polish_enabled = True
    harness.config_path = Path("config.yaml")
    harness.hud = Mock()
    harness.transcriber = Mock()
    harness.rewriter = Mock()
    harness.inserter = Mock()
    harness.inserter.paste_text.return_value = InsertResult(
        False, True, "target_elevated", ELEVATED_TARGET_REASON
    )
    harness.history = Mock()
    harness.last = SimpleNamespace(text="", context=None, history_id="")
    return harness


def _admin_context() -> ForegroundContext:
    return ForegroundContext(
        "admin.exe",
        "Administrator",
        "general",
        ProfileStyle(label="General"),
        window_hwnd=100,
    )


def test_dictation_and_no_selection_polish_copy_without_claiming_insertion():
    for polish in (False, True):
        harness = _harness()
        harness.transcriber.transcribe.return_value = "a recoverable result"
        harness.rewriter.polish.return_value = "A recoverable result."

        with patch("voicepilot.app_pipeline.record_usage"):
            harness._process_dictation(None, _admin_context(), polish=polish)

        event = harness.history.append.call_args.args[0]
        harness.history.update_source.assert_called_once_with(event.id, "dictation:elevated_copied")
        assert harness.last.text == event.output_text
        assert harness.hud.show.call_args.args == ("Copied", ELEVATED_TARGET_REASON, "warning")
        harness.inserter.press_key.assert_not_called()


def test_selected_text_polish_copies_and_records_elevated_delivery():
    harness = _harness()
    harness.transcriber.transcribe.return_value = "replace with a synonym"
    harness.rewriter.rewrite.return_value = "unwise"

    with patch("voicepilot.app_pipeline.record_usage"):
        harness._process_rewrite(None, _admin_context(), selection="stupid")

    event = harness.history.append.call_args.args[0]
    harness.history.update_source.assert_called_once_with(event.id, "selection:Custom:copy_elevated")
    assert harness.last.text == "unwise"
    assert harness.hud.show.call_args.args == ("Copied", ELEVATED_TARGET_REASON, "warning")
