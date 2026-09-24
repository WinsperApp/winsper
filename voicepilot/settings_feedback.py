from __future__ import annotations


from .settings_icons import settings_nav_icon
from .windows_ui import motion_enabled


class SettingsFeedbackMixin:
    def _flash_saved_indicator(self) -> None:
        """Briefly confirm auto-save without interrupting the user."""
        self._show_toast("Saved", "good")

    def _show_inline_status(
        self,
        text: str,
        tone: str = "good",
        *,
        action_label: str = "",
        action_callback=None,
    ) -> None:
        self._show_toast(
            text,
            tone,
            action_label=action_label,
            action_callback=action_callback,
        )

    def _run_toast_action(self) -> None:
        callback = self._toast_action_callback
        self._toast_action_callback = None
        self._save_retry.setVisible(False)
        if callback is not None:
            callback()

    def _position_save_indicator(self) -> None:
        if not self._save_indicator.isVisible():
            return
        x = (self.window.width() - self._save_indicator.width()) // 2
        y = self.window.height() - self._save_indicator.height() - 28
        self._save_indicator.move(max(12, x), max(12, y))

    def _show_toast(
        self,
        text: str,
        tone: str = "good",
        *,
        persistent: bool = False,
        action_label: str = "",
        action_callback=None,
    ) -> None:
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation

        self._toast_hide_timer.stop()
        if self._toast_anim is not None:
            self._toast_anim.stop()

        icon_name = "check" if tone == "good" else "warning" if tone == "bad" else "info"
        icon_color = self.palette.success if tone == "good" else self.palette.coral if tone == "bad" else self.palette.amber
        self._save_icon.setPixmap(settings_nav_icon(icon_name, icon_color, 15).pixmap(15, 15))
        self._save_text.setText(text)
        self._toast_action_callback = action_callback
        self._save_retry.setText(action_label)
        self._save_retry.setVisible(bool(action_label and action_callback))
        self._save_indicator.setProperty("tone", tone)
        self._save_indicator.style().unpolish(self._save_indicator)
        self._save_indicator.style().polish(self._save_indicator)
        self._save_indicator.adjustSize()
        self._save_indicator.setVisible(True)
        self._position_save_indicator()
        self._save_indicator.raise_()
        hide_after_ms = 4000 if action_label else 3500 if tone == "bad" else 900

        if not motion_enabled():
            self._save_opacity.setOpacity(1.0)
            if not persistent:
                self._toast_hide_timer.start(hide_after_ms)
            return

        animation = QPropertyAnimation(self._save_opacity, b"opacity", self.window)
        animation.setDuration(180)
        animation.setStartValue(self._save_opacity.opacity())
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._toast_anim = animation
        animation.start()
        if not persistent:
            self._toast_hide_timer.start(hide_after_ms)

    def _fade_out_toast(self) -> None:
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation

        if not self._save_indicator.isVisible():
            return
        if not motion_enabled():
            self._save_indicator.setVisible(False)
            return
        if self._toast_anim is not None:
            self._toast_anim.stop()
        animation = QPropertyAnimation(self._save_opacity, b"opacity", self.window)
        animation.setDuration(180)
        animation.setStartValue(self._save_opacity.opacity())
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.InCubic)

        def finish() -> None:
            if self._toast_anim is animation:
                self._save_indicator.setVisible(False)

        animation.finished.connect(finish)
        self._toast_anim = animation
        animation.start()

    def _ensure_required_save_widgets(self) -> None:

        current_index = self.stack.currentIndex()
        for key in [
            "hotkeys.dictate",
            "hotkeys.polish",
            "hotkeys.cancel",
            "hotkeys.tap_to_toggle_dictation",
            "hotkeys.toggle_tap_seconds",
            "dictation.ramble_model",
            "dictation.polish_enabled",
            "dictation.polish_fallback_to_ramble",
            "spoken_formatting.enabled",
            "spoken_actions.enabled",
            "spoken_actions.enter_phrase",
            "snippets.enabled",
            "correction_memory.enabled",
            "correction_memory.max_rules",
            "hud.theme",
            "hud.mode",
            "hud.position",
            "hud.enabled",
            "hud.recording_chimes",
            "tray.enabled",
            "startup.start_with_windows",
            "hud.show_idle",
            "hud.opacity",
            "hud.auto_hide_seconds",
            "history.enabled",
            "history.max_items",
        ]:
            if key not in self.widgets:
                self._show_named_page(self._page_for_widget(key))
        if any(key not in self.widgets for key in self._hidden_widget_keys()):
            self._ensure_page_loaded(self.page_names.index("Hidden Fields"))
        if 0 <= current_index < len(self.page_names):
            self._show_page(current_index)
