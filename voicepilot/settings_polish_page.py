from __future__ import annotations


from .ai_catalog import polish_model
from .ai_runtime import model_is_installed
from .hotkeys import validate_hotkey_bindings


class SettingsPolishPageMixin:
    def _build_polish_consumer_page(self):
        from PySide6.QtCore import QSignalBlocker, Qt
        from PySide6.QtWidgets import (
            QButtonGroup,
            QFrame,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QSizePolicy,
            QVBoxLayout,
        )

        page, layout = self._page(
            "Polish",
            "Clean up what you say, or transform selected text with a spoken request.",
        )

        status = QFrame()
        status.setObjectName("PolishStatusCard")
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(20, 17, 20, 17)
        status_layout.setSpacing(14)
        status_copy = QVBoxLayout()
        status_copy.setSpacing(3)
        status_title = QLabel("Polish")
        status_title.setObjectName("PolishStatusTitle")
        status_detail = QLabel("Private, local writing assistance whenever you need it.")
        status_detail.setObjectName("Muted")
        status_copy.addWidget(status_title)
        status_copy.addWidget(status_detail)
        local_badge = QLabel("Local")
        local_badge.setObjectName("LocalBadge")
        local_badge.setAccessibleName("Local Polish processing")
        local_badge.setToolTip("Polish processing stays on this device.")
        enabled = self._check("dictation.polish_enabled", self.config.dictation.polish_enabled)
        enabled.setAccessibleName("Enable Polish")
        enabled.setAccessibleDescription("Make the Polish shortcut available.")
        status_layout.addLayout(status_copy, 1)
        status_layout.addWidget(local_badge, 0, Qt.AlignVCenter)
        status_layout.addWidget(enabled, 0, Qt.AlignVCenter)
        layout.addWidget(status)

        def refresh_status_copy(is_enabled: bool) -> None:
            status_detail.setText(
                "Private, local writing assistance whenever you need it." if is_enabled else "Turn it on to use the Polish shortcut."
            )

        enabled.toggled.connect(refresh_status_copy)
        refresh_status_copy(enabled.isChecked())

        modes_title = QLabel("Two ways to Polish")
        modes_title.setObjectName("CardTitle")
        layout.addWidget(modes_title)

        modes = QHBoxLayout()
        modes.setSpacing(12)
        for eyebrow, title, description in (
            (
                "NOTHING SELECTED",
                "Clean up what you say",
                "Removes fillers, fixes grammar and punctuation, and keeps your meaning.",
            ),
            (
                "TEXT SELECTED",
                "Ask for any change",
                "Your voice becomes the instruction. Only the selected text is replaced.",
            ),
        ):
            panel = QFrame()
            panel.setObjectName("PolishModePanel")
            panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(17, 15, 17, 15)
            panel_layout.setSpacing(5)
            mode_eyebrow = QLabel(eyebrow)
            mode_eyebrow.setObjectName("PolishModeEyebrow")
            heading = QLabel(title)
            heading.setObjectName("PolishModeTitle")
            detail = QLabel(description)
            detail.setObjectName("PolishModeDetail")
            detail.setWordWrap(True)
            panel_layout.addWidget(mode_eyebrow)
            panel_layout.addWidget(heading)
            panel_layout.addWidget(detail)
            modes.addWidget(panel, 1)
        layout.addLayout(modes)

        from .app_icons import app_icon

        app_awareness = QFrame()
        app_awareness.setObjectName("PolishAppAwareness")
        app_awareness.setAccessibleName("App-aware Polish examples")
        app_layout = QHBoxLayout(app_awareness)
        app_layout.setContentsMargins(16, 11, 16, 11)
        app_layout.setSpacing(12)
        app_copy = QVBoxLayout()
        app_copy.setSpacing(2)
        app_title = QLabel("Adapts to where you write")
        app_title.setObjectName("PolishAppTitle")
        app_detail = QLabel("Tone and format follow the active app.")
        app_detail.setObjectName("PolishAppDetail")
        app_copy.addWidget(app_title)
        app_copy.addWidget(app_detail)
        app_layout.addLayout(app_copy, 1)
        for app_id, label in (
            ("outlook", "Outlook"),
            ("slack", "Slack"),
            ("chatgpt", "ChatGPT"),
            ("vscode", "VS Code"),
            ("terminal", "Windows Terminal"),
        ):
            mark = QLabel()
            mark.setObjectName("PolishAppMark")
            mark.setAccessibleName(label)
            mark.setToolTip(label)
            mark.setPixmap(app_icon(app_id, 24).pixmap(24, 24))
            mark.setFixedSize(30, 30)
            mark.setAlignment(Qt.AlignCenter)
            app_layout.addWidget(mark, 0, Qt.AlignVCenter)
        layout.addWidget(app_awareness)

        controls = QFrame()
        controls.setObjectName("PolishControlsCard")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(18, 10, 18, 10)
        controls_layout.setSpacing(0)
        polish_shortcut = self._shortcut("hotkeys.polish", self.config.hotkeys.polish)
        self._simple_row(
            controls_layout,
            "Polish shortcut",
            "Hold to speak, then release to improve or transform text.",
            polish_shortcut,
            compact=True,
        )
        self._simple_row(
            controls_layout,
            "Review selected-text changes",
            "Preview the original and improved text before replacing a selection.",
            self._check("rewrite.preview_before_apply", self.config.rewrite.preview_before_apply),
            compact=True,
        )

        layout.addWidget(controls)

        quality_panel = QFrame()
        quality_panel.setObjectName("DictationPanel")
        quality_layout = QVBoxLayout(quality_panel)
        quality_layout.setContentsMargins(20, 14, 20, 14)
        quality_layout.setSpacing(8)
        quality_header = QHBoxLayout()
        quality_header.setContentsMargins(0, 0, 0, 0)
        quality_header.setSpacing(12)
        quality_title = QLabel("Polish quality")
        quality_title.setObjectName("DictationPanelTitle")
        quality_header.addWidget(quality_title)
        quality_header.addStretch(1)
        configure = QPushButton("Advanced")
        configure.setObjectName("QualityAdvancedButton")
        configure.setAccessibleName("Manage Polish models")
        configure.setAccessibleDescription("Open advanced model, download, and acceleration controls for Polish.")
        configure.clicked.connect(self._open_advanced_polish_ai)
        quality_header.addWidget(configure)
        quality_layout.addLayout(quality_header)

        quality_selector = QFrame()
        quality_selector.setObjectName("QualitySelector")
        selector_layout = QHBoxLayout(quality_selector)
        selector_layout.setContentsMargins(4, 4, 4, 4)
        selector_layout.setSpacing(4)
        quality_group = QButtonGroup(quality_selector)
        quality_group.setExclusive(True)
        quality_models = {
            "Fast": "qwen2.5-1.5b-q4km",
            "Balanced": "qwen3-4b-instruct-2507-q4km",
            "Best quality": "qwen3-8b-q4km",
        }
        quality_buttons: dict[str, QPushButton] = {}
        for label, model_id in quality_models.items():
            button = QPushButton(label)
            button.setObjectName("PolishQualityOption")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            quality_group.addButton(button)
            selector_layout.addWidget(button, 1)
            quality_buttons[model_id] = button
        custom_quality = QPushButton("Custom")
        custom_quality.setObjectName("PolishQualityOption")
        custom_quality.setCheckable(True)
        custom_quality.setProperty("winsperCursorRole", "arrow")
        custom_quality.setCursor(Qt.ArrowCursor)
        custom_quality.setFocusPolicy(Qt.NoFocus)
        custom_quality.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        custom_quality.setAccessibleDescription("Read-only status for a Polish model selected in Advanced settings.")
        quality_group.addButton(custom_quality)
        selector_layout.addWidget(custom_quality, 1)
        quality_layout.addWidget(quality_selector)

        quality_summary = QLabel()
        quality_summary.setObjectName("QualitySummary")
        quality_summary.setWordWrap(True)
        quality_layout.addWidget(quality_summary)
        layout.addWidget(quality_panel)

        def refresh_polish_quality() -> None:
            provider = self.config.rewrite.provider
            custom_path = self.config.rewrite.llama_model_path.strip()
            selected_id = self.config.rewrite.llama_model_id
            custom_selected = provider != "embedded" or bool(custom_path) or selected_id not in quality_buttons
            for model_id, button in quality_buttons.items():
                button.setEnabled(True)
                button.setChecked(not custom_selected and model_id == selected_id)
            custom_quality.setChecked(custom_selected)
            if provider == "ollama":
                quality_summary.setText("Custom engine selected in Advanced. Choose a preset above to use Winsper embedded.")
            elif custom_path:
                quality_summary.setText("Custom local model selected in Advanced. Choose a preset above to replace it.")
            elif custom_selected:
                quality_summary.setText("Custom model selected in Advanced. Choose a preset above to replace it.")
            else:
                try:
                    model = polish_model(selected_id)
                    description = {
                        "fast": "Fastest response with a lighter local model.",
                        "balanced": "Recommended — strong everyday Polish without the longest wait.",
                        "quality": "Highest local quality; best suited to faster PCs.",
                    }.get(model.tier, "Selected local Polish model.")
                    quality_summary.setText(f"{description} - {model.label}")
                except KeyError:
                    quality_summary.setText("Custom local model selected in Advanced.")
            quality_summary.setProperty("recommended", False)
            quality_summary.style().unpolish(quality_summary)
            quality_summary.style().polish(quality_summary)

        def select_polish_quality(model_id: str) -> None:
            model = polish_model(model_id)
            if not model_is_installed(model):
                self._pending_polish_selection = (
                    self.config.rewrite.provider,
                    self.config.rewrite.llama_model_id,
                    self.config.rewrite.llama_model_path,
                    model_id,
                )
                self._open_advanced_polish_ai()
                provider_widget = self.widgets.get("rewrite.provider")
                advanced_model = self.widgets.get("rewrite.llama_model_id")
                path_widget = self.widgets.get("rewrite.llama_model_path")
                staged = [widget for widget in (provider_widget, advanced_model, path_widget) if widget is not None]
                blockers = [QSignalBlocker(widget) for widget in staged]
                if provider_widget is not None and hasattr(provider_widget, "setCurrentText"):
                    provider_widget.setCurrentText("embedded")
                if advanced_model is not None and hasattr(advanced_model, "setCurrentText"):
                    advanced_model.setCurrentText(model_id)
                if path_widget is not None and hasattr(path_widget, "setText"):
                    path_widget.setText("")
                del blockers
                refresh_setup = getattr(self, "_refresh_polish_model_setup", None)
                if callable(refresh_setup):
                    refresh_setup()
                self.status.setText(f"{model.label} needs a one-time download.")
                refresh_polish_quality()
                return
            self._pending_polish_selection = None
            self.config.rewrite.provider = "embedded"
            self.config.rewrite.llama_model_id = model_id
            self.config.rewrite.llama_model_path = ""
            provider_widget = self.widgets.get("rewrite.provider")
            if provider_widget is not None and hasattr(provider_widget, "setCurrentText"):
                provider_widget.setCurrentText("embedded")
            model_widget = self.widgets.get("rewrite.llama_model_id")
            if model_widget is not None and hasattr(model_widget, "setCurrentText"):
                model_widget.setCurrentText(model_id)
            path_widget = self.widgets.get("rewrite.llama_model_path")
            if path_widget is not None and hasattr(path_widget, "setText"):
                path_widget.setText("")
            self._save(silent=True)
            refresh_polish_quality()

        for model_id, button in quality_buttons.items():
            button.clicked.connect(lambda _checked=False, selected=model_id: select_polish_quality(selected))
        self._refresh_polish_quality = refresh_polish_quality
        refresh_polish_quality()

        shortcut_validation = QLabel()
        shortcut_validation.setObjectName("InlineNotice")
        shortcut_validation.setWordWrap(True)
        shortcut_validation.hide()
        layout.addWidget(shortcut_validation)

        def refresh_shortcut_validation() -> None:
            errors = validate_hotkey_bindings(
                self.config.hotkeys.dictate,
                polish_shortcut.value(),
                self.config.hotkeys.cancel,
            )
            shortcut_validation.setVisible(bool(errors))
            shortcut_validation.setText(errors[0] if errors else "")
            self._set_tone(shortcut_validation, "bad" if errors else "neutral")

        polish_shortcut.shortcutChanged.connect(lambda _value: refresh_shortcut_validation())
        refresh_shortcut_validation()

        layout.addStretch(1)
        return page
