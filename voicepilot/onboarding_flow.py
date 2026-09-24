from __future__ import annotations

from copy import deepcopy

from .onboarding_helpers import ONBOARDING_VERSION, _utc_now


class OnboardingFlowMixin:
    """State transitions shared by the visual first-run flow."""

    def _apply_choices(self, *, completed: bool = True) -> None:
        c = self.config
        self._apply_language_choice(c)
        self._apply_speed_profile(c)
        c.speech.preload_on_startup = self.preload_check.isChecked()
        c.hud.mode = str(self.hud_style_combo.currentData() or "compact")
        c.hotkeys.dictate, c.hotkeys.polish = self._shortcut_values()
        c.dictation.polish_enabled = self.polish_check.isChecked() and self._polish_support_ready()
        c.dictation.polish_fallback_to_ramble = self.fallback_check.isChecked()
        if self._is_first_run or self._polish_provider_changed:
            c.rewrite.provider = "embedded"
            if self.recommended_polish_model is not None:
                c.rewrite.llama_model_id = self.recommended_polish_model.id
                c.rewrite.llama_model_path = ""
        c.startup.start_with_windows = self.startup_check.isChecked()
        c.onboarding.version = ONBOARDING_VERSION
        c.onboarding.current_step = 0 if completed else self.index
        c.onboarding.dictation_test_passed = self.dictation_test_passed
        c.onboarding.polish_skipped = not c.dictation.polish_enabled
        selected_quality = self.speed_group.checkedButton()
        c.onboarding.quality_profile = str(selected_quality.property("profile_id") or "instant")
        c.onboarding.completed = completed
        c.onboarding.completed_at = _utc_now() if completed else ""

    def _preview_config(self):
        c = deepcopy(self.config)
        self._apply_language_choice(c)
        self._apply_speed_profile(c)
        c.speech.preload_on_startup = self.preload_check.isChecked()
        c.hud.mode = str(self.hud_style_combo.currentData() or "compact")
        c.hotkeys.dictate, c.hotkeys.polish = self._shortcut_values()
        c.dictation.polish_enabled = self.polish_check.isChecked()
        c.dictation.polish_fallback_to_ramble = self.fallback_check.isChecked()
        if self._is_first_run or self._polish_provider_changed:
            c.rewrite.provider = "embedded"
            if self.recommended_polish_model is not None:
                c.rewrite.llama_model_id = self.recommended_polish_model.id
                c.rewrite.llama_model_path = ""
        return c

    def _refresh_finish_status(self) -> None:
        speech_ready = self._speech_support_ready()
        if self.finish_language_value is not None:
            self.finish_language_value.setText(self.language_combo.currentText() or "English")
        if self.finish_quality_value is not None:
            selected = self.speed_group.checkedButton()
            profile_id = str(selected.property("profile_id") or "instant") if selected is not None else "instant"
            self.finish_quality_value.setText(
                {"instant": "Fast", "balanced": "Balanced", "precise": "Best quality"}.get(profile_id, "Fast")
            )
        if self.finish_polish_value is not None:
            polish_ready = self.polish_check.isChecked() and self._polish_support_ready()
            self.finish_polish_value.setText("Ready" if polish_ready else "Dictation only")
        if self.finish_shortcut_value is not None:
            from .settings_widgets import format_shortcut

            self.finish_shortcut_value.setText(format_shortcut(self.dictate_shortcut_recorder.value()))
        if self.finish_title is not None:
            self.finish_title.setText("Setup complete" if speech_ready else "Speech support still needed")
        if self.finish_detail is not None:
            self.finish_detail.setText(
                "Winsper is ready to use across your apps."
                if speech_ready
                else "Go back to Language & quality and download the selected model."
            )
        if self.finish_button is not None:
            self.finish_button.setEnabled(speech_ready)
            self.finish_button.setToolTip("" if speech_ready else "Download Dictation support before finishing setup.")

    def _focus_current_step(self) -> None:
        current = self.window.focusWidget()
        if current is not None and current.isVisible():
            return
        from PySide6.QtCore import Qt

        targets = (
            self.language_combo,
            self.dictate_shortcut_recorder,
            self.polish_check,
            self.trigger_format_panel,
            self.finish_button,
        )
        target = targets[self.index]
        if target is not None and target.isVisible() and target.isEnabled():
            target.setFocus(Qt.OtherFocusReason)
