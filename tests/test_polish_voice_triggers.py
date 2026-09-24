from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from voicepilot.app_context import ForegroundContext
from voicepilot.app_pipeline import DictationPipelineMixin
from voicepilot.config import AppConfig, ProfileStyle, Snippet
from voicepilot.paste import InsertResult
from voicepilot.voice_commands import VoiceCommand


class _PipelineHarness(DictationPipelineMixin):
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


def _harness() -> _PipelineHarness:
    harness = _PipelineHarness()
    harness.config = AppConfig()
    harness.config_path = Path("config.yaml")
    harness.hud = Mock()
    harness.transcriber = Mock()
    harness.rewriter = Mock()
    harness.inserter = Mock()
    harness.inserter.paste_text.return_value = InsertResult(True, False, "standard")
    harness.history = Mock()
    harness.last = SimpleNamespace(text="", context=None, history_id="")
    return harness


def test_selected_rewrite_keeps_trailing_enter_out_of_the_model_instruction():
    harness = _harness()
    harness.config.paste.paste_delay_ms = 0
    harness.transcriber.transcribe.return_value = "make this concise press enter"
    harness.rewriter.rewrite.return_value = "Brief update."

    def parse(instruction, *, allow_local_actions):
        assert instruction == "make this concise"
        assert not allow_local_actions
        return VoiceCommand(kind="custom", label="Custom", instruction=instruction)

    harness._parse_voice_command = parse
    context = ForegroundContext("notepad.exe", "Notes", "general", ProfileStyle(label="General"), window_hwnd=100)

    with patch("voicepilot.app_pipeline.record_usage"):
        harness._process_rewrite(None, context, selection="A long status update.", action_id=7)

    assert harness.rewriter.rewrite.call_args.args[1] == "make this concise"
    harness.inserter.press_key.assert_called_once_with("enter")


def test_no_selection_polish_expands_text_shortcut_without_calling_ai():
    harness = _harness()
    harness.config.snippets.items = [Snippet(name="Signature", trigger="insert signature", text="Regards,\nAlex")]
    harness.transcriber.transcribe.return_value = "insert signature"
    context = ForegroundContext("outlook.exe", "New message", "email", ProfileStyle(label="Email"), window_hwnd=100)

    with patch("voicepilot.app_pipeline.record_usage"):
        harness._process_dictation(None, context, polish=True, action_id=9)

    harness.rewriter.polish.assert_not_called()
    harness.inserter.paste_text.assert_called_once_with(
        "Regards,\nAlex",
        process_name="outlook.exe",
        window_title="New message",
        window_hwnd=100,
    )


def test_no_selection_polish_applies_spoken_layout_before_ai():
    harness = _harness()
    harness.transcriber.transcribe.return_value = "First thought new paragraph Second thought new line Third thought"
    harness.rewriter.polish.return_value = "First thought\n\nSecond thought\nThird thought"
    context = ForegroundContext("notepad.exe", "Notes", "notes", ProfileStyle(label="Notes"), window_hwnd=100)

    with patch("voicepilot.app_pipeline.record_usage"):
        harness._process_dictation(None, context, polish=True, action_id=10)

    assert harness.rewriter.polish.call_args.args[0] == ("First thought\n\nSecond thought\nThird thought")


def test_no_selection_polish_runs_local_action_without_ai_or_insertion():
    harness = _harness()
    harness.transcriber.transcribe.return_value = "open history"
    harness._parse_voice_command = Mock(
        return_value=VoiceCommand(
            kind="action",
            label="Open history",
            instruction="Open the local history window.",
            action="open_history",
        )
    )
    harness._execute_voice_action = Mock()
    context = ForegroundContext("notepad.exe", "Notes", "general", ProfileStyle(label="General"), window_hwnd=100)

    with patch("voicepilot.app_pipeline.record_usage"):
        harness._process_dictation(None, context, polish=True, action_id=11)

    harness._execute_voice_action.assert_called_once()
    harness.rewriter.polish.assert_not_called()
    harness.inserter.paste_text.assert_not_called()


def test_polish_commands_are_intrinsic_when_legacy_master_flag_is_off():
    harness = _harness()
    harness.config.voice_commands.enabled = False
    harness.config.voice_commands.edit_presets_enabled = False
    harness.config.voice_commands.local_actions_enabled = False

    edit = harness._parse_voice_command("make this shorter", allow_local_actions=False)
    action = harness._parse_voice_command("undo that", allow_local_actions=True)

    assert edit.kind == "edit"
    assert action.kind == "action"
