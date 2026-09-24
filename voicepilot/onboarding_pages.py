from __future__ import annotations

from .ai_catalog import POLISH_MODELS, compatible_polish_models, polish_model, recommended_polish_model
from .ai_hardware import detect_ai_hardware
from .models import speech_language_options
from .settings_widgets import format_shortcut


class OnboardingPagesMixin:
    def _page(self, title: str, subtitle: str):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

        page = QScrollArea()
        page.setObjectName("OnboardingPage")
        page.setWidgetResizable(True)
        page.setFrameShape(QScrollArea.NoFrame)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("OnboardingPageContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 32, 36, 24)
        layout.setSpacing(18)
        header = QFrame()
        header.setObjectName("PageHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(20)
        heading_copy = QVBoxLayout()
        heading_copy.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        heading.setWordWrap(True)
        sub = QLabel(subtitle)
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        heading_copy.addWidget(heading)
        heading_copy.addWidget(sub)
        header_layout.addLayout(heading_copy, 1)
        layout.addWidget(header)
        page.setWidget(content)
        return page, layout

    def _note(self, layout, text: str):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

        from .settings_icons import settings_nav_icon

        note = QFrame()
        note.setObjectName("SetupNote")
        row = QHBoxLayout(note)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(10)
        icon = QLabel()
        icon.setObjectName("SetupNoteIcon")
        icon.setPixmap(settings_nav_icon("info", self.palette.accent, 16).pixmap(16, 16))
        copy = QLabel(text)
        copy.setObjectName("SetupNoteText")
        copy.setWordWrap(True)
        row.addWidget(icon, 0, Qt.AlignTop)
        row.addWidget(copy, 1)
        layout.addWidget(note)
        return note

    def _card(self, layout, title: str, subtitle: str = "", *, object_name: str = "SetupCard"):
        from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

        card = QFrame()
        card.setObjectName(object_name)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(12)
        if title:
            label = QLabel(title)
            label.setObjectName("CardTitle")
            card_layout.addWidget(label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            card_layout.addWidget(sub)
        layout.addWidget(card)
        return card_layout

    def _waiting_exercise(
        self,
        layout,
        prefix: str,
        *,
        title: str,
        hint: str,
        result_title: str,
        placeholder: str,
        icon_name: str,
    ):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

        from .settings_icons import settings_nav_icon

        panel = QFrame()
        panel.setObjectName("DictationReadyPanel")
        row = QHBoxLayout(panel)
        row.setContentsMargins(15, 13, 15, 13)
        row.setSpacing(12)
        state_icon = QLabel()
        state_icon.setObjectName("DictationStateIcon")
        state_icon.setAlignment(Qt.AlignCenter)
        state_icon.setFixedSize(36, 36)
        state_icon.setPixmap(settings_nav_icon(icon_name, self.palette.accent, 18).pixmap(18, 18))
        copy = QVBoxLayout()
        copy.setSpacing(2)
        state_title = QLabel(title)
        state_title.setObjectName("DictationStateTitle")
        state_title.setWordWrap(True)
        state_hint = QLabel(hint)
        state_hint.setObjectName("Muted")
        state_hint.setWordWrap(True)
        copy.addWidget(state_title)
        copy.addWidget(state_hint)
        row.addWidget(state_icon, 0, Qt.AlignVCenter)
        row.addLayout(copy, 1)
        layout.addWidget(panel)

        canvas = QFrame()
        canvas.setObjectName("TranscriptCanvas")
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(16, 14, 16, 16)
        canvas_layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(8)
        result_icon = QLabel()
        result_icon.setObjectName("TranscriptStateIcon")
        result_icon.setFixedSize(20, 20)
        result_icon.setPixmap(settings_nav_icon("transcripts", self.palette.muted, 16).pixmap(16, 16))
        heading = QLabel(result_title)
        heading.setObjectName("RowTitle")
        header.addWidget(result_icon)
        header.addWidget(heading)
        header.addStretch(1)
        canvas_layout.addLayout(header)
        result = QLabel(placeholder)
        result.setObjectName("TranscriptText")
        result.setWordWrap(True)
        result.setAccessibleName(result_title)
        canvas_layout.addWidget(result)
        layout.addWidget(canvas)

        setattr(self, f"{prefix}_state_icon", state_icon)
        setattr(self, f"{prefix}_state_title", state_title)
        setattr(self, f"{prefix}_state_hint", state_hint)
        setattr(self, f"{prefix}_result_icon", result_icon)
        setattr(self, f"{prefix}_panel", panel)
        setattr(self, f"{prefix}_canvas", canvas)
        return result

    def _row(self, layout, label: str, description: str, widget):
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

        row_frame = QFrame()
        row_frame.setObjectName("SetupRow")
        row = QHBoxLayout(row_frame)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(18)
        text = QVBoxLayout()
        text.setSpacing(3)
        name = QLabel(label)
        name.setObjectName("RowTitle")
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        desc = QLabel(description)
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        desc.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        widget.setAccessibleName(label)
        widget.setAccessibleDescription(description)
        name.setBuddy(widget)
        text.addWidget(name)
        text.addWidget(desc)
        row.addLayout(text, 1)
        row.addWidget(widget)
        layout.addWidget(row_frame)
        return row

    def _shortcut_chip(self, shortcut: str, accessible_name: str):
        from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

        container = QWidget()
        container.setObjectName("ShortcutChips")
        container.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self._set_shortcut_chip_value(container, shortcut)
        container.setAccessibleName(accessible_name)
        return container

    def _set_shortcut_chip_value(self, container, shortcut: str) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel

        row = container.layout()
        while row.count():
            item = row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        parts = [part.strip() for part in format_shortcut(shortcut).split("+") if part.strip()]
        for index, part in enumerate(parts):
            key = QLabel(part)
            key.setObjectName("ShortcutKeycap")
            key.setAlignment(Qt.AlignCenter)
            row.addWidget(key)
            if index < len(parts) - 1:
                plus = QLabel("+")
                plus.setObjectName("ShortcutSeparator")
                row.addWidget(plus)
        row.addStretch(1)
        container.setAccessibleDescription(format_shortcut(shortcut))

    def _feature(self, layout, title: str, detail: str):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

        from .settings_icons import settings_nav_icon

        feature = QFrame()
        feature.setObjectName("FeatureRow")
        row = QHBoxLayout(feature)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)
        dot = QLabel()
        dot.setObjectName("FeatureMark")
        dot.setAlignment(Qt.AlignCenter)
        dot.setFixedSize(24, 24)
        dot.setPixmap(settings_nav_icon("check", self.palette.accent, 14).pixmap(14, 14))
        copy = QVBoxLayout()
        copy.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("RowTitle")
        body = QLabel(detail)
        body.setObjectName("Muted")
        body.setWordWrap(True)
        copy.addWidget(heading)
        copy.addWidget(body)
        row.addWidget(dot, 0, Qt.AlignTop)
        row.addLayout(copy, 1)
        layout.addWidget(feature)

    def _summary_row(self, layout, label: str):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QHBoxLayout, QLabel

        row = QHBoxLayout()
        row.setSpacing(16)
        name = QLabel(label)
        name.setObjectName("SummaryLabel")
        value = QLabel()
        value.setObjectName("SummaryValue")
        value.setWordWrap(True)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(name)
        row.addWidget(value, 1)
        layout.addLayout(row)
        return value

    def _choice_icon(self, checked: bool):
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

        canvas = QPixmap(22, 22)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(self.palette.accent if checked else self.palette.border), 1.5))
        painter.setBrush(QColor(self.palette.surface))
        painter.drawEllipse(QRectF(2.5, 2.5, 17, 17))
        if checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self.palette.accent))
            painter.drawEllipse(QRectF(6.5, 6.5, 9, 9))
        painter.end()
        return QIcon(canvas)

    def _quality_choice(self, group, choice_id: str, title: str, description: str, *, property_name: str):
        from PySide6.QtCore import QSize, Qt, Signal
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

        class ChoiceFrame(QFrame):
            clicked = Signal()

            def mouseReleaseEvent(self, event):
                if event.button() == Qt.LeftButton and self.isEnabled():
                    self.clicked.emit()
                    event.accept()
                    return
                super().mouseReleaseEvent(event)

        frame = ChoiceFrame()
        frame.setObjectName("QualityChoiceRow")
        frame.setProperty("winsperCursorRole", "button")
        frame.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(12)
        button = QPushButton(title)
        button.setObjectName("QualityChoiceControl")
        button.setCheckable(True)
        button.setProperty(property_name, choice_id)
        button.setIconSize(QSize(22, 22))
        button.setIcon(self._choice_icon(False))
        button.setCursor(Qt.PointingHandCursor)
        button.setAccessibleName(f"{title} quality")
        button.setAccessibleDescription(description)
        detail = QLabel(description)
        detail.setObjectName("QualityChoiceDetail")
        detail.setWordWrap(True)
        detail.setAttribute(Qt.WA_TransparentForMouseEvents)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        copy.addWidget(button)
        copy.addWidget(detail)
        model_row = QHBoxLayout()
        model_row.setSpacing(7)
        model_tick = QLabel()
        model_tick.setObjectName("ModelReadyTick")
        model_tick.setFixedSize(18, 18)
        model_tick.hide()
        model_tick.setAttribute(Qt.WA_TransparentForMouseEvents)
        model_label = QLabel("Checking model…")
        model_label.setObjectName("QualityModelName")
        model_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        model_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        model_row.addWidget(model_tick)
        model_row.addWidget(model_label)
        row.addLayout(copy, 1)
        row.addLayout(model_row)
        group.addButton(button)

        def refresh_selection(checked: bool) -> None:
            frame.setProperty("selected", checked)
            button.setIcon(self._choice_icon(checked))
            frame.style().unpolish(frame)
            frame.style().polish(frame)

        button.toggled.connect(refresh_selection)
        frame.clicked.connect(lambda: button.setChecked(True))
        refresh_selection(False)
        return frame, button, model_label, model_tick

    def _build_speed_page(self):
        from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QPushButton

        page, layout = self._page(
            "Which language do you speak?",
            "Start fast for the quickest first result. You can change quality later.",
        )
        preferences = self._card(
            layout,
            "Language & transcription",
            "Fast is selected for the quickest first experience.",
        )
        for code, label in speech_language_options():
            self.language_combo.addItem(label, code)
        language_index = self.language_combo.findData(self.config.speech.language)
        self.language_combo.setCurrentIndex(language_index if language_index >= 0 else 0)
        self._row(
            preferences,
            "Language",
            "Choose Auto / Mixed if you switch languages while speaking.",
            self.language_combo,
        )
        self.language_combo.currentIndexChanged.connect(lambda *_args: self._refresh_model_status())

        self.speech_quality_models = {}
        for profile in self._speed_profiles():
            frame, button, model_label, model_tick = self._quality_choice(
                self.speed_group,
                profile["id"],
                profile["title"],
                profile["description"],
                property_name="profile_id",
            )
            preferences.addWidget(frame)
            self.speech_quality_models[profile["id"]] = (model_label, model_tick)
            button.toggled.connect(lambda checked: self._refresh_model_status() if checked else None)
            if profile["id"] == self.config.onboarding.quality_profile:
                button.setChecked(True)
        if self.speed_group.checkedButton() is None:
            next(button for button in self.speed_group.buttons() if button.property("profile_id") == "instant").setChecked(True)
        self.model_status.setObjectName("StatusBox")
        self.model_status.setWordWrap(True)
        preferences.addWidget(self.model_status)

        self.model_download_progress = QProgressBar()
        self.model_download_progress.setRange(0, 100)
        self.model_download_progress.setValue(0)
        self.model_download_progress.hide()
        preferences.addWidget(self.model_download_progress)

        download_row = QHBoxLayout()
        download_row.setSpacing(8)
        download = QPushButton("Download speech support")
        download.setObjectName("PrimaryButton")
        download.clicked.connect(self._download_selected_speech_support)
        self.model_download_pause_button = QPushButton("Pause")
        self.model_download_pause_button.setObjectName("DownloadControlButton")
        self.model_download_pause_button.clicked.connect(self._toggle_speech_download_pause)
        self.model_download_cancel_button = QPushButton("Cancel")
        self.model_download_cancel_button.setObjectName("DownloadControlButton")
        self.model_download_cancel_button.clicked.connect(self._cancel_speech_download)
        download_row.addWidget(download)
        download_row.addWidget(self.model_download_pause_button)
        download_row.addWidget(self.model_download_cancel_button)
        download_row.addStretch(1)
        preferences.addLayout(download_row)
        self.model_download_button = download
        self._show_speech_download_controls(False)

        self._refresh_model_status()
        layout.addStretch(1)
        return page

    def _build_dictation_test_page(self):
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

        from .hud_icons import record_icon_pixmap
        from .settings_icons import settings_nav_icon

        page, layout = self._page(
            "Dictate something now.",
            "Set your shortcut, hold it while you speak, then release. The Winsper HUD will appear.",
        )
        shortcut_card = self._card(
            layout,
            "",
        )
        self._row(
            shortcut_card,
            "Dictate shortcut",
            "Hold to speak; release when finished.",
            self.dictate_shortcut_recorder,
        )
        self._row(
            shortcut_card,
            "HUD style",
            "Choose full status details or a minimal recording wave.",
            self.hud_style_combo,
        )
        self.hotkey_check_status.setObjectName("HotkeyCheck")
        self.hotkey_check_status.setWordWrap(True)
        self.hotkey_check_status.clear()
        self.hotkey_check_status.hide()
        shortcut_card.addWidget(self.hotkey_check_status)

        practice = self._card(
            layout,
            "Try Dictate mode",
            "Press and hold this shortcut while you speak, then release it.",
        )
        shortcut_prompt = QFrame()
        shortcut_prompt.setObjectName("ShortcutPracticePrompt")
        shortcut_prompt_row = QHBoxLayout(shortcut_prompt)
        shortcut_prompt_row.setContentsMargins(16, 13, 16, 13)
        shortcut_prompt_row.setSpacing(10)
        shortcut_prompt_icon = QLabel()
        shortcut_prompt_icon.setObjectName("DictatePracticeMic")
        shortcut_prompt_icon.setFixedSize(38, 38)
        shortcut_prompt_icon.setPixmap(record_icon_pixmap(38))
        shortcut_prompt_icon.setAccessibleName("Listening microphone")
        shortcut_prompt_copy = QLabel("Press and hold")
        shortcut_prompt_copy.setObjectName("ShortcutPracticeCopy")
        shortcut_prompt_copy.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        shortcut_prompt_end = QLabel("while you speak, then release")
        shortcut_prompt_end.setObjectName("ShortcutPracticeCopy")
        shortcut_prompt_end.setWordWrap(True)
        shortcut_prompt_end.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        shortcut_prompt_row.addWidget(shortcut_prompt_icon)
        shortcut_prompt_row.addWidget(shortcut_prompt_copy)
        shortcut_prompt_row.addWidget(self.dictation_practice_shortcut_chip)
        shortcut_prompt_row.addWidget(shortcut_prompt_end)
        shortcut_prompt_row.addStretch(1)
        practice.addWidget(shortcut_prompt)

        transcript = QFrame()
        transcript.setObjectName("TranscriptCanvas")
        transcript_layout = QVBoxLayout(transcript)
        transcript_layout.setContentsMargins(16, 14, 16, 16)
        transcript_layout.setSpacing(8)
        transcript_header = QHBoxLayout()
        transcript_header.setSpacing(8)
        self.dictation_transcript_icon = QLabel()
        self.dictation_transcript_icon.setObjectName("TranscriptStateIcon")
        self.dictation_transcript_icon.setFixedSize(20, 20)
        self.dictation_transcript_icon.setPixmap(settings_nav_icon("transcripts", self.palette.muted, 16).pixmap(16, 16))
        transcript_title = QLabel("Your transcription")
        transcript_title.setObjectName("RowTitle")
        transcript_header.addWidget(self.dictation_transcript_icon)
        transcript_header.addWidget(transcript_title)
        transcript_header.addStretch(1)
        transcript_layout.addLayout(transcript_header)
        self.dictation_result.setObjectName("TranscriptText")
        self.dictation_result.setWordWrap(True)
        self.dictation_result.setText("What Winsper hears will appear here.")
        self.dictation_result.setAccessibleName("Dictation transcription result")
        transcript_layout.addWidget(self.dictation_result)
        practice.addWidget(transcript)
        self.dictation_progress = None

        layout.addStretch(1)
        return page

    def _build_polish_page(self):
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtWidgets import (
            QButtonGroup,
            QFrame,
            QHBoxLayout,
            QLabel,
            QProgressBar,
            QPushButton,
            QSizePolicy,
            QTextEdit,
            QToolButton,
            QVBoxLayout,
            QWidget,
        )

        from .app_icons import app_icon
        from .settings_icons import settings_nav_icon

        page, layout = self._page(
            "Add Polish — if you want it.",
            "Clean up rough speech or transform selected text in one shortcut.",
        )
        enable_card = self._card(layout, "")
        self._row(
            enable_card,
            "Enable Polish",
            "Clean up rough speech or transform selected text with one shortcut.",
            self.polish_check,
        )

        disabled = QFrame()
        disabled.setObjectName("PolishDisabledState")
        disabled_layout = QHBoxLayout(disabled)
        disabled_layout.setContentsMargins(16, 14, 16, 14)
        disabled_layout.setSpacing(12)
        disabled_icon = QLabel()
        disabled_icon.setObjectName("PolishDisabledIcon")
        disabled_icon.setAlignment(Qt.AlignCenter)
        disabled_icon.setFixedSize(38, 38)
        disabled_icon.setPixmap(settings_nav_icon("polish", self.palette.accent, 19).pixmap(19, 19))
        self.polish_disabled_icon = disabled_icon
        disabled_title = QLabel("Polish is off")
        disabled_title.setObjectName("PolishDisabledTitle")
        disabled_copy = QLabel("Dictation stays available. Turn on Polish for app-aware cleanup and selected-text edits.")
        disabled_copy.setObjectName("PolishDisabledCopy")
        disabled_copy.setWordWrap(True)
        disabled_copy_layout = QVBoxLayout()
        disabled_copy_layout.setSpacing(2)
        disabled_copy_layout.addWidget(disabled_title)
        disabled_copy_layout.addWidget(disabled_copy)
        disabled_layout.addWidget(disabled_icon, 0, Qt.AlignVCenter)
        disabled_layout.addLayout(disabled_copy_layout, 1)
        layout.addWidget(disabled)
        self.polish_disabled_state = disabled

        self.polish_options_container = QWidget()
        self.polish_options_container.setObjectName("PolishOptions")
        options_layout = QVBoxLayout(self.polish_options_container)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(14)
        layout.addWidget(self.polish_options_container)

        modes = self._card(options_layout, "")

        self._row(
            modes,
            "Polish shortcut",
            "Use this wherever you can type.",
            self.polish_shortcut_recorder,
        )
        self.polish_shortcut_status.setObjectName("HotkeyCheck")
        self.polish_shortcut_status.hide()

        setup_card = self._card(
            options_layout,
            "Polish quality",
            "Choose faster responses or more nuance.",
        )
        hardware = detect_ai_hardware()
        recommended_polish = recommended_polish_model(hardware)
        compatible_ids = {model.id for model in compatible_polish_models(hardware)}
        fast_polish = next(
            (model for model in POLISH_MODELS if model.tier == "fast" and model.id in compatible_ids),
            recommended_polish,
        )
        try:
            configured_polish = polish_model(self.config.rewrite.llama_model_id)
        except KeyError:
            configured_polish = recommended_polish
        selected_model = (
            fast_polish
            if self._is_first_run
            else (
                configured_polish if configured_polish in POLISH_MODELS and configured_polish.id in compatible_ids else recommended_polish
            )
        )
        onboarding_recommended_polish = fast_polish if self._is_first_run else recommended_polish
        self.recommended_polish_model = selected_model
        self.polish_recommended_model_id = onboarding_recommended_polish.id
        self.polish_quality_group = QButtonGroup(self.window)
        self.polish_quality_group.setExclusive(True)
        self.polish_quality_models = {}
        self.polish_quality_choices = QWidget()
        quality_choices_layout = QVBoxLayout(self.polish_quality_choices)
        quality_choices_layout.setContentsMargins(0, 0, 0, 0)
        quality_choices_layout.setSpacing(8)
        tier_copy = {
            "fast": ("Fast", "Fastest response for everyday cleanup."),
            "balanced": ("Balanced", "Stronger everyday Polish with a little more waiting."),
            "quality": ("Best quality", "Largest local model for complex rewrites; slower."),
        }
        for model in POLISH_MODELS:
            title, description = tier_copy[model.tier]
            frame, button, model_label, model_tick = self._quality_choice(
                self.polish_quality_group,
                model.id,
                title,
                description,
                property_name="model_id",
            )
            model_label.setText(f"{model.label} · Recommended" if model.id == onboarding_recommended_polish.id else model.label)
            supported = model.id in compatible_ids
            frame.setProperty("supported", supported)
            button.setEnabled(supported)
            frame.setEnabled(supported)
            if not supported:
                model_label.setText(f"{model.label} · Needs more memory")
            quality_choices_layout.addWidget(frame)
            self.polish_quality_models[model.id] = (model_label, model_tick, frame)
            if model.id == selected_model.id:
                button.setChecked(True)
            button.toggled.connect(lambda checked, selected=model.id: self._select_polish_model(selected) if checked else None)
        setup_card.addWidget(self.polish_quality_choices)
        self.polish_setup_status.setObjectName("StatusBox")
        self.polish_setup_status.setWordWrap(True)
        self.polish_setup_status.setText("")
        setup_card.addWidget(self.polish_setup_status)
        self.polish_setup_progress = QProgressBar()
        self.polish_setup_progress.setRange(0, 100)
        self.polish_setup_progress.setValue(0)
        self.polish_setup_progress.hide()
        self.polish_setup_progress.setAccessibleName("Polish setup progress")
        setup_card.addWidget(self.polish_setup_progress)
        setup_row = QHBoxLayout()
        setup_row.setSpacing(8)
        setup = QPushButton("Download Polish model")
        setup.setObjectName("PrimaryButton")
        setup.clicked.connect(self._start_polish_setup)
        self.polish_setup_pause_button = QPushButton("Pause")
        self.polish_setup_pause_button.setObjectName("DownloadControlButton")
        self.polish_setup_pause_button.clicked.connect(self._toggle_polish_setup_pause)
        self.polish_setup_cancel_button = QPushButton("Cancel")
        self.polish_setup_cancel_button.setObjectName("DownloadControlButton")
        self.polish_setup_cancel_button.clicked.connect(self._cancel_polish_setup)
        setup_row.addWidget(setup)
        setup_row.addWidget(self.polish_setup_pause_button)
        setup_row.addWidget(self.polish_setup_cancel_button)
        setup_row.addStretch(1)
        setup_card.addLayout(setup_row)
        self.polish_setup_button = setup
        self.polish_skip_button = None
        self._show_polish_download_controls(False)

        mode_header = QHBoxLayout()
        mode_header.setSpacing(12)
        self.polish_mode_group = QButtonGroup(self.window)
        self.polish_mode_group.setExclusive(True)
        for mode_id, title, description in (
            (
                "free",
                "Nothing selected — app-aware",
                "Speak naturally. Winsper fixes grammar, fillers, tone, and formatting for the chosen app.",
            ),
            (
                "selected",
                "Text selected",
                "Select text first. Your voice becomes the instruction, and only that selection is transformed.",
            ),
        ):
            button = QPushButton(title)
            button.setObjectName("PolishModeButton")
            button.setCheckable(True)
            button.setProperty("mode_id", mode_id)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            button.setAccessibleName(f"Show {title.lower()} Polish example")
            button.setAccessibleDescription(description)
            button.setIcon(
                settings_nav_icon(
                    "polish" if mode_id == "free" else "edit",
                    self.palette.accent,
                    22,
                )
            )
            button.setIconSize(QSize(22, 22))
            self.polish_mode_group.addButton(button)
            mode_header.addWidget(button, 1)
            if mode_id == "free":
                button.setChecked(True)
        options_layout.addLayout(mode_header)

        free_prompt = self._card(
            options_layout,
            "",
        )
        free_prompt_frame = QFrame()
        free_prompt_frame.setObjectName("ReadAloudPrompt")
        free_prompt_layout = QVBoxLayout(free_prompt_frame)
        free_prompt_layout.setContentsMargins(16, 13, 16, 14)
        free_prompt_layout.setSpacing(6)
        free_prompt_title = QLabel("Read this aloud")
        free_prompt_title.setObjectName("OptionEyebrow")
        self.polish_free_prompt_text = QLabel()
        self.polish_free_prompt_text.setObjectName("TriggerReadAloudText")
        self.polish_free_prompt_text.setWordWrap(True)
        free_prompt_layout.addWidget(free_prompt_title)
        free_prompt_layout.addWidget(self.polish_free_prompt_text)
        free_prompt.addWidget(free_prompt_frame)
        self.polish_app_group = QButtonGroup(self.window)
        self.polish_app_group.setExclusive(True)
        app_row = QHBoxLayout()
        app_row.setContentsMargins(0, 2, 0, 0)
        app_row.setSpacing(8)
        self.polish_app_layout = app_row
        apps = (
            (
                "outlook",
                "Outlook",
                "outlook.exe",
                "email",
                "Um, hey Alex, thanks for sharing the quarterly results. I reviewed them and, uh, everything looks good from my side. Regards, Jordan.",
            ),
            (
                "slack",
                "Slack",
                "slack.exe",
                "chat",
                "Um, hey team, quick update, the checkout fix is done but, like, the tests are still running and I need Alex to review it before release.",
            ),
            (
                "chatgpt",
                "ChatGPT",
                "chatgpt.exe",
                "prompt",
                "Um, compare SQLite and Postgres for a small offline desktop app, include the tradeoffs, recommend one, and, like, keep it under five bullets.",
            ),
            (
                "vscode",
                "VS Code",
                "code.exe",
                "code",
                "Create a JSON object with name as Jordan, plan as Pro, and notifications as true.",
            ),
            (
                "terminal",
                "Windows Terminal",
                "windowsterminal.exe",
                "terminal",
                "CD into Documents.",
            ),
        )
        for index, (app_id, label, process_name, profile_name, spoken_example) in enumerate(apps):
            button = QToolButton()
            button.setObjectName("AppChoice")
            button.setText(label)
            button.setIcon(app_icon(app_id, 28))
            button.setIconSize(QSize(28, 28))
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            button.setProperty("app_label", label)
            button.setProperty("process_name", process_name)
            button.setProperty("profile_name", profile_name)
            button.setProperty("spoken_example", spoken_example)
            button.setAccessibleName(f"Use {label} as the Polish destination")
            self.polish_app_group.addButton(button, index)
            app_row.addWidget(button)
            if index == 0:
                button.setChecked(True)
        app_row.addStretch(1)
        free_prompt.addLayout(app_row)
        self.polish_free_prompt_card = free_prompt.parentWidget()
        self.polish_destinations_card = self.polish_free_prompt_card
        self.polish_free_prompt_text.setText(str(self.polish_app_group.checkedButton().property("spoken_example")))
        self.polish_app_group.buttonClicked.connect(self._on_polish_app_selected)

        demo = self._card(
            options_layout,
            "See the app-aware result",
            "Choose an app above, then read its example with Polish. Winsper adapts the tone and format for that destination.",
        )
        self.polish_test_result = self._waiting_exercise(
            demo,
            "polish_free",
            title="Waiting for your Polish shortcut",
            hint="Choose an app above, then hold Polish and read the sentence.",
            result_title="App-aware polished result",
            placeholder="Your polished words will appear here.",
            icon_name="polish",
        )
        self.polish_free_speech_card = demo.parentWidget()

        selection = self._card(
            options_layout,
            "Transform selected text",
            "Text selected: select the sample, hold Polish, and say what you want changed.",
        )
        self.polish_selection_editor = QTextEdit()
        self.polish_selection_editor.setObjectName("SelectionExercise")
        self.polish_selection_editor.setPlainText(
            "checkout timeout is 30 seconds retries are off dont change the public API security review Thursday release Friday"
        )
        self.polish_selection_editor.setMinimumHeight(82)
        self.polish_selection_editor.setMaximumHeight(112)
        self.polish_selection_editor.setAccessibleName("Text to select and transform")
        selection.addWidget(self.polish_selection_editor)
        selection_hint = QLabel(
            "Try saying: “Turn this into a clear release checklist with bullet points. Keep every deadline and constraint.”"
        )
        selection_hint.setObjectName("Tiny")
        selection_hint.setWordWrap(True)
        selection.addWidget(selection_hint)
        self.polish_selection_result = self._waiting_exercise(
            selection,
            "polish_selected",
            title="Waiting for a text selection",
            hint="Select the sample, then hold Polish and speak your instruction.",
            result_title="Transformed text",
            placeholder="Your transformed selection will appear here.",
            icon_name="edit",
        )
        self.polish_selected_text_card = selection.parentWidget()
        self.polish_mode_group.buttonClicked.connect(self._on_polish_mode_selected)
        self.polish_check.toggled.connect(self._on_polish_enabled_changed)
        self._on_polish_mode_selected(self.polish_mode_group.checkedButton())
        self._on_polish_enabled_changed(self.polish_check.isChecked())
        self._refresh_polish_setup_status()
        layout.addStretch(1)
        return page

    def _build_triggers_page(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

        page, layout = self._page(
            "Try voice triggers — or skip this lesson.",
            "Practice two useful phrases with your real Dictate shortcut.",
        )
        shortcut = self._card(
            layout,
            "Use your Dictate shortcut",
            "Hold to speak; release when finished.",
        )
        self.trigger_shortcut_chip = self._shortcut_chip(
            self.dictate_shortcut_recorder.value(),
            "Dictate shortcut for voice trigger practice",
        )
        shortcut.addWidget(self.trigger_shortcut_chip)

        formatting = self._card(
            layout,
            "Format while you speak",
            "Read the sentence exactly as shown. Spoken formatting words become layout and actions.",
        )
        prompt = QFrame()
        prompt.setObjectName("ReadAloudPrompt")
        prompt_layout = QVBoxLayout(prompt)
        prompt_layout.setContentsMargins(16, 13, 16, 14)
        prompt_layout.setSpacing(6)
        prompt_title = QLabel("Read this aloud")
        prompt_title.setObjectName("OptionEyebrow")
        prompt_text = QLabel("Project update new line Design is approved new paragraph Engineering starts Monday press enter")
        prompt_text.setObjectName("TriggerReadAloudText")
        prompt_text.setWordWrap(True)
        prompt_layout.addWidget(prompt_title)
        prompt_layout.addWidget(prompt_text)
        formatting.addWidget(prompt)
        self.trigger_format_result = self._waiting_exercise(
            formatting,
            "trigger_format",
            title="Waiting for your Dictate shortcut",
            hint="Hold Dictate, read the sentence above, then release.",
            result_title="Formatted result",
            placeholder="Your line break, paragraph break, and Enter action will appear here.",
            icon_name="shortcuts",
        )
        self.trigger_format_card = formatting.parentWidget()
        self.trigger_format_card.setProperty("taskComplete", False)
        self.trigger_format_card.setProperty("activeTask", True)
        self.trigger_format_panel.setFocusPolicy(Qt.StrongFocus)
        self.trigger_format_card.setFocusProxy(self.trigger_format_panel)

        date = self._card(
            layout,
            "Insert today's date",
            "After the formatting test passes, hold Dictate and say “today's date”.",
        )
        self.trigger_date_result = self._waiting_exercise(
            date,
            "trigger_date",
            title="Complete the formatting test first",
            hint="This exercise unlocks after Winsper recognizes a formatting trigger.",
            result_title="Date result",
            placeholder="Today's date will appear here.",
            icon_name="shortcuts",
        )
        self.trigger_date_card = date.parentWidget()
        self.trigger_date_card.setProperty("taskComplete", False)
        self.trigger_date_card.setProperty("activeTask", False)
        self.trigger_date_panel.setFocusPolicy(Qt.StrongFocus)
        self.trigger_date_card.setFocusProxy(self.trigger_date_panel)
        self.trigger_date_card.hide()
        self.trigger_test_stage = "formatting"
        self.trigger_test_result = self.trigger_format_result
        layout.addStretch(1)
        return page

    def _speed_profiles(self) -> list[dict[str, str]]:
        return [
            {
                "id": "instant",
                "title": "Fast",
                "description": "Quickest response for everyday dictation.",
                "models": "",
            },
            {
                "id": "balanced",
                "title": "Balanced",
                "description": "The best fit for most people.",
                "models": "",
            },
            {
                "id": "precise",
                "title": "Best quality",
                "description": "More accuracy, with a little more waiting.",
                "models": "",
            },
        ]
