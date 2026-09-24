from __future__ import annotations

import logging
import time
from dataclasses import replace

from .app_context import ForegroundContext, get_foreground_window_details
from .action_state import ActionStage
from .action_presentation import ActionPresentationMixin, rewrite_delivery_message
from .destination import extract_explicit_language, infer_language_from_selection
from .command_preview import RewritePreview, choose_rewrite_action
from .history import create_history_event
from .history_metrics import measure_ms, measure_text_ms, performance_fields
from .instruction_quality import assess_instruction, instruction_language_for_selection
from .llama_server import LlamaServerModelMissing, LlamaServerUnavailable
from .ollama import OllamaModelMissing, OllamaUnavailable
from .paste import DeliveryStatus
from .selection import SelectionStatus
from .runtime_log import write_runtime_log
from .snippets import match_snippet
from .spoken_formatting import apply_spoken_layout
from .self_corrections import resolve_explicit_self_corrections
from .usage import record_usage
from .voice_commands import VoiceCommand, parse_voice_command, split_trailing_enter_action
from .app_support_actions import PipelineSupportActionsMixin
from .app_helpers import (
    _resolved_speech_status,
    friendly_error_message,
    history_instruction,
    is_prompt_context,
    local_ai_message,
    log_runtime_error,
    polish_fallback_message,
)

logger = logging.getLogger(__name__)

REWRITE_UNAVAILABLE_ERRORS = (
    OllamaUnavailable,
    OllamaModelMissing,
    LlamaServerUnavailable,
    LlamaServerModelMissing,
)


def _same_rewrite_text(source: str, rewritten: str) -> bool:
    """Whitespace-only changes must not silently replace selected text."""
    return source.strip() == rewritten.strip()


def _rewrite_delivery_action(result) -> str:
    if result.delivery is DeliveryStatus.TARGET_CHANGED:
        return "copy_target_changed"
    if result.delivery is DeliveryStatus.TARGET_ELEVATED:
        return "copy_elevated"
    return "copy_blocked" if result.copied else "saved_blocked"


