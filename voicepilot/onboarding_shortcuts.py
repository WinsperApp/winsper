from __future__ import annotations

import queue
import threading
from dataclasses import replace

from .audio import RecordingTooShort
from .destination import infer_destination
from .hotkeys import GlobalHoldHotkeys, validate_hotkey_bindings
from .instruction_quality import instruction_language_for_selection
from .onboarding_helpers import friendly_setup_error
from .transcribe import clip_has_speech_activity
from .rewrite import TextRewriter
from .spoken_formatting import apply_spoken_layout
from .vocabulary import effective_vocabulary


class OnboardingShortcutsMixin:
    """Drive onboarding exercises through the same hold shortcuts as the app."""

    def _shortcut_values(self) -> tuple[str, str]:
        return self.dictate_shortcut_recorder.value(), self.polish_shortcut_recorder.value()

    def _on_shortcut_changed(self, _value: str = "") -> None:
        dictate, polish = self._shortcut_values()
        errors = validate_hotkey_bindings(dictate, polish, self.config.hotkeys.cancel)
        message = errors[0] if errors else ""
        for label in (self.hotkey_check_status, self.polish_shortcut_status):
            label.setText(message)
            label.setVisible(bool(message))
            label.setProperty("tone", "warning" if errors else "good")
            label.style().unpolish(label)
            label.style().polish(label)
        self.dictation_practice_shortcut_chip.setValue(dictate)
        if self.trigger_shortcut_chip is not None:
            self._set_shortcut_chip_value(self.trigger_shortcut_chip, dictate)
        self._restart_onboarding_hotkeys()

    def _restart_onboarding_hotkeys(self) -> None:
        if self.index not in {1, 2, 3}:
            self._stop_onboarding_hotkeys()
            return
        if not self.dictation_runtime_ready:
            self._stop_onboarding_hotkeys()
            return
        if self.dictation_test_hud is None:
            self._prepare_dictation_test_hud()
        # Wait for the separate HUD process: audio must never start without
        # a visible listening state.
        if self.dictation_test_hud is None or not self.dictation_test_hud_ready.is_set():
            self._stop_onboarding_hotkeys()
            return
        from PySide6.QtGui import QGuiApplication

        # Unit and screenshot tests must never register system-wide shortcuts.
        if QGuiApplication.platformName().casefold() == "offscreen":
            self._stop_onboarding_hotkeys()
            return
        dictate, polish = self._shortcut_values()
        errors = validate_hotkey_bindings(dictate, polish, self.config.hotkeys.cancel)
        if errors:
            self._stop_onboarding_hotkeys()
            return
        signature = (dictate, polish, self.config.hotkeys.cancel)
        if self.onboarding_hotkeys is not None and self.onboarding_hotkey_signature == signature:
            return
        self._stop_onboarding_hotkeys()
        try:
            self.onboarding_hotkeys = GlobalHoldHotkeys(
                dictate,
                polish,
                "",
                lambda mode: self.onboarding_hotkey_bridge.triggered.emit("start", mode),
                lambda mode: self.onboarding_hotkey_bridge.triggered.emit("stop", mode),
                cancel_combo=self.config.hotkeys.cancel,
                asynchronous_callbacks=True,
            )
            self.onboarding_hotkeys.start()
            self.onboarding_hotkey_signature = signature
        except Exception as exc:
            self.onboarding_hotkeys = None
            self.onboarding_hotkey_signature = None
            if self.index == 3:
                self._set_trigger_practice_state(
                    "error",
                    "Shortcut needs attention",
                    friendly_setup_error(exc),
                )
            else:
                target = self.hotkey_check_status if self.index == 1 else self.polish_shortcut_status
                target.setText(f"Windows could not activate this shortcut: {friendly_setup_error(exc)}")

    def _stop_onboarding_hotkeys(self) -> None:
        hotkeys = self.onboarding_hotkeys
        self.onboarding_hotkeys = None
        self.onboarding_hotkey_signature = None
        if hotkeys is not None:
            hotkeys.stop()

    def _handle_onboarding_hotkey_event(self, event: str, mode: str) -> None:
        if self.index == 1 and mode == "dictate":
            if event == "start":
                self.dictate_shortcut_recorder.dismissAttention()
                self.dictation_practice_shortcut_chip.dismissAttention()
            (self._begin_dictation_recording if event == "start" else self._finish_dictation_recording)()
        elif self.index == 2 and mode == "polish":
            if event == "start":
                self.polish_shortcut_recorder.dismissAttention()
            (self._begin_polish_recording if event == "start" else self._finish_polish_recording)()
        elif self.index == 3 and mode == "dictate":
            (self._begin_dictation_recording if event == "start" else self._finish_dictation_recording)()

    def _selected_polish_app(self) -> dict[str, str]:
        button = self.polish_app_group.checkedButton()
        if button is None:
            return {"label": "Outlook", "process": "outlook.exe", "profile": "email"}
        return {
            "label": str(button.property("app_label") or "Outlook"),
            "process": str(button.property("process_name") or "outlook.exe"),
            "profile": str(button.property("profile_name") or "email"),
        }

    def _on_polish_app_selected(self, button) -> None:
        self.polish_free_prompt_text.setText(str(button.property("spoken_example") or ""))
        mode_button = self.polish_mode_group.checkedButton()
        mode = str(mode_button.property("mode_id") or "free") if mode_button else "free"
        self._set_polish_practice_state(
            mode,
            "idle",
            f"Waiting for Polish in {button.property('app_label')}",
            "Hold Polish and read the example above.",
            "Your app-aware result will appear here.",
        )

    def _on_polish_enabled_changed(self, enabled: bool) -> None:
        self.polish_shortcut_recorder.setAttentionActive(self.index == 2 and enabled)
        if self.polish_options_container is not None:
            self.polish_options_container.setVisible(enabled)
        if self.polish_disabled_state is not None:
            self.polish_disabled_state.setVisible(not enabled)
        parent = self.polish_options_container.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().activate()
        page = self.stack.widget(2)
        if not enabled and hasattr(page, "verticalScrollBar"):
            page.verticalScrollBar().setValue(0)
        if enabled:
            self.config.onboarding.polish_skipped = False
            self._refresh_polish_setup_status()
            self._ensure_polish_test_runtime()
        else:
            self.config.onboarding.polish_skipped = True
            self._stop_polish_test()
            self._stop_polish_test_runtime()

    def _ensure_polish_test_runtime(self) -> None:
        if (
            self.index != 2
            or not self.polish_check.isChecked()
            or not self._polish_support_ready()
            or not self.dictation_runtime_ready
        ):
            return
        config = self._preview_config()
        model_id = config.rewrite.llama_model_id
        if self.polish_rewriter is not None and self.polish_runtime_model_id == model_id:
            return
        if self.polish_runtime_preparing and self.polish_runtime_model_id == model_id:
            return
        self._stop_polish_test_runtime()
        self.polish_runtime_generation += 1
        generation = self.polish_runtime_generation
        cancel_event = threading.Event()
        self.polish_runtime_cancel_event = cancel_event
        self.polish_runtime_preparing = True
        self.polish_runtime_model_id = model_id
        mode_button = self.polish_mode_group.checkedButton()
        mode = str(mode_button.property("mode_id") or "free") if mode_button else "free"
        self._set_polish_practice_state(
            mode,
            "process",
            "Preparing Polish",
            "Loading the selected writing model once for fast reuse.",
        )
        threading.Thread(
            target=self._prepare_polish_test_runtime,
            args=(config, generation, model_id, cancel_event),
            name="WinsperOnboardingPolishPrepare",
            daemon=True,
        ).start()

    def _prepare_polish_test_runtime(self, config, generation: int, model_id: str, cancel_event) -> None:
        rewriter = None
        try:
            rewriter = TextRewriter(config.rewrite, effective_vocabulary(config))
            if not rewriter.warm_up(cancel_event):
                self.polish_runtime_events.put((generation, "cancelled", None))
                rewriter.close()
                return
            self.polish_runtime_events.put((generation, "ready", (model_id, rewriter)))
        except Exception as exc:
            if rewriter is not None:
                rewriter.close()
            self.polish_runtime_events.put((generation, "error", friendly_setup_error(exc)))

    def _poll_polish_runtime(self) -> None:
        while True:
            try:
                generation, event, payload = self.polish_runtime_events.get_nowait()
            except queue.Empty:
                return
            if generation != self.polish_runtime_generation:
                if event == "ready":
                    payload[1].close()
                continue
            self.polish_runtime_preparing = False
            if event == "ready":
                model_id, rewriter = payload
                self.polish_runtime_model_id = model_id
                self.polish_rewriter = rewriter
                mode_button = self.polish_mode_group.checkedButton()
                mode = str(mode_button.property("mode_id") or "free") if mode_button else "free"
                self._set_polish_practice_state(
                    mode,
                    "idle",
                    "Waiting for your Polish shortcut",
                    "Hold Polish when you are ready.",
                )
            elif event == "error":
                self._set_polish_practice_state(
                    self.polish_active_mode,
                    "error",
                    "Polish needs attention",
                    "The selected writing model could not start.",
                    str(payload),
                )

    def _stop_polish_test_runtime(self) -> None:
        self.polish_runtime_generation += 1
        self.polish_runtime_preparing = False
        cancel_event = self.polish_runtime_cancel_event
        self.polish_runtime_cancel_event = None
        if cancel_event is not None:
            cancel_event.set()
        rewriter = self.polish_rewriter
        self.polish_rewriter = None
        self.polish_runtime_model_id = ""
        if rewriter is not None:
            rewriter.close()

    def _on_polish_mode_selected(self, button) -> None:
        if button is None:
            return
        selected_mode = str(button.property("mode_id") or "free")
        if self.polish_free_speech_card is not None:
            self.polish_free_speech_card.setVisible(selected_mode == "free")
        if getattr(self, "polish_free_prompt_card", None) is not None:
            self.polish_free_prompt_card.setVisible(selected_mode == "free")
        if self.polish_selected_text_card is not None:
            self.polish_selected_text_card.setVisible(selected_mode == "selected")
        if selected_mode != "selected":
            self.polish_selection_editor.clearFocus()

    def _set_polish_practice_state(
        self,
        mode: str,
        tone: str,
        title: str,
        detail: str,
        result: str | None = None,
    ) -> None:
        from .settings_icons import settings_nav_icon

        prefix = "polish_selected" if mode == "selected" else "polish_free"
        state_title = getattr(self, f"{prefix}_state_title", None)
        state_hint = getattr(self, f"{prefix}_state_hint", None)
        state_icon = getattr(self, f"{prefix}_state_icon", None)
        result_icon = getattr(self, f"{prefix}_result_icon", None)
        result_widget = self.polish_selection_result if mode == "selected" else self.polish_test_result
        color = {
            "success": self.palette.success,
            "warning": self.palette.coral,
            "error": self.palette.coral,
            "record": self.palette.accent,
            "process": self.palette.accent,
            "idle": self.palette.muted,
        }.get(tone, self.palette.muted)
        icon = {
            "success": "check",
            "warning": "warning",
            "error": "warning",
            "selected": "edit",
        }.get(tone, "edit" if mode == "selected" else "polish")
        if state_title is not None:
            state_title.setText(title)
        if state_hint is not None:
            state_hint.setText(detail)
        if state_icon is not None:
            state_icon.setPixmap(settings_nav_icon(icon, color, 18).pixmap(18, 18))
        if result_icon is not None:
            result_icon.setPixmap(settings_nav_icon(icon, color, 16).pixmap(16, 16))
        if result is not None:
            result_widget.setText(result)

    def _set_trigger_practice_state(
        self,
        tone: str,
        title: str,
        detail: str,
        result: str | None = None,
    ) -> None:
        from .settings_icons import settings_nav_icon

        prefix = "trigger_date" if self.trigger_test_stage in {"date", "complete"} else "trigger_format"
        state_title = getattr(self, f"{prefix}_state_title", None)
        state_hint = getattr(self, f"{prefix}_state_hint", None)
        state_icon = getattr(self, f"{prefix}_state_icon", None)
        result_icon = getattr(self, f"{prefix}_result_icon", None)
        result_widget = self.trigger_date_result if prefix == "trigger_date" else self.trigger_format_result
        color = {
            "success": self.palette.success,
            "warning": self.palette.coral,
            "error": self.palette.coral,
            "record": self.palette.accent,
            "process": self.palette.accent,
            "idle": self.palette.muted,
        }.get(tone, self.palette.muted)
        icon = "check" if tone == "success" else "warning" if tone in {"warning", "error"} else "shortcuts"
        if state_title is not None:
            state_title.setText(title)
        if state_hint is not None:
            state_hint.setText(detail)
        if state_icon is not None:
            state_icon.setPixmap(settings_nav_icon(icon, color, 18).pixmap(18, 18))
        if result_icon is not None:
            result_icon.setPixmap(settings_nav_icon(icon, color, 16).pixmap(16, 16))
        if result is not None:
            result_widget.setText(result)

    @staticmethod
    def _set_trigger_task_state(card, *, complete: bool, active: bool) -> None:
        card.setProperty("taskComplete", complete)
        card.setProperty("activeTask", active)
        card.style().unpolish(card)
        card.style().polish(card)

    def _evaluate_trigger_dictation(self, text: str) -> bool:
        from .snippets import match_snippet
        from .voice_commands import split_trailing_enter_action

        if self.trigger_test_stage == "formatting":
            remaining, action = split_trailing_enter_action(
                text,
                self.config.spoken_actions.enter_phrase,
                self.config.spoken_actions.enabled,
            )
            formatted = "\n" in remaining
            if action == "enter" or formatted:
                detail_parts = []
                if formatted:
                    detail_parts.append("spoken layout recognized")
                if action == "enter":
                    detail_parts.append("Enter recognized")
                preview = remaining or "No text before the Enter trigger."
                if action == "enter":
                    preview = f"{preview}\n\n↵ Enter will be pressed"
                self._set_trigger_practice_state(
                    "success",
                    "Formatting trigger recognized",
                    " · ".join(detail_parts),
                    preview,
                )
                self._set_trigger_task_state(
                    self.trigger_format_card, complete=True, active=False
                )
                self.trigger_test_stage = "date"
                self.trigger_date_card.show()
                self._set_trigger_task_state(
                    self.trigger_date_card, complete=False, active=True
                )
                self._set_trigger_practice_state(
                    "idle",
                    "Now try today's date",
                    "Hold Dictate, say “today's date”, then release.",
                )
                page = self.stack.currentWidget()
                if hasattr(page, "ensureWidgetVisible"):
                    page.ensureWidgetVisible(self.trigger_date_card, 0, 60)
                from PySide6.QtCore import Qt, QTimer

                QTimer.singleShot(
                    0,
                    lambda: self.trigger_date_panel.setFocus(Qt.OtherFocusReason),
                )
                return True
            self._set_trigger_practice_state(
                "warning",
                "No formatting trigger recognized",
                "Try ending with “press enter”, or say “new line” in the sentence.",
                text,
            )
            return False

        match = match_snippet(text, self.config.snippets.items) if self.config.snippets.enabled else None
        if match is not None and match.snippet.trigger.casefold() == "today's date":
            self.trigger_test_stage = "complete"
            self._set_trigger_practice_state(
                "success",
                "Today's date recognized",
                "Winsper expanded the saved text shortcut.",
                match.text,
            )
            self._set_trigger_task_state(
                self.trigger_date_card, complete=True, active=False
            )
            from PySide6.QtCore import Qt

            self.next_button.setFocus(Qt.OtherFocusReason)
            return True
        self._set_trigger_practice_state(
            "warning",
            "Date trigger not recognized",
            "Hold Dictate and say only “today's date”.",
            text,
        )
        return False

    def _current_selected_demo_text(self) -> str:
        cursor = self.polish_selection_editor.textCursor()
        return cursor.selectedText().replace("\u2029", "\n").strip() if cursor.hasSelection() else ""

    def _begin_polish_recording(self) -> None:
        mode_button = self.polish_mode_group.checkedButton()
        mode = str(mode_button.property("mode_id") or "free") if mode_button else "free"
        self.polish_active_mode = mode
        if self.polish_test_running:
            self._set_polish_practice_state(
                mode, "process", "Finishing your last request", "Polish will be ready again shortly."
            )
            return
        if not self.polish_check.isChecked() or not self._polish_support_ready():
            self._set_polish_practice_state(
                mode, "warning", "Polish is not ready", "Enable Polish and download the selected model first."
            )
            self._show_dictation_test_hud("Polish is not ready", "Finish setup first", "warning")
            return
        if not self._speech_support_ready():
            self._set_polish_practice_state(
                mode, "warning", "Speech support is not ready", "Return to Language & quality first."
            )
            self._show_dictation_test_hud("Speech support is not ready", "Return to Language & quality", "warning")
            return
        if not self.dictation_runtime_ready or self.dictation_transcriber is None:
            self._set_polish_practice_state(
                mode, "process", "Preparing speech", "Polish will be ready as soon as Dictate finishes loading."
            )
            self._show_dictation_test_hud("Preparing Winsper", "Getting speech ready", "preparing")
            return
        if self.polish_rewriter is None:
            self._ensure_polish_test_runtime()
            self._set_polish_practice_state(
                mode, "process", "Preparing Polish", "Loading the selected writing model once for fast reuse."
            )
            self._show_dictation_test_hud("Preparing Polish", "Getting writing support ready", "preparing")
            return
        self.polish_selected_text = self._current_selected_demo_text() if mode == "selected" else ""
        if mode == "selected" and not self.polish_selected_text:
            self._set_polish_practice_state(
                mode,
                "warning",
                "Select text first",
                "Keep part or all of the sample selected, then hold Polish.",
            )
            self._show_dictation_test_hud("Select text first", "Nothing was changed", "warning")
            return
        self.polish_active_app = (
            {"label": "Selected text", "process": "", "profile": "general"}
            if mode == "selected"
            else self._selected_polish_app()
        )
        # Match the production app: Dictate and Polish share the already-warmed
        # recorder instead of reopening the microphone for every Polish attempt.
        self.polish_recorder = self.dictation_recorder
        self.polish_test_running = True
        self.polish_recording = True
        if mode == "selected":
            hud_title = "Say your instruction"
            hud_subtitle = "Selected text — release to transform"
        else:
            hud_title = "Listening for polish"
            hud_subtitle = f"{self.polish_active_app['label']} — release to polish"
        self._set_polish_practice_state(
            mode,
            "record",
            hud_title,
            "Release the shortcut when you finish speaking.",
            "Listening…",
        )
        try:
            self.polish_recorder.start()
            self._show_dictation_test_hud(hud_title, hud_subtitle, "rewrite")
        except Exception as exc:
            self.polish_recording = False
            self.polish_test_running = False
            self.polish_recorder = None
            self._set_polish_practice_state(
                mode, "error", "Microphone needs attention", "Check your microphone and try again.", friendly_setup_error(exc)
            )

    def _finish_polish_recording(self) -> None:
        if not self.polish_recording or self.polish_recorder is None:
            return
        recorder = self.polish_recorder
        self.polish_recorder = None
        self.polish_recording = False
        try:
            clip = recorder.stop()
        except RecordingTooShort:
            self.polish_test_running = False
            self._set_polish_practice_state(
                self.polish_active_mode,
                "warning",
                "Nothing heard",
                "Hold Polish a little longer and try again.",
                "No speech was detected.",
            )
            self._show_dictation_test_hud(
                "Nothing heard", "No speech was detected", "warning"
            )
            return
        except Exception as exc:
            self.polish_test_running = False
            self._set_polish_practice_state(
                self.polish_active_mode,
                "error",
                "Microphone needs attention",
                "Check your microphone and try again.",
                friendly_setup_error(exc),
            )
            return
        self._set_polish_practice_state(
            self.polish_active_mode,
            "process",
            "Transcribing",
            "Turning your instruction into text.",
            "Working…",
        )
        self._show_dictation_test_hud(
            "Transcribing", self.polish_active_app["label"], "process"
        )
        threading.Thread(
            target=self._run_live_polish,
            args=(
                self._preview_config(),
                clip,
                self.polish_selected_text,
                self.polish_active_app,
                self.dictation_transcriber,
                self.polish_rewriter,
            ),
            name="WinsperOnboardingPolish",
            daemon=True,
        ).start()

    def _run_live_polish(self, config, clip, selected_text: str, app: dict[str, str], transcriber, rewriter) -> None:
        try:
            speech_config = replace(
                transcriber.mode_config(config.dictation.ramble_model),
                purpose="polish_instruction" if selected_text else "dictation",
            )
            if selected_text:
                speech_config = replace(
                    speech_config,
                    language=instruction_language_for_selection(
                        speech_config.language,
                        selected_text,
                    ),
                )
            profile = config.profiles.styles.get(app["profile"])
            instruction = transcriber.transcribe(clip, profile=profile, config=speech_config).strip()
            instruction = self.dictation_corrections.apply(instruction, app["profile"])
            instruction = apply_spoken_layout(instruction, config.spoken_formatting.enabled)
            if not instruction:
                raise RuntimeError("No speech was detected.")
            self._show_dictation_test_hud(
                "Polishing text", "Improving clarity", "rewrite"
            )
            destination = infer_destination(app["process"], app["label"], app["profile"], app["label"])
            if selected_text:
                result = rewriter.rewrite(
                    selected_text,
                    instruction,
                    profile=profile,
                    app_label=app["label"],
                    destination=destination,
                ).strip()
            else:
                result = rewriter.polish(
                    instruction,
                    profile=profile,
                    app_label=app["label"],
                    destination=destination,
                    language=config.speech.language,
                ).strip()
            result = self.dictation_corrections.apply(result, app["profile"])
            if not result:
                raise RuntimeError("Polish returned no text. Nothing was changed.")
            self.polish_test_events.put(("done", (instruction, result, bool(selected_text), app["label"])))
        except Exception as exc:
            message = (
                "No speech was detected."
                if self._is_no_speech_error(exc) or not clip_has_speech_activity(clip)
                else friendly_setup_error(exc)
            )
            self.polish_test_events.put(("error", message))

    def _poll_live_polish(self) -> None:
        self._poll_polish_runtime()
        while True:
            try:
                event, payload = self.polish_test_events.get_nowait()
            except queue.Empty:
                return
            self.polish_test_running = False
            if event == "error":
                if self._is_no_speech_error(payload):
                    self._set_polish_practice_state(
                        self.polish_active_mode,
                        "warning",
                        "Nothing heard",
                        "Hold Polish and try again.",
                        "No speech was detected.",
                    )
                    self._show_dictation_test_hud(
                        "Nothing heard", "No speech was detected", "warning"
                    )
                    continue
                self._set_polish_practice_state(
                    self.polish_active_mode,
                    "error",
                    "Polish needs attention",
                    "Nothing was changed.",
                    str(payload),
                )
                self._show_dictation_test_hud("Polish needs attention", "Nothing was changed", "error")
                continue
            heard, result, selected, app_label = payload
            if selected:
                self._set_polish_practice_state(
                    "selected", "success", "Selected text transformed", f"Winsper heard: {heard}", result
                )
                result_widget = self.polish_selection_result
            else:
                self._set_polish_practice_state(
                    "free", "success", f"Polished for {app_label}", f"Winsper heard: {heard}", result
                )
                result_widget = self.polish_test_result
            page = self.stack.currentWidget()
            if hasattr(page, "ensureWidgetVisible"):
                page.ensureWidgetVisible(result_widget, 0, 60)
            self._show_dictation_test_hud("Polish complete", app_label, "success")

    def _stop_polish_test(self) -> None:
        recorder = self.polish_recorder
        self.polish_recorder = None
        self.polish_recording = False
        self.polish_test_running = False
        if recorder is not None:
            try:
                recorder.stop()
            except Exception:
                pass


__all__ = ["OnboardingShortcutsMixin"]
