from __future__ import annotations

from collections.abc import Callable

from .history import HistoryEvent, HistoryStore
from .history_ui_support import app_label, infer_correction_candidate, mode_label, selected_text


class HistoryDetailsDialog:
    """Focused transcript actions shared by the integrated History page."""

    def __init__(
        self,
        owner,
        event: HistoryEvent,
        *,
        is_latest: bool,
        on_saved: Callable[[], None],
    ) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QDialog,
            QFrame,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QTextEdit,
            QToolButton,
            QVBoxLayout,
        )

        from .paste import TextInserter
        from .windows_ui import apply_native_window_style

        self.owner = owner
        self.event = event
        self.on_saved = on_saved
        self.store = HistoryStore.for_config(
            owner.config_path,
            max_items=owner.config.history.max_items,
            enabled=owner.config.history.enabled,
            retention_days=owner.config.history.retention_days,
        )
        self.inserter = TextInserter(owner.config.paste)

        dialog = QDialog(owner.window)
        dialog.setObjectName("HistoryDetailsDialog")
        dialog.setWindowTitle("Transcript details")
        dialog.setModal(True)
        dialog.setMinimumSize(660, 520)
        dialog.resize(720, 600)
        dialog.setStyleSheet(owner.window.styleSheet())
        self.dialog = dialog

        root = QVBoxLayout(dialog)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(12)
        heading_copy = QVBoxLayout()
        heading_copy.setSpacing(4)
        title = QLabel("Transcript details")
        title.setObjectName("HistoryDetailsTitle")
        meta = QLabel(self._summary())
        meta.setObjectName("HistoryDetailsMeta")
        heading_copy.addWidget(title)
        heading_copy.addWidget(meta)
        header.addLayout(heading_copy, 1)
        close = QPushButton("Close")
        close.setObjectName("HistoryDetailsClose")
        close.clicked.connect(dialog.reject)
        header.addWidget(close, 0, Qt.AlignTop)
        root.addLayout(header)

        result_label = QLabel("Result")
        result_label.setObjectName("HistoryDetailsSectionLabel")
        root.addWidget(result_label)
        self.output = QTextEdit()
        self.output.setObjectName("HistoryDetailsOutput")
        self.output.setAccessibleName("Transcript result")
        result_text = event.output_text or event.input_text
        self.output.setPlainText(result_text)
        self.output.setMinimumHeight(138)
        root.addWidget(self.output, 1)

        original_text = event.input_text.strip()
        if original_text and original_text != result_text.strip():
            original_label = QLabel("Original")
            original_label.setObjectName("HistoryDetailsSectionLabel")
            root.addWidget(original_label)
            original = QTextEdit()
            original.setObjectName("HistoryDetailsOriginal")
            original.setAccessibleName("Original transcript")
            original.setReadOnly(True)
            original.setPlainText(event.input_text)
            original.setMaximumHeight(100)
            root.addWidget(original)
            self.original = original
        else:
            self.original = None

        details_toggle = QToolButton()
        details_toggle.setObjectName("HistoryDetailsToggle")
        details_toggle.setText("More details")
        details_toggle.setCheckable(True)
        details_toggle.setArrowType(Qt.RightArrow)
        details_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        root.addWidget(details_toggle, 0, Qt.AlignLeft)

        details = QFrame()
        details.setObjectName("HistoryDetailsTechnical")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(14, 11, 14, 11)
        details_layout.setSpacing(4)
        details_label = QLabel(self._technical_details())
        details_label.setObjectName("HistoryDetailsTechnicalText")
        details_label.setWordWrap(True)
        details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        details_layout.addWidget(details_label)
        details.setVisible(False)
        root.addWidget(details)
        details_toggle.toggled.connect(
            lambda expanded: (
                details.setVisible(expanded),
                details_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow),
            )
        )
        self.details_toggle = details_toggle
        self.technical_details = details

        actions = QHBoxLayout()
        actions.setSpacing(9)
        copy = QPushButton("Copy")
        copy.setObjectName("HistoryDetailsSecondary")
        copy.clicked.connect(self._copy)
        paste = QPushButton("Paste again")
        paste.setObjectName("HistoryDetailsSecondary")
        paste.clicked.connect(self._repaste)
        learn = QPushButton("Learn correction")
        learn.setObjectName("HistoryDetailsSecondary")
        learn.clicked.connect(self._learn_correction)
        actions.addWidget(copy)
        actions.addWidget(paste)
        actions.addWidget(learn)
        if is_latest:
            undo = QPushButton("Undo last insertion")
            undo.setObjectName("HistoryDetailsSecondary")
            undo.clicked.connect(self._undo_last)
            actions.addWidget(undo)
            self.undo_button = undo
        else:
            self.undo_button = None
        actions.addStretch(1)
        save = QPushButton("Save changes")
        save.setObjectName("PrimaryButton")
        save.setMinimumWidth(132)
        save.clicked.connect(self._save_output_edit)
        actions.addWidget(save)
        root.addLayout(actions)
        self.save_button = save

        self.output.textChanged.connect(self._update_save_state)
        self._update_save_state()
        apply_native_window_style(dialog, owner.palette)
        cursor_policy = getattr(owner, "_button_cursor_policy", None)
        if cursor_policy is not None:
            cursor_policy.apply_tree(dialog)

    def exec(self) -> int:
        try:
            return self.dialog.exec()
        finally:
            cursor_policy = getattr(self.owner, "_button_cursor_policy", None)
            if cursor_policy is not None:
                cursor_policy.restore_after_modal()

    def _summary(self) -> str:
        parts = [mode_label(self.event)]
        profile = self.event.profile_label or self.event.profile_name
        if profile:
            parts.append(profile)
        application = app_label(self.event)
        if application != "Unknown":
            parts.append(application)
        return "  ·  ".join(parts)

    def _technical_details(self) -> str:
        parts: list[str] = []
        if self.event.instruction:
            parts.append(f"Instruction: {self.event.instruction}")
        if self.event.speech_model:
            runtime = self.event.speech_model
            if self.event.speech_device:
                runtime += f" · {self.event.speech_device.upper()}"
            if self.event.speech_compute_type:
                runtime += f"/{self.event.speech_compute_type}"
            parts.append(f"Speech: {runtime}")
        timings = []
        if self.event.transcription_ms:
            timings.append(f"transcribed in {self.event.transcription_ms / 1000:.2f}s")
        if self.event.polish_ms:
            timings.append(f"polished in {self.event.polish_ms / 1000:.2f}s")
        if timings:
            parts.append("Timing: " + " · ".join(timings))
        if self.event.rewrite_model:
            parts.append(f"Writing model: {self.event.rewrite_model}")
        return "\n".join(parts) or "Stored locally on this device."

    def _set_status(self, message: str) -> None:
        self.owner.status.setText(message)
        show_toast = getattr(self.owner, "_show_toast", None)
        if callable(show_toast):
            show_toast(message)

    def _update_save_state(self) -> None:
        changed = self.output.toPlainText().strip() != self.event.output_text.strip()
        self.save_button.setEnabled(changed and bool(self.output.toPlainText().strip()))

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.output.toPlainText())
        self._set_status("Copied to clipboard.")

    def _repaste(self) -> None:
        from PySide6.QtCore import QTimer

        text = self.output.toPlainText().strip()
        if not text:
            return
        self.dialog.accept()
        self.owner.window.hide()

        def paste() -> None:
            try:
                result = self.inserter.paste_text(text)
                if result.sent:
                    self._set_status("Sent transcript again.")
                elif result.copied:
                    self._set_status("Copied transcript because direct insertion was not safe.")
                else:
                    self._set_status(result.reason or "Transcript was not inserted.")
            except Exception as exc:
                self._set_status(f"Could not paste transcript: {exc}")
            QTimer.singleShot(450, self.owner.show)

        QTimer.singleShot(240, paste)

    def _undo_last(self) -> None:
        from PySide6.QtCore import QTimer

        self.dialog.accept()
        self.owner.window.hide()

        def undo() -> None:
            try:
                self.inserter.undo_last_paste()
                self._set_status("Undid the last insertion.")
            except Exception as exc:
                self._set_status(f"Could not undo the last insertion: {exc}")
            QTimer.singleShot(450, self.owner.show)

        QTimer.singleShot(240, undo)

    def _save_output_edit(self) -> None:
        from .control import request_control_command
        from .settings_dialogs import confirm_settings_action

        corrected = self.output.toPlainText().strip()
        if not corrected or corrected == self.event.output_text.strip():
            return
        previous = self.event.output_text
        updated = self.store.update_output(self.event.id, corrected)
        if updated is None:
            self._set_status("Could not save transcript changes.")
            return
        self.event = updated
        learned = False
        candidate = infer_correction_candidate(previous, corrected)
        if candidate is not None and self.owner.config.correction_memory.enabled:
            heard, replacement = candidate
            learned = confirm_settings_action(
                self.dialog,
                self.owner.palette,
                title="Learn this correction?",
                message=f'Always replace “{heard}” with “{replacement}” in future dictations?',
                confirm_label="Learn correction",
            )
            if learned:
                self.owner.correction_store.add_rule(heard, replacement)
                request_control_command(self.owner.config_path, "reload_silent")
        self.on_saved()
        self._update_save_state()
        suffix = " Correction learned." if learned else ""
        self._set_status(f"Transcript updated.{suffix}")

    def _learn_correction(self) -> None:
        from PySide6.QtWidgets import (
            QDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
        )

        from .control import request_control_command
        from .windows_ui import apply_native_window_style

        dialog = QDialog(self.dialog)
        dialog.setObjectName("HistoryCorrectionDialog")
        dialog.setWindowTitle("Learn correction")
        dialog.setModal(True)
        dialog.setFixedWidth(500)
        dialog.setStyleSheet(self.owner.window.styleSheet())
        root = QVBoxLayout(dialog)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(17)
        title = QLabel("Learn correction")
        title.setObjectName("HistoryDetailsTitle")
        hint = QLabel("Winsper will apply this local replacement after speech recognition.")
        hint.setObjectName("HistoryDetailsMeta")
        hint.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(12)
        heard_seed = selected_text(self.output)
        if not heard_seed and self.original is not None:
            heard_seed = selected_text(self.original)
        heard = QLineEdit(heard_seed)
        heard.setPlaceholderText("What Winsper heard")
        replacement = QLineEdit()
        replacement.setPlaceholderText("What it should become")
        form.addRow("Heard", heard)
        form.addRow("Replace with", replacement)
        root.addLayout(form)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("HistoryDetailsSecondary")
        cancel.clicked.connect(dialog.reject)
        save = QPushButton("Learn correction")
        save.setObjectName("PrimaryButton")
        save.setEnabled(bool(heard.text().strip() and replacement.text().strip()))
        heard.textChanged.connect(
            lambda: save.setEnabled(bool(heard.text().strip() and replacement.text().strip()))
        )
        replacement.textChanged.connect(
            lambda: save.setEnabled(bool(heard.text().strip() and replacement.text().strip()))
        )
        save.clicked.connect(dialog.accept)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)
        apply_native_window_style(dialog, self.owner.palette)
        cursor_policy = getattr(self.owner, "_button_cursor_policy", None)
        if cursor_policy is not None:
            cursor_policy.apply_tree(dialog)
        try:
            accepted = dialog.exec() == QDialog.Accepted
        finally:
            cursor_policy = getattr(self.owner, "_button_cursor_policy", None)
            if cursor_policy is not None:
                cursor_policy.restore_after_modal()
        if not accepted:
            return
        self.owner.correction_store.add_rule(
            heard.text(),
            replacement.text(),
        )
        request_control_command(self.owner.config_path, "reload_silent")
        self._set_status(f"Learned correction: {heard.text().strip()} → {replacement.text().strip()}")