class DictationPipelineMixin(PipelineSupportActionsMixin, ActionPresentationMixin):
    def _process_clip(self, mode: str, clip, context: ForegroundContext, action_id: int = 0) -> None:
        try:
            if mode == "dictate":
                self._process_dictation(clip, context, polish=False, action_id=action_id)
            elif mode == "polish":
                self._process_polish(clip, context, action_id)
            else:
                self._process_rewrite(clip, context, action_id=action_id)
        except RuntimeError as exc:
            if self._action_cancelled(action_id):
                return
            log_runtime_error("processing", exc, self.config_path)
            self._fail_action(action_id, "processing_error")
            self._show_action_message(action_id, "Something went wrong", friendly_error_message(exc), "error")
        except Exception as exc:
            if self._action_cancelled(action_id):
                return
            log_runtime_error("unexpected processing", exc, self.config_path)
            self._fail_action(action_id, "processing_error")
            self._show_action_message(action_id, "Something went wrong", "Nothing was inserted. Please try again.", "error")
        finally:
            self._set_idle(action_id)

    def _process_polish(self, clip, context: ForegroundContext, action_id: int = 0) -> None:
        if self._action_cancelled(action_id):
            return
        if not self._target_is_current(context):
            self._show_action_message(action_id, "Target changed", "Return to the selected text and try again", "warning")
            return
        self._advance_action_stage(action_id, ActionStage.READING_SELECTION)
        self._show_action_message(action_id, "Reading selection", context.hud_context_label, "process")
        selection = self._selection_for_polish_action(action_id) if action_id else self.inserter.read_selection()
        if selection.status is SelectionStatus.TARGET_CHANGED:
            self._show_action_message(action_id, "Target changed", "Return to selected text and hold Polish again", "warning")
            return
        if selection.status is SelectionStatus.TARGET_ELEVATED:
            # Windows will not expose selected text across the integrity
            # boundary, but speech-only Polish remains safe: process the
            # recording and leave the result on the clipboard for manual paste.
            self._process_dictation(clip, context, polish=True, action_id=action_id)
            return
        if selection.status is SelectionStatus.UNAVAILABLE:
            self._show_action_message(action_id, "Selection unavailable", "Select text again, then hold Polish", "warning")
            return
        if selection.status is SelectionStatus.CAPTURED:
            self._show_action_message(action_id, "Rewriting selection", "Say how to change it", "rewrite")
            self._process_rewrite(clip, context, selection=selection.text, action_id=action_id)
            return
        self._process_dictation(clip, context, polish=True, action_id=action_id)

    def _process_dictation(self, clip, context: ForegroundContext, polish: bool = False, action_id: int = 0) -> None:
        if self._action_cancelled(action_id):
            return
        mode = "polish" if polish else "dictate"
        speech_config = self._speech_config_for_mode(mode)
        requested_model = self.config.dictation.ramble_model
        self._advance_action_stage(action_id, ActionStage.TRANSCRIBING)
        self._show_action_message(
            action_id,
            "Transcribing",
            _resolved_speech_status(
                self._model_status_text(context.hud_context_label, speech_config.model),
                requested_model,
                speech_config.model,
            ),
            "process",
        )

        def show_partial(partial: str) -> None:
            if not self._action_cancelled(action_id):
                self._show_action_message(action_id, "Live transcript", partial, "process")

        raw_text, transcription_ms = measure_ms(
            self.transcriber.transcribe,
            clip,
            on_partial=show_partial,
            profile=context.writing_profile,
            config=speech_config,
        )
        if self._action_cancelled(action_id):
            return
        spoken_text = raw_text.strip()
        text = self._apply_corrections(spoken_text, context)
        # With no selection, Polish normally treats speech as content to clean
        # up. Explicit Winsper actions are the one exception: handle them
        # before spoken formatting or AI rewriting can alter the command.
        if polish:
            command = self._parse_voice_command(text, allow_local_actions=True)
            if command.kind == "action":
                self._execute_voice_action(command)
                return
        text = apply_spoken_layout(text, self.config.spoken_formatting.enabled)
        text, post_key = split_trailing_enter_action(
            text,
            self.config.spoken_actions.enter_phrase,
            self.config.spoken_actions.enabled,
        )
        if not text and not post_key:
            self._show_action_message(action_id, "Nothing heard", "No speech was detected", "warning")
            return
        if not text and post_key:
            if self._action_cancelled(action_id):
                return
            self.inserter.press_key(post_key)
            self._show_action_message(action_id, "Enter sent", "Spoken action", "success")
            return
        destination = context.destination
        if polish:
            text, destination = extract_explicit_language(text, destination)
            if not text:
                self._show_action_message(action_id, "Nothing heard", "No speech was detected", "warning")
                return
        if polish:
            self._show_action_message(action_id, "Transcribed", text, "process")

        snippet = match_snippet(text, self.config.snippets.items, context.profile_name) if self.config.snippets.enabled else None
        output = snippet.text if snippet is not None else text
        polish_result, polish_ms = "", 0
        if snippet is not None:
            label = snippet.snippet.name or snippet.snippet.trigger
            status = "Snippet" if snippet.mode == "command" else "Snippet expanded"
            self._show_action_message(action_id, status, label, "process")
        elif polish:
            if not self.config.dictation.polish_enabled:
                self._show_action_message(action_id, "Auto-polish is off", "Inserted your raw dictation", "warning")
                polish_result = "disabled"
            else:
                if self._action_cancelled(action_id):
                    return
                polish_title = "Structuring prompt" if is_prompt_context(context) else "Polishing text"
                polish_detail = "Organizing your request" if is_prompt_context(context) else "Improving clarity"
                self._advance_action_stage(action_id, ActionStage.REWRITING)
                self._show_action_message(action_id, polish_title, polish_detail, "rewrite")
                try:
                    output, polish_ms = measure_text_ms(
                        self.rewriter.polish,
                        text,
                        profile=context.writing_profile,
                        app_label=context.hud_label,
                        destination=destination,
                        language=self.config.speech.language,
                    )
                except REWRITE_UNAVAILABLE_ERRORS as exc:
                    if self._action_cancelled(action_id):
                        return
                    if not self.config.dictation.polish_fallback_to_ramble:
                        raise
                    write_runtime_log(self.config_path, "polish fallback", str(exc), exc)
                    logger.warning("Winsper polish fallback: %s", exc)
                    self._show_action_message(action_id, "AI unavailable", polish_fallback_message(exc), "warning")
                    correction = resolve_explicit_self_corrections(text)
                    output = correction.text if correction.has_safe_fallback else text
                    polish_result = "fallback_corrected" if correction.has_safe_fallback else "fallback"
                else:
                    polish_result = "polished"
                if not output:
                    self._show_action_message(action_id, "AI returned nothing", "Inserted your raw dictation instead", "warning")
                    output = text
                    polish_result = "empty"
                output = self._apply_corrections(output, context)
        else:
            self._show_action_message(action_id, "Inserting", f"{len(text.split())} words", "process")

        if self._action_cancelled(action_id):
            return
        self._advance_action_stage(action_id, ActionStage.INSERTING)
        event_mode = (
            "prompt"
            if polish and snippet is None and is_prompt_context(context)
            else ("polish" if polish and snippet is None else "ramble")
        )
        if snippet is not None:
            event_mode = "snippet" if snippet.mode == "command" else "snippet_inline"
        event = create_history_event(
            mode=event_mode,
            input_text=spoken_text,
            output_text=output,
            context=context,
            speech_model=speech_config.model,
            rewrite_model=self._history_rewrite_model() if polish and snippet is None and output != text else "",
            source="dictation:pending",
            snippet_name=snippet.snippet.name if snippet is not None else "",
            snippet_trigger=snippet.snippet.trigger if snippet is not None else "",
            **performance_fields(transcription_ms, polish_ms, speech_config, self.config.speech),
        )
        self._checkpoint_history(event)
        self.last.text = output
        self.last.context = context
        self.last.history_id = event.id

        target_changed = not self._target_is_current(context)
        if target_changed:
            self.inserter.copy_text(output)
            insertion_result = None
        else:
            insertion_result = self.inserter.paste_text(
                output,
                process_name=context.process_name,
                window_title=context.window_title,
                window_hwnd=context.window_hwnd,
            )
            target_changed = insertion_result.delivery is DeliveryStatus.TARGET_CHANGED
        if post_key and insertion_result is not None and insertion_result.sent:
            time.sleep(self.config.paste.paste_delay_ms / 1000)
            if self._action_cancelled(action_id):
                return
            self.inserter.press_key(post_key)
        if self._action_cancelled(action_id):
            return
        if target_changed:
            delivery_source = "dictation:target_changed"
        elif insertion_result is not None and insertion_result.delivery is DeliveryStatus.TARGET_ELEVATED:
            delivery_source = "dictation:elevated_copied"
        elif insertion_result is not None and not insertion_result.sent:
            delivery_source = "dictation:paste_copied" if insertion_result.copied else "dictation:paste_saved"
        else:
            delivery_source = "dictation:sent"
        self._finalize_history(event, delivery_source)
        self._record_usage_safely(event.word_count)
        if target_changed:
            self._show_action_message(action_id, "Target changed", "Result copied — paste it where you want", "warning")
        elif insertion_result is not None and insertion_result.delivery is DeliveryStatus.TARGET_ELEVATED:
            self._show_action_message(action_id, "Copied", insertion_result.reason, "warning")
        elif insertion_result is not None and not insertion_result.sent:
            recovery = "Result copied." if insertion_result.copied else "Result saved in History."
            self._show_action_message(action_id, "Paste blocked", f"{insertion_result.reason} {recovery}", "warning")
        elif insertion_result is not None and insertion_result.reason:
            self._show_action_message(action_id, "Sent", insertion_result.reason, "warning")
        elif snippet is not None:
            status = "Snippet sent" if snippet.mode == "command" else "Snippet expanded and sent"
            suffix = " + Enter" if post_key else ""
            self._show_action_message(action_id, status, f"{snippet.snippet.trigger}{suffix}", "success")
        elif polish and polish_result == "polished":
            suffix = " + Enter" if post_key else ""
            self._show_action_message(action_id, "Polished", f"{len(output)} characters sent{suffix}", "success")
        elif polish and polish_result == "fallback":
            suffix = " + Enter" if post_key else ""
            self._show_action_message(
                action_id,
                "AI unavailable",
                f"Inserted raw dictation — {len(output.split())} words{suffix}",
                "warning",
            )
        elif polish and polish_result == "fallback_corrected":
            suffix = " + Enter" if post_key else ""
            self._show_action_message(
                action_id,
                "Correction applied",
                f"{len(output)} characters sent{suffix}",
                "success",
            )
        elif polish and polish_result == "disabled":
            suffix = " + Enter" if post_key else ""
            self._show_action_message(
                action_id,
                "Auto-polish is off",
                f"Inserted raw dictation — {len(output.split())} words{suffix}",
                "warning",
            )
        elif polish:
            suffix = " + Enter" if post_key else ""
            self._show_action_message(
                action_id,
                "AI skipped",
                f"Inserted raw dictation — {len(output.split())} words{suffix}",
                "warning",
            )
        else:
            suffix = " + Enter" if post_key else ""
            self._show_action_message(
                action_id,
                "Sent",
                f"{context.hud_context_label} - {len(text.split())} words{suffix}",
                "success",
            )

    def _process_rewrite(self, clip, context: ForegroundContext, selection: str = "", action_id: int = 0) -> None:
        if self._action_cancelled(action_id):
            return
        speech_config = self._speech_config_for_mode("rewrite")
        requested_model = self.config.dictation.ramble_model
        instruction_language = instruction_language_for_selection(speech_config.language, selection)
        if instruction_language != speech_config.language:
            speech_config = replace(speech_config, language=instruction_language)
        self._advance_action_stage(action_id, ActionStage.TRANSCRIBING)
        self._show_action_message(
            action_id,
            "Listening to instruction",
            _resolved_speech_status(
                self._model_status_text(context.hud_context_label, speech_config.model),
                requested_model,
                speech_config.model,
            ),
            "process",
        )

        def show_instruction_partial(partial: str) -> None:
            if not self._action_cancelled(action_id):
                self._show_action_message(action_id, "Hearing instruction", partial, "rewrite")

        raw_instruction, transcription_ms = measure_text_ms(
            self.transcriber.transcribe,
            clip,
            on_partial=show_instruction_partial,
            profile=context.profile,
            config=speech_config,
        )
        if self._action_cancelled(action_id):
            return
        instruction = self._apply_corrections(raw_instruction, context)
        instruction, post_key = split_trailing_enter_action(
            instruction,
            self.config.spoken_actions.enter_phrase,
            self.config.spoken_actions.enabled,
        )
        if not instruction and not post_key:
            self._show_action_message(action_id, "Nothing heard", "No instruction was given", "warning")
            return
        if not instruction and post_key:
            self.inserter.press_key(post_key)
            self._show_action_message(action_id, "Enter sent", "Spoken action", "success")
            return
        assessment = assess_instruction(instruction, clip, speech_config.language, selection)
        if not assessment.accepted:
            write_runtime_log(
                self.config_path,
                "instruction rejected",
                f"code={assessment.code}; reason={assessment.reason}",
            )
            self._show_action_message(action_id, "Instruction unclear", "Nothing changed", "warning")
            return
        self._show_action_message(action_id, "Instruction", instruction, "rewrite")

        command = self._parse_voice_command(instruction, allow_local_actions=not bool(selection))
        if command.kind == "action":
            self._execute_voice_action(command)
            return

        rewrite_instruction = command.instruction or instruction
        target = selection
        target_context = context
        if not target:
            self._show_action_message(action_id, "No text selected", "Select text first, then hold Polish", "warning")
            return

        source_label = "selected text"
        command_label = command.label if command.kind == "edit" else "Custom"
        self._advance_action_stage(action_id, ActionStage.REWRITING)
        self._show_action_message(action_id, "Applying instruction", "Rewriting selected text", "rewrite")
        destination = infer_language_from_selection(target, target_context.destination)
        try:
            rewritten, polish_ms = measure_text_ms(
                self.rewriter.rewrite,
                target,
                rewrite_instruction,
                profile=target_context.writing_profile,
                app_label=target_context.hud_label,
                destination=destination,
            )
        except REWRITE_UNAVAILABLE_ERRORS as exc:
            if self._action_cancelled(action_id):
                return
            write_runtime_log(self.config_path, "rewrite unavailable", str(exc), exc)
            logger.warning("Winsper rewrite unavailable: %s", exc)
            self._show_action_message(action_id, "Polish unavailable", local_ai_message(exc), "warning")
            return
        if self._action_cancelled(action_id):
            return
        if not rewritten:
            self._show_action_message(action_id, "Polish empty", "No text was produced", "warning")
            return
        rewritten = self._apply_corrections(rewritten, target_context)
        if _same_rewrite_text(target, rewritten):
            self._show_action_message(action_id, "No change made", "Local AI left selected text unchanged", "warning")
            return

        action = "replace"
        if self.config.rewrite.preview_before_apply:
            self._show_action_message(action_id, "Preview ready", "Choose how to apply the rewrite", "process")
            result = choose_rewrite_action(
                RewritePreview(
                    instruction_label=command_label,
                    source_label=source_label,
                    context_label=target_context.hud_context_label,
                    original_text=target,
                    rewritten_text=rewritten,
                    instruction_text=instruction,
                    theme=self.config.hud.theme,
                )
            )
            if result.action == "error":
                write_runtime_log(self.config_path, "rewrite preview", result.error or "Preview failed")
                self._show_action_message(action_id, "Preview unavailable", "Nothing was changed", "warning")
                return
            if result.action == "cancel":
                self._show_action_message(action_id, "Polish cancelled", "Nothing was changed", "cancelled")
                return
            if self._action_cancelled(action_id):
                return
            rewritten = result.text.strip()
            action = result.action
            if not rewritten:
                self._show_action_message(action_id, "Polish empty", "Nothing was changed", "warning")
                return

        if self._action_cancelled(action_id):
            return
        self._advance_action_stage(action_id, ActionStage.INSERTING)
        event = create_history_event(
            mode="polish_selection",
            input_text=target,
            output_text=rewritten,
            context=target_context,
            speech_model=speech_config.model,
            rewrite_model=self._history_rewrite_model(),
            instruction=history_instruction(instruction, command),
            source=f"selection:{command_label}:pending",
            **performance_fields(transcription_ms, polish_ms, speech_config, self.config.speech),
        )
        self._checkpoint_history(event)
        self.last.text = rewritten
        self.last.context = target_context
        self.last.history_id = event.id

        delivery_warning = ""
        result = None
        target_changed = action != "copy" and not self._target_is_current(target_context)
        if action == "copy":
            self.inserter.copy_text(rewritten)
        elif target_changed:
            self.inserter.copy_text(rewritten)
            action = "copy_target_changed"
        elif action == "insert_below":
            result = self.inserter.insert_below_selection(
                rewritten,
                process_name=target_context.process_name,
                window_title=target_context.window_title,
                window_hwnd=target_context.window_hwnd,
                destination_kind=target_context.destination.kind,
            )
            if not result.sent:
                action = _rewrite_delivery_action(result)
            else:
                delivery_warning = result.reason
        else:
            result = self.inserter.paste_text(
                rewritten,
                process_name=target_context.process_name,
                window_title=target_context.window_title,
                window_hwnd=target_context.window_hwnd,
            )
            if not result.sent:
                action = _rewrite_delivery_action(result)
            else:
                delivery_warning = result.reason

        if post_key and result is not None and result.sent:
            time.sleep(self.config.paste.paste_delay_ms / 1000)
            if self._action_cancelled(action_id):
                return
            self.inserter.press_key(post_key)

        self._finalize_history(event, f"selection:{command_label}:{action}")
        self._record_usage_safely(event.word_count)
        status, detail, tone = rewrite_delivery_message(
            action,
            reason=result.reason if result is not None else "",
            warning=delivery_warning,
            context_label=target_context.hud_context_label,
            word_count=len(rewritten.split()),
        )
        self._show_action_message(action_id, status, detail, tone)

    def _checkpoint_history(self, event) -> None:
        """Keep completed text recoverable before interacting with another app."""
        try:
            self.history.append(event)
        except Exception as exc:
            log_runtime_error("history checkpoint", exc, self.config_path)

    def _advance_action_stage(self, action_id: int, stage: ActionStage) -> None:
        coordinator = getattr(self, "_coordinator", None)
        if coordinator is None or not action_id or not coordinator.advance(action_id, stage):
            return
        show_event = getattr(getattr(self, "hud", None), "show_action_event", None)
        event = coordinator.latest_event()
        if not callable(show_event) or event is None or event.action_id != action_id:
            return
        show_event(event)

    def _finalize_history(self, event, source: str) -> None:
        try:
            self.history.update_source(event.id, source)
        except Exception as exc:
            log_runtime_error("history delivery state", exc, self.config_path)

    def _record_usage_safely(self, words: int) -> None:
        try:
            record_usage(self.config_path, words)
        except Exception as exc:
            log_runtime_error("usage recording", exc, self.config_path)
    @staticmethod
    def _target_is_current(context: ForegroundContext) -> bool:
        current = get_foreground_window_details()
        if context.window_hwnd:
            return current.hwnd == context.window_hwnd
        return current.process_name.lower() == context.process_name.lower() and current.window_title == context.window_title

    def _history_rewrite_model(self) -> str:
        label = getattr(self.rewriter, "model_label", None)
        if callable(label):
            return str(label())
        return f"{self.config.rewrite.provider} \u00b7 {self.config.rewrite.model}"

    def _parse_voice_command(self, instruction: str, *, allow_local_actions: bool = True) -> VoiceCommand:
        return parse_voice_command(
            instruction,
            edit_presets_enabled=True,
            local_actions_enabled=allow_local_actions,
        )

    def _apply_corrections(self, text: str, context: ForegroundContext) -> str:
        if not self.config.correction_memory.enabled:
            return text
        return self.corrections.apply(text, context.profile_name)
