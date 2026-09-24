from __future__ import annotations

from copy import deepcopy

from .hotkeys import validate_hotkey_bindings
from .models import (
    detect_hardware,
    engine_runtime_available,
    find_speech_model,
    installed_status,
    model_supports_language,
    recommended_model_for_language,
    speech_language_options,
)
from .speed_lab import apply_speed_profile
from .speech_languages import fast_dictation_supported
from .settings_microphone import build_microphone_selector
from .settings_widgets import create_settings_combo
from .system_audio import list_audio_devices


class SettingsDictationPageMixin:
    def _build_voice_page(self):
        from PySide6.QtCore import QEvent, QObject, Qt
        from PySide6.QtWidgets import (
            QButtonGroup,
            QComboBox,
            QFrame,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QVBoxLayout,
        )

        page, layout = self._page("Dictation", "Choose how Winsper hears and writes your voice.")

        voice_panel = QFrame()
        voice_panel.setObjectName("DictationPanel")
        voice_layout = QVBoxLayout(voice_panel)
        voice_layout.setContentsMargins(20, 14, 20, 10)
        voice_layout.setSpacing(0)
        voice_header = QHBoxLayout()
        voice_title = QLabel("Voice setup")
        voice_title.setObjectName("DictationPanelTitle")
        local_badge = QLabel("Local")
        local_badge.setObjectName("LocalBadge")
        local_badge.setAccessibleName("Local speech processing")
        local_badge.setToolTip("Speech processing stays on this device.")
        voice_header.addWidget(voice_title)
        voice_header.addStretch(1)
        voice_header.addWidget(local_badge)
        voice_layout.addLayout(voice_header)

        build_microphone_selector(self, page, voice_layout, list_audio_devices)

        language_combo = create_settings_combo(
            lambda: self.palette,
            accessible_name="Dictation language",
        )
        language_combo.setEditable(True)
        language_combo.setInsertPolicy(QComboBox.NoInsert)
        for code, label in speech_language_options():
            language_combo.addItem(label, code)
        index = language_combo.findData(self.config.speech.language)
        language_combo.setCurrentIndex(index if index >= 0 else 0)
        if language_combo.completer() is not None:
            language_combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
            language_combo.completer().setFilterMode(Qt.MatchContains)
        self.dictation_language_combo = language_combo
        self._simple_row(
            voice_layout,
            "Language",
            "Choose Auto / Mixed if you switch languages while speaking.",
            language_combo,
            last=True,
            compact=True,
        )

        layout.addWidget(voice_panel)

        pending_setup: dict[str, str] = {}

        def preset_ready(preset) -> bool:
            return bool(
                preset is not None and installed_status(preset, include_size=False).installed and engine_runtime_available(preset.engine)
            )

        def selected_language_setup():
            code = str(language_combo.currentData() or "")
            current = find_speech_model(self.config.dictation.ramble_model)
            if code != self.config.speech.language and preset_ready(current) and model_supports_language(current, code):
                return code, current
            preset = recommended_model_for_language(code, detect_hardware())
            return code, preset

        def current_model_supports(language: str) -> bool:
            current = find_speech_model(self.config.dictation.ramble_model)
            return bool(current is not None and preset_ready(current) and model_supports_language(current, language))

        def remember_setup(language: str, preset, profile: str = "") -> None:
            pending_setup.clear()
            pending_setup.update(
                language=language,
                model=preset.model,
                profile=profile,
            )
            self._pending_dictation_language = language
            self._pending_dictation_model = preset.model

        def refresh_language_action() -> None:
            selected_code = str(language_combo.currentData() or "")
            changed = selected_code != self.config.speech.language
            if not changed:
                if pending_setup.get("profile") != "custom":
                    pending_setup.clear()
                return
            code, preset = selected_language_setup()
            if preset_ready(preset):
                pending_setup.clear()
            else:
                remember_setup(code, preset)

        def apply_selected_language_if_ready() -> None:
            code, preset = selected_language_setup()
            if code != self.config.speech.language and preset_ready(preset):
                if current_model_supports(code):
                    # A language change must not silently replace a compatible
                    # custom model or reset its chosen device/precision.
                    self.config.speech.language = code
                    self._sync_model_widgets()
                    self._save(silent=True)
                    self.status.setText(f"{preset.label} remains selected for {language_combo.currentText()}.")
                else:
                    self._apply_language_model(code, preset.model)
            refresh_language_action()
            refresh_quality()

        quality_panel = QFrame()
        quality_panel.setObjectName("DictationPanel")
        quality_layout = QVBoxLayout(quality_panel)
        quality_layout.setContentsMargins(20, 14, 20, 14)
        quality_layout.setSpacing(8)
        quality_header = QHBoxLayout()
        quality_header.setContentsMargins(0, 0, 0, 0)
        quality_header.setSpacing(12)
        quality_title = QLabel("Transcription quality")
        quality_title.setObjectName("DictationPanelTitle")
        quality_header.addWidget(quality_title)
        quality_header.addStretch(1)
        advanced_models = QPushButton("Advanced")
        advanced_models.setObjectName("QualityAdvancedButton")
        advanced_models.setAccessibleName("Manage Dictation models")
        advanced_models.setAccessibleDescription("Open advanced language, speech model, download, and acceleration controls for Dictation.")
        advanced_models.clicked.connect(self._open_advanced_models)
        quality_header.addWidget(advanced_models)
        quality_layout.addLayout(quality_header)

        quality_selector = QFrame()
        quality_selector.setObjectName("QualitySelector")
        quality_buttons = QHBoxLayout(quality_selector)
        quality_buttons.setContentsMargins(4, 4, 4, 4)
        quality_buttons.setSpacing(4)
        quality_group = QButtonGroup(quality_selector)
        quality_group.setExclusive(True)

        class QualityAvailabilityFilter(QObject):
            """Block activation while preserving hover/cursor feedback."""

            def eventFilter(self, watched, event) -> bool:
                if watched.property("unavailable") and event.type() in {
                    QEvent.MouseButtonPress,
                    QEvent.MouseButtonRelease,
                    QEvent.KeyPress,
                    QEvent.KeyRelease,
                }:
                    event.accept()
                    return True
                return super().eventFilter(watched, event)

        availability_filter = QualityAvailabilityFilter(quality_selector)
        buttons: dict[str, QPushButton] = {}
        for label, profile in (("Fast", "instant"), ("Balanced", "balanced"), ("Best quality", "precise")):
            button = QPushButton(label)
            button.setObjectName("QualityOption")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.installEventFilter(availability_filter)
            buttons[profile] = button
            quality_group.addButton(button)
            quality_buttons.addWidget(button, 1)
        custom_quality = QPushButton("Custom")
        custom_quality.setObjectName("QualityOption")
        custom_quality.setCheckable(True)
        custom_quality.setProperty("winsperCursorRole", "arrow")
        custom_quality.setCursor(Qt.ArrowCursor)
        custom_quality.setFocusPolicy(Qt.NoFocus)
        custom_quality.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        custom_quality.setAccessibleDescription("Read-only status for a model selected in Advanced Dictation settings.")
        quality_group.addButton(custom_quality)
        quality_buttons.addWidget(custom_quality, 1)
        quality_layout.addWidget(quality_selector)

        quality_state = QLabel()
        quality_state.setObjectName("QualitySummary")
        quality_state.setWordWrap(True)
        quality_layout.addWidget(quality_state)
        layout.addWidget(quality_panel)

        def candidate_for_quality(
            profile: str,
            *,
            latest=None,
            acceleration_ready: bool | None = None,
        ):
            candidate = deepcopy(self.config)
            candidate.speech.language = str(language_combo.currentData() or "")
            apply_speed_profile(
                candidate,
                profile,
                self.speed_store.latest_by_model() if latest is None else latest,
                acceleration_ready=acceleration_ready,
            )
            return candidate, find_speech_model(candidate.speech.model)

        def dictation_signature(config) -> tuple[str, ...]:
            return (
                str(config.speech.language).casefold(),
                str(config.speech.engine).casefold(),
                str(config.speech.model).casefold(),
                str(config.speech.device).casefold(),
                str(config.speech.compute_type).casefold(),
                str(config.dictation.ramble_model).casefold(),
            )

        def apply_dictation_candidate(candidate) -> None:
            self.config.speech.language = candidate.speech.language
            self.config.speech.engine = candidate.speech.engine
            self.config.speech.model = candidate.speech.model
            self.config.speech.device = candidate.speech.device
            self.config.speech.compute_type = candidate.speech.compute_type
            self.config.speech.preload_on_startup = candidate.speech.preload_on_startup
            self.config.dictation.ramble_model = candidate.dictation.ramble_model
            self.config.dictation.quality_profile = candidate.dictation.quality_profile
            self._sync_model_widgets()
            self._save(silent=True)

        def refresh_quality() -> None:
            current_signature = dictation_signature(self.config)
            explicit_profile = str(self.config.dictation.quality_profile).casefold()
            latest = self.speed_store.latest_by_model()
            current_acceleration = self.config.speech.device.casefold() == "cuda"
            selected_profile = "custom"
            if explicit_profile != "custom":
                selected_profile = next(
                    (
                        profile
                        for profile in ("instant", "balanced", "precise")
                        if dictation_signature(
                            candidate_for_quality(
                                profile,
                                latest=latest,
                                acceleration_ready=current_acceleration,
                            )[0]
                        )
                        == current_signature
                    ),
                    explicit_profile or "custom",
                )
            if selected_profile == "custom" and str(self.config.dictation.ramble_model).casefold() in {"tiny", "tiny.en"}:
                # Older/manual Tiny selections are still the Fast tier even
                # when the current benchmark-derived Fast candidate is Base.
                selected_profile = "instant"
            pending_code = str(language_combo.currentData() or "")
            fast_available = fast_dictation_supported(pending_code)
            fast_button = buttons["instant"]
            # Keep an unavailable option mouse-aware so Windows can display a
            # forbidden cursor. A disabled Qt button inherits its parent's
            # cursor and cannot provide that feedback reliably.
            fast_button.setEnabled(True)
            fast_button.setProperty("unavailable", not fast_available)
            fast_button.setProperty(
                "winsperCursorRole",
                "" if fast_available else "forbidden",
            )
            if fast_available and quality_group.id(fast_button) == -1:
                quality_group.addButton(fast_button)
            elif not fast_available and quality_group.id(fast_button) != -1:
                # An unavailable option remains enabled only to receive the
                # forbidden cursor. Removing it from the exclusive group keeps
                # a click from clearing the valid selected profile.
                quality_group.removeButton(fast_button)
            fast_button.setFocusPolicy(Qt.StrongFocus if fast_available else Qt.NoFocus)
            fast_button.setCursor(Qt.PointingHandCursor if fast_available else Qt.ForbiddenCursor)
            fast_button.setToolTip("" if fast_available else "Fast is not available for this language.")
            fast_button.setAccessibleDescription("" if fast_available else "Unavailable for the selected language.")
            fast_button.style().unpolish(fast_button)
            fast_button.style().polish(fast_button)
            compatibility_message = ""
            if selected_profile == "instant" and not fast_available:
                selected_profile = "balanced"
                compatibility_message = (
                    f"Fast is not available for {language_combo.currentText()}. {buttons[selected_profile].text()} will be used."
                )
            current_model = find_speech_model(self.config.dictation.ramble_model)
            displayed_profile = selected_profile
            for profile, button in buttons.items():
                button.setChecked(profile == displayed_profile)
            custom_model = current_model
            custom_quality.setText(
                f"Custom · {custom_model.label}"
                if custom_model is not None and displayed_profile == "custom"
                else "Custom"
            )
            custom_quality.show()
            custom_quality.setChecked(displayed_profile == "custom")
            description = (
                compatibility_message
                or {
                    "instant": "Fastest response with a lighter local speech model.",
                    "balanced": "Recommended — strong accuracy without slowing everyday dictation.",
                    "precise": "Highest local accuracy; best suited to faster PCs.",
                    "custom": "Selected in Advanced. Choose a preset above to replace it.",
                }[selected_profile]
            )
            model_name = current_model.label if current_model is not None else self.config.dictation.ramble_model
            quality_state.setText(f"{description} - {model_name}" if model_name else description)
            quality_state.setProperty(
                "recommended",
                not compatibility_message and selected_profile == "balanced",
            )
            quality_state.style().unpolish(quality_state)
            quality_state.style().polish(quality_state)

        def apply_quality(profile: str) -> None:
            pending_code = str(language_combo.currentData() or "")
            if profile == "instant" and not fast_dictation_supported(pending_code):
                refresh_quality()
                return
            candidate, preset = candidate_for_quality(profile)
            candidate.dictation.quality_profile = profile
            if not preset_ready(preset):
                if preset is not None:
                    remember_setup(pending_code, preset, profile)
                    self._open_advanced_models()
                else:
                    self.status.setText("This quality option is not available in this build.")
                refresh_quality()
                return
            self.config.speech.language = pending_code
            apply_dictation_candidate(candidate)
            pending_setup.clear()
            refresh_language_action()
            refresh_quality()

        def request_advanced_model_setup(language: str, model: str) -> None:
            preset = find_speech_model(model)
            if preset is None:
                return
            remember_setup(language, preset, "custom")
            refresh_quality()

        def clear_advanced_model_setup() -> None:
            pending_setup.clear()
            self._pending_dictation_language = None
            self._pending_dictation_model = None
            refresh_quality()

        self._request_dictation_model_setup = request_advanced_model_setup
        self._clear_dictation_model_setup = clear_advanced_model_setup

        for profile, button in buttons.items():
            button.clicked.connect(lambda _checked=False, value=profile: apply_quality(value))

        def refresh_language_selection() -> None:
            refresh_language_action()
            refresh_quality()

        self._refresh_dictation_consumer_state = refresh_language_selection
        language_combo.currentIndexChanged.connect(apply_selected_language_if_ready)
        refresh_language_selection()

        shortcut_panel = QFrame()
        shortcut_panel.setObjectName("DictationShortcutPanel")
        shortcut_layout = QVBoxLayout(shortcut_panel)
        shortcut_layout.setContentsMargins(20, 14, 20, 10)
        shortcut_layout.setSpacing(0)
        shortcut_title = QLabel("Shortcuts")
        shortcut_title.setObjectName("DictationPanelTitle")
        shortcut_layout.addWidget(shortcut_title)

        dictate_shortcut = self._shortcut("hotkeys.dictate", self.config.hotkeys.dictate)
        cancel_shortcut = self._shortcut("hotkeys.cancel", self.config.hotkeys.cancel)
        tap_toggle = self._check(
            "hotkeys.tap_to_toggle_dictation",
            self.config.hotkeys.tap_to_toggle_dictation,
        )
        self._simple_row(
            shortcut_layout,
            "Dictate",
            "Hold to speak, then release to insert.",
            dictate_shortcut,
            compact=True,
        )
        self._simple_row(
            shortcut_layout,
            "Cancel",
            "Stop the current recording or Dictation result.",
            cancel_shortcut,
            compact=True,
        )
        self._simple_row(
            shortcut_layout,
            "Tap to keep listening",
            "Tap Dictate once for hands-free listening, then tap again to finish.",
            tap_toggle,
            compact=True,
        )
        self._simple_row(
            shortcut_layout,
            "Spoken formatting",
            'Say "new line", "new paragraph", or "insert tab" while dictating.',
            self._check("spoken_formatting.enabled", self.config.spoken_formatting.enabled),
            last=True,
            compact=True,
        )

        shortcut_validation = QLabel()
        shortcut_validation.setObjectName("InlineNotice")
        shortcut_validation.setWordWrap(True)
        shortcut_validation.hide()
        shortcut_layout.addWidget(shortcut_validation)

        def refresh_shortcut_validation() -> None:
            errors = validate_hotkey_bindings(
                dictate_shortcut.value(),
                self.config.hotkeys.polish,
                cancel_shortcut.value(),
            )
            shortcut_validation.setVisible(bool(errors))
            shortcut_validation.setText(errors[0] if errors else "")
            self._set_tone(shortcut_validation, "bad" if errors else "neutral")

        dictate_shortcut.shortcutChanged.connect(lambda _value: refresh_shortcut_validation())
        cancel_shortcut.shortcutChanged.connect(lambda _value: refresh_shortcut_validation())
        refresh_shortcut_validation()
        layout.addWidget(shortcut_panel)

        layout.addStretch(1)
        return page
