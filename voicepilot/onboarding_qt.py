from __future__ import annotations

import queue
import sys
import threading
from copy import deepcopy
from pathlib import Path

from .audio import AudioRecorder
from .autostart import is_start_with_windows_enabled, set_start_with_windows
from .branding import qt_window_icon, set_windows_app_user_model_id
from .config import AppConfig, load_config, save_config
from .corrections import CorrectionStore
from .models import detect_hardware, find_speech_model, recommended_model_for_hardware
from .speech_runtime import nvidia_acceleration_ready
from .speed_lab import apply_speed_profile as apply_intent_profile
from .theme import get_palette
from .windows_ui import apply_native_window_style

from .onboarding_downloads import OnboardingDownloadsMixin
from .onboarding_flow import OnboardingFlowMixin
from .onboarding_finish_page import OnboardingFinishPageMixin
from .onboarding_pages import OnboardingPagesMixin
from .onboarding_shortcuts import OnboardingShortcutsMixin
from .onboarding_tests import OnboardingTestsMixin
from .onboarding_helpers import ONBOARDING_VERSION, _utc_now, friendly_setup_error


def run_onboarding_wizard(config_path: Path, auto_close_seconds: float | None = None) -> bool:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Winsper")
    wizard = OnboardingWindow(config_path)
    wizard.show()
    if auto_close_seconds is not None:
        QTimer.singleShot(int(auto_close_seconds * 1000), wizard.close)
    app.exec()
    return wizard.completed


class OnboardingWindow(
    OnboardingFlowMixin,
    OnboardingFinishPageMixin,
    OnboardingDownloadsMixin,
    OnboardingPagesMixin,
    OnboardingShortcutsMixin,
    OnboardingTestsMixin,
):
    def __init__(self, config_path: Path) -> None:
        from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
        from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QPixmap
        from PySide6.QtWidgets import (
            QApplication,
            QButtonGroup,
            QCheckBox,
            QFrame,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QProgressBar,
            QPushButton,
            QStackedWidget,
            QToolButton,
            QVBoxLayout,
            QWidget,
        )

        self.config_path = config_path
        self.config = load_config(config_path)
        self._is_first_run = not self.config.onboarding.completed and not self.config.onboarding.started_at
        self._polish_provider_changed = False
        if self._is_first_run:
            self.config.onboarding.quality_profile = "instant"
        self.dictation_corrections = CorrectionStore.for_config(
            config_path,
            max_rules=self.config.correction_memory.max_rules,
            enabled=self.config.correction_memory.enabled,
        )
        self._editing_completed_setup = self.config.onboarding.completed
        if self.config.onboarding.version != ONBOARDING_VERSION:
            self.config.onboarding.current_step = 0
            self.config.onboarding.dictation_test_passed = False
            self.config.onboarding.polish_skipped = False
            self.config.onboarding.version = ONBOARDING_VERSION
        if not self.config.onboarding.started_at:
            self.config.onboarding.started_at = _utc_now()
        self.palette = get_palette(self.config.hud.theme)
        from .settings_helpers import apply_qt_palette

        apply_qt_palette(QApplication.instance(), self.palette, QColor, QPalette)
        self.hardware = detect_hardware()
        self.speech_acceleration_ready = bool(self.hardware.has_nvidia and nvidia_acceleration_ready())
        self.recommended = recommended_model_for_hardware(self.hardware)
        self.completed = False
        self.index = 0 if self.config.onboarding.completed else max(0, min(4, self.config.onboarding.current_step))
        self._closing_intentionally = False

        owner = self

        class OnboardingMainWindow(QMainWindow):
            def closeEvent(self, event) -> None:
                owner._handle_window_close()
                super().closeEvent(event)

        self.window = OnboardingMainWindow()
        self.window.setWindowTitle("Winsper Setup")
        self.window.setFont(QFont("Segoe UI", 10))
        self.window.resize(1180, 780)
        self.window.setMinimumSize(960, 660)
        self.window.setStyleSheet(self.stylesheet())
        self.window.destroyed.connect(lambda *_args: self._cleanup())
        pixmap = self._logo_pixmap(QPixmap, 36)
        icon = qt_window_icon(QIcon, QPixmap)
        if not icon.isNull():
            self.window.setWindowIcon(icon)

        root = QWidget()
        root.setObjectName("AppCanvas")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)
        self.window.setCentralWidget(root)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(252)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 22, 18, 18)
        sidebar_layout.setSpacing(5)

        brand = QHBoxLayout()
        brand.setContentsMargins(5, 0, 0, 0)
        brand.setSpacing(12)
        logo = QLabel()
        logo.setObjectName("BrandLogo")
        logo.setPixmap(pixmap)
        logo.setFixedSize(QSize(36, 36))
        self.brand_logo = logo
        brand.addWidget(logo, 0, Qt.AlignVCenter)
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(1)
        title = QLabel("Winsper")
        title.setObjectName("BrandName")
        brand_subtitle = QLabel("First-time setup")
        brand_subtitle.setObjectName("BrandSubtitle")
        brand_copy.addWidget(title)
        brand_copy.addWidget(brand_subtitle)
        brand.addLayout(brand_copy)
        brand.addStretch(1)
        self.theme_toggle = QToolButton()
        self.theme_toggle.setObjectName("ThemeToggle")
        self.theme_toggle.setFixedSize(32, 32)
        self.theme_toggle.setAccessibleName("Toggle light and dark mode")
        self.theme_toggle.clicked.connect(self._toggle_theme)
        brand.addWidget(self.theme_toggle, 0, Qt.AlignVCenter)
        sidebar_layout.addLayout(brand)
        sidebar_layout.addSpacing(22)

        self.step_labels: list[QLabel] = []
        self.step_frames: list[QFrame] = []
        self.step_numbers: list[QLabel] = []
        self.step_icon_names = ["models", "dictation", "polish", "shortcuts", "check"]
        self.steps = [
            "Language & quality",
            "Try Winsper",
            "Optional Polish",
            "Optional voice triggers",
            "Finish",
        ]
        step_details = [
            "Choose what fits",
            "Test your dictation",
            "Add local rewriting",
            "Try useful phrases",
            "Review and launch",
        ]
        for number, (step, detail) in enumerate(zip(self.steps, step_details, strict=True), start=1):
            frame = QFrame()
            frame.setObjectName("StepItem")
            frame.setAccessibleName(f"Step {number}: {step}")
            row = QHBoxLayout(frame)
            row.setContentsMargins(10, 9, 10, 9)
            row.setSpacing(10)
            number_label = QLabel()
            number_label.setObjectName("StepIcon")
            number_label.setAlignment(Qt.AlignCenter)
            number_label.setFixedSize(28, 28)
            copy = QVBoxLayout()
            copy.setSpacing(1)
            label = QLabel(step)
            label.setObjectName("StepTitle")
            description = QLabel(detail)
            description.setObjectName("StepDetail")
            copy.addWidget(label)
            copy.addWidget(description)
            row.addWidget(number_label, 0, Qt.AlignVCenter)
            row.addLayout(copy, 1)
            self.step_frames.append(frame)
            self.step_numbers.append(number_label)
            self.step_labels.append(label)
            sidebar_layout.addWidget(frame)
        sidebar_layout.addStretch(1)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        self.step_counter = QLabel()
        self.step_counter.setObjectName("SetupCounter")
        progress_row.addWidget(self.step_counter)
        progress_row.addStretch(1)
        sidebar_layout.addLayout(progress_row)
        self.setup_progress = QProgressBar()
        self.setup_progress.setObjectName("SetupProgress")
        self.setup_progress.setRange(1, 5)
        self.setup_progress.setTextVisible(False)
        self.setup_progress.setAccessibleName("Setup progress")
        sidebar_layout.addWidget(self.setup_progress)
        self.sidebar_status = QLabel()
        self.sidebar_status.setObjectName("Tiny")
        self.sidebar_status.setWordWrap(True)
        sidebar_layout.addWidget(self.sidebar_status)

        main = QFrame()
        main.setObjectName("ContentPanel")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack, 1)

        from .settings_combo_widgets import create_settings_combo

        self.language_combo = create_settings_combo(
            lambda: self.palette,
            accessible_name="Transcription language",
        )
        self.hud_style_combo = create_settings_combo(
            lambda: self.palette,
            accessible_name="HUD style",
        )
        self.hud_style_combo.addItem("Full HUD", "standard")
        self.hud_style_combo.addItem("Compact HUD", "compact")
        hud_mode_index = self.hud_style_combo.findData(self.config.hud.mode)
        self.hud_style_combo.setCurrentIndex(hud_mode_index if hud_mode_index >= 0 else 1)
        self.hud_style_combo.currentIndexChanged.connect(self._on_hud_style_changed)
        self.preload_check = QCheckBox("Warm selected speech models when Winsper starts")
        self.startup_check = QCheckBox("Start Winsper when I sign in to Windows")
        from .settings_widgets import ToggleSwitch

        self.polish_check = ToggleSwitch.create(
            checked=self.config.dictation.polish_enabled,
            accent=self.palette.accent,
            accent2=self.palette.accent_2,
        )
        self.polish_check.setAccessibleName("Enable Polish")
        self.fallback_check = QCheckBox("Keep raw dictated text if local AI is unavailable")
        self.recommended_polish_model = None
        self.polish_recommended_model_id = ""
        self.speed_group = QButtonGroup()
        self.speech_quality_models = {}
        self.polish_quality_group = None
        self.polish_quality_models = {}
        self.polish_options_container = None
        self.polish_disabled_state = None
        self.polish_mode_group = None
        self.polish_free_speech_card = None
        self.polish_selected_text_card = None
        self.model_status = QLabel()
        self.model_download_progress = None
        self.model_download_button = None
        self.polish_test_result = QLabel()
        self.polish_test_button = None
        self.dictation_status = QLabel()
        self.dictation_state_hint = None
        self.dictation_state_icon = None
        self.dictation_transcript_icon = None
        self.dictation_practice_shortcut_chip = None
        self.trigger_shortcut_chip = None
        self.dictation_progress = None
        self.dictation_result = QLabel()
        self.dictation_test_button = None
        self.hotkey_check_status = QLabel()
        self.polish_shortcut_status = QLabel()
        self.dictate_shortcut_confirmed = False
        self.finish_status = None
        self.finish_title = None
        self.finish_detail = None
        self.finish_language_value = None
        self.finish_quality_value = None
        self.finish_polish_value = None
        self.finish_shortcut_value = None
        self.finish_button = None
        self.polish_setup_status = QLabel()
        self.polish_setup_progress = None
        self.polish_setup_button = None
        self.polish_quality_summary = None
        self.polish_quality_choices = None
        self.polish_quality_change_button = None
        self.polish_setup_pause_button = None
        self.polish_setup_cancel_button = None
        self.polish_skip_button = None
        self.polish_setup_events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.polish_setup_timer = None
        self.polish_setup_running = False
        self.polish_setup_paused = False
        self.polish_setup_pause_event = threading.Event()
        self.polish_setup_cancel_event = threading.Event()
        self.dictation_test_events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.dictation_runtime_events: "queue.Queue[tuple[int, str, object]]" = queue.Queue()
        self.download_events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.polish_test_events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.polish_runtime_events: "queue.Queue[tuple[int, str, object]]" = queue.Queue()
        self.dictation_recorder: AudioRecorder | None = None
        self.dictation_transcriber = None
        self.dictation_speech_config = None
        self.dictation_runtime_ready = False
        self.dictation_runtime_preparing = False
        self.dictation_runtime_generation = 0
        self.dictation_runtime_signature = None
        self.dictation_runtime_cancel_event = None
        self.dictation_runtime_thread = None
        self.dictation_runtime_prepare_lock = threading.Lock()
        self.dictation_runtime_prepare_recorder = None
        self.dictation_runtime_prepare_transcriber = None
        self.dictation_device_fallback: tuple[str, str] | None = None
        self.dictation_timer = None
        self.download_timer = None
        self.download_running = False
        self.download_paused = False
        self.download_pause_event = threading.Event()
        self.download_cancel_event = threading.Event()
        self.model_download_pause_button = None
        self.model_download_cancel_button = None
        self.active_speech_download_model = ""
        self.polish_test_running = False
        self.polish_rewriter = None
        self.polish_runtime_generation = 0
        self.polish_runtime_model_id = ""
        self.polish_runtime_preparing = False
        self.polish_runtime_cancel_event = None
        self.dictation_test_running = False
        self.dictation_recording = False
        self.dictation_test_generation = 0
        self.active_dictation_test_generation = 0
        self.dictation_test_passed = self.config.onboarding.dictation_test_passed
        self.dictation_test_hud = None
        self.dictation_test_hud_thread = None
        self.dictation_test_hud_stop_requested = False
        self.dictation_test_hud_ready = threading.Event()
        self.dictation_test_hud_message_lock = threading.Lock()
        self.dictation_test_hud_pending_message = None
        self.onboarding_hotkeys = None
        self.onboarding_hotkey_signature = None

        class HotkeyBridge(QObject):
            triggered = Signal(str, str)

        self.onboarding_hotkey_bridge = HotkeyBridge(self.window)
        self.onboarding_hotkey_bridge.triggered.connect(self._handle_onboarding_hotkey_event)
        self.polish_recorder = None
        self.polish_recording = False
        self.polish_selected_text = ""
        self.polish_active_mode = "free"
        self.polish_active_app: dict[str, str] = {}

        from .settings_shortcut_widgets import (
            create_pulsing_shortcut_display,
            create_shortcut_recorder,
        )

        self.dictate_shortcut_recorder = create_shortcut_recorder(self.config.hotkeys.dictate)
        self.polish_shortcut_recorder = create_shortcut_recorder(self.config.hotkeys.polish)
        self.dictation_practice_shortcut_chip = create_pulsing_shortcut_display(
            self.config.hotkeys.dictate,
            self.palette.accent,
        )
        self.dictation_practice_shortcut_chip.setAccessibleName("Shortcut to press for Dictate practice")
        self.dictate_shortcut_recorder.setAttentionAccent(self.palette.accent)
        self.polish_shortcut_recorder.setAttentionAccent(self.palette.accent)
        self.dictate_shortcut_recorder.shortcutChanged.connect(self._on_shortcut_changed)
        self.polish_shortcut_recorder.shortcutChanged.connect(self._on_shortcut_changed)

        self.onboarding_hotkey_timer = QTimer(self.window)
        self.onboarding_hotkey_timer.setInterval(50)
        self.onboarding_hotkey_timer.timeout.connect(self._poll_live_polish)
        self.onboarding_hotkey_timer.start()

        self.fallback_check.setChecked(self.config.dictation.polish_fallback_to_ramble)
        self.preload_check.setChecked(self.config.speech.preload_on_startup)
        self.startup_check.setChecked(self.config.startup.start_with_windows or is_start_with_windows_enabled(config_path))

        self.stack.addWidget(self._build_speed_page())
        self.stack.addWidget(self._build_dictation_test_page())
        self.stack.addWidget(self._build_polish_page())
        self.stack.addWidget(self._build_triggers_page())
        self.stack.addWidget(self._build_finish_page())

        footer_frame = QFrame()
        footer_frame.setObjectName("SetupFooter")
        footer = QHBoxLayout(footer_frame)
        footer.setContentsMargins(30, 14, 30, 18)
        footer.setSpacing(10)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._back)
        self.defer_button = QPushButton("Exit setup")
        self.defer_button.setObjectName("LinkButton")
        self.defer_button.clicked.connect(self._defer)
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("PrimaryButton")
        self.next_button.setMinimumWidth(132)
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self._next)
        for button, name in (
            (self.back_button, "Go to previous setup step"),
            (self.defer_button, "Exit setup; it will reopen next time"),
            (self.next_button, "Go to next setup step"),
        ):
            button.setAccessibleName(name)
        footer.addWidget(self.back_button)
        footer.addStretch(1)
        footer.addWidget(self.defer_button)
        footer.addWidget(self.next_button)
        main_layout.addWidget(footer_frame)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(main, 1)
        from .settings_cursor_policy import create_settings_button_cursor_policy

        self._button_cursor_policy = create_settings_button_cursor_policy(self.window)
        self.window._winsper_cursor_policy = self._button_cursor_policy
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._button_cursor_policy)
        self._button_cursor_policy.apply_tree(self.window)
        self._refresh()

    def show(self) -> None:
        from PySide6.QtCore import QTimer

        self.window.show()
        apply_native_window_style(self.window, self.palette)
        # Construction happens before the native window is visible. Refresh
        # once after first show so a resumed interactive step immediately
        # reflects any Dictation preparation already in progress.
        QTimer.singleShot(0, self._refresh)

    def close(self) -> None:
        self.window.close()

    def _logo_pixmap(self, QPixmap, size: int):
        from .branding import logo_pixmap

        return logo_pixmap(QPixmap, size)

    def _back(self) -> None:
        previous = self.index
        target = max(0, self.index - 1)
        self._stop_polish_test()
        self._cancel_dictation_attempt()
        if previous in {1, 2, 3} and target not in {1, 2, 3}:
            self._stop_polish_test_runtime()
            self._stop_dictation_test()
            self._stop_dictation_test_hud()
        self.index = target
        self._persist_progress()
        self._refresh()

    def _next(self) -> None:
        if self.index == 0:
            if self.download_running:
                self.model_status.setText("Pause or cancel the current download first.")
                return
            if not self._speech_support_ready():
                self.model_status.setText("Download the selected Dictation model before continuing.")
                self.model_download_button.setFocus()
                return
        if self.index == 2 and self.polish_setup_running:
            self.polish_setup_status.setText("Pause or cancel the current download before continuing.")
            return
        if self.index >= self.stack.count() - 1:
            self._finish()
            return
        previous = self.index
        target = self.index + 1
        self._stop_polish_test()
        self._cancel_dictation_attempt()
        if previous in {1, 2, 3} and target not in {1, 2, 3}:
            self._stop_polish_test_runtime()
            self._stop_dictation_test()
            self._stop_dictation_test_hud()
        self.index = target
        self._persist_progress()
        self._refresh()

    def _defer(self) -> None:
        """Leave safely without pretending setup was completed."""
        self._persist_progress()
        self._closing_intentionally = True
        self.window.close()

    def _finish(self) -> None:
        if not self._speech_support_ready():
            self.index = 0
            self.sidebar_status.setText("Download Dictation support before finishing setup.")
            self._refresh()
            return
        self._apply_choices(completed=True)
        try:
            save_config(self.config, self.config_path)
            set_start_with_windows(self.config_path, self.config.startup.start_with_windows)
        except Exception as exc:
            self.sidebar_status.setText(f"Could not save setup: {friendly_setup_error(exc)}")
            return
        self._closing_intentionally = True
        self.completed = True
        self.window.close()

    def _persist_progress(self) -> bool:
        try:
            completed_at = self.config.onboarding.completed_at
            self._apply_choices(completed=self._editing_completed_setup)
            if self._editing_completed_setup:
                self.config.onboarding.completed_at = completed_at
            save_config(self.config, self.config_path)
            return True
        except Exception as exc:
            self.sidebar_status.setText(f"Could not save setup progress: {friendly_setup_error(exc)}")
            return False

    def _handle_window_close(self) -> None:
        # Hide first so model and worker shutdown never makes Close feel stuck.
        self.window.hide()
        if not self._closing_intentionally and not self.completed:
            self._persist_progress()
        self._cleanup()

    def _apply_speed_profile(self, config: AppConfig) -> None:
        selected = self.speed_group.checkedButton()
        profile_id = selected.property("profile_id") if selected is not None else "balanced"
        apply_intent_profile(config, str(profile_id), acceleration_ready=self.speech_acceleration_ready)
        if self.dictation_device_fallback is not None:
            config.speech.device, config.speech.compute_type = self.dictation_device_fallback

    def _speech_model_for_profile(self, profile_id: str):
        config = deepcopy(self.config)
        self._apply_language_choice(config)
        apply_intent_profile(
            config,
            profile_id,
            acceleration_ready=self.speech_acceleration_ready,
        )
        return find_speech_model(config.dictation.ramble_model or config.speech.model)

    def _apply_language_choice(self, config: AppConfig) -> None:
        code = str(self.language_combo.currentData() or "en") if self.language_combo.count() else "en"
        config.speech.language = code

    def _cleanup(self) -> None:
        self.dictate_shortcut_recorder.setAttentionActive(False)
        self.polish_shortcut_recorder.setAttentionActive(False)
        self.dictation_practice_shortcut_chip.setAttentionActive(False)
        self._stop_onboarding_hotkeys()
        self._stop_polish_test()
        self._stop_polish_test_runtime()
        self._stop_dictation_test()
        self._stop_dictation_test_hud()
        self.download_cancel_event.set()
        self.download_pause_event.clear()
        self.polish_setup_cancel_event.set()
        self.polish_setup_pause_event.clear()
        self._stop_download_timer()
        if self.polish_setup_timer is not None:
            self.polish_setup_timer.stop()
            self.polish_setup_timer = None
        if self.dictation_timer is not None:
            self.dictation_timer.stop()
            self.dictation_timer = None
        if self.onboarding_hotkey_timer is not None:
            self.onboarding_hotkey_timer.stop()

    def _refresh(self) -> None:
        from .settings_icons import settings_nav_icon

        self.stack.setCurrentIndex(self.index)
        for step_index, (frame, number) in enumerate(zip(self.step_frames, self.step_numbers, strict=True)):
            active = step_index == self.index
            complete = step_index < self.index
            frame.setProperty("active", active)
            frame.setProperty("complete", complete)
            number.setProperty("active", active)
            number.setProperty("complete", complete)
            color = self.palette.accent if active or complete else self.palette.muted
            icon_name = "check" if complete else self.step_icon_names[step_index]
            number.setPixmap(settings_nav_icon(icon_name, color, 15).pixmap(15, 15))
            for widget in (frame, number):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        self.step_counter.setText(f"Step {self.index + 1} of {self.stack.count()}")
        self.setup_progress.setValue(self.index + 1)
        self.back_button.setVisible(self.index > 0)
        self.defer_button.setVisible(self.index < self.stack.count() - 1)
        self.next_button.setVisible(self.index < self.stack.count() - 1)
        speech_ready = self._speech_support_ready()
        next_copy = {
            0: "Continue",
            1: "Continue to Polish" if self.dictation_test_passed else "Skip practice",
            2: "Continue",
            3: "Finish setup" if self.trigger_test_stage == "complete" else "Skip lesson",
        }.get(self.index, "Continue")
        self.next_button.setText(next_copy)
        self.next_button.setEnabled(self.index != 0 or (speech_ready and not self.download_running))
        self.next_button.setDefault(self.index < self.stack.count() - 1 and self.next_button.isEnabled())
        if self.finish_button is not None:
            self.finish_button.setDefault(self.index >= self.stack.count() - 1)
        if self.index == 0:
            self._refresh_model_status()
        if self.index in {0, 1, 2, 3} and self._speech_support_ready():
            self._ensure_dictation_test_runtime()
            if self.index in {1, 2, 3} and (
                not self.dictation_runtime_ready or self.dictation_test_hud is None or not self.dictation_test_hud_ready.is_set()
            ):
                self._set_dictation_practice_state(
                    "process",
                    "Preparing Winsper",
                    "Dictate becomes active as soon as speech and microphone support are ready.",
                    "Your words will appear here when Winsper is ready.",
                )
        elif self.index in {1, 3} and not self._speech_support_ready():
            self._set_dictation_practice_state(
                "warning",
                "Speech support is not ready",
                "Go back and choose a Dictation model.",
                "Download the selected model, then return here to try Dictate.",
            )
        if self.index == 2:
            self._refresh_polish_setup_status()
            self._ensure_polish_test_runtime()
        self.dictate_shortcut_recorder.setAttentionActive(self.index == 1)
        self.dictation_practice_shortcut_chip.setAttentionActive(
            self.index == 1 and self.dictation_runtime_ready
        )
        self.polish_shortcut_recorder.setAttentionActive(self.index == 2 and self.polish_check.isChecked())
        self._restart_onboarding_hotkeys()
        self._refresh_theme_toggle()
        self._refresh_finish_status()
        current_page = self.stack.currentWidget()
        current_page.setAccessibleName(self.steps[self.index])
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._focus_current_step)

    def _toggle_theme(self) -> None:
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication
        from .settings_helpers import apply_qt_palette

        self._stop_polish_test()
        self._cancel_dictation_attempt()
        self._stop_dictation_test_hud()
        self.config.hud.theme = "light" if self.palette.mode == "dark" else "dark"
        self.palette = get_palette(self.config.hud.theme)
        apply_qt_palette(QApplication.instance(), self.palette, QColor, QPalette)
        self.window.setStyleSheet(self.stylesheet())
        apply_native_window_style(self.window, self.palette)
        self._refresh()

    def _on_hud_style_changed(self, _index: int) -> None:
        mode = str(self.hud_style_combo.currentData() or "compact")
        if mode not in {"compact", "standard"} or self.config.hud.mode == mode:
            return
        self.config.hud.mode = mode
        self._stop_dictation_test_hud()
        if self.index == 1 and self.dictation_runtime_ready:
            self._show_dictation_test_hud("Ready", "Hold the hotkey to speak", "idle")

    def _refresh_theme_toggle(self) -> None:
        from .settings_icons import settings_nav_icon

        target = "light" if self.palette.mode == "dark" else "dark"
        self.theme_toggle.setIcon(settings_nav_icon("appearance", self.palette.text, 17))
        self.theme_toggle.setToolTip(f"Use {target} mode")
        for toggle in (self.polish_check,):
            if toggle is not None and hasattr(toggle, "setAccentColors"):
                toggle.setAccentColors(self.palette.accent, self.palette.accent_2)
        for group in (self.speed_group, self.polish_quality_group):
            if group is None:
                continue
            for button in group.buttons():
                button.setIcon(self._choice_icon(button.isChecked()))
        if getattr(self, "polish_disabled_icon", None) is not None:
            self.polish_disabled_icon.setPixmap(settings_nav_icon("polish", self.palette.accent, 24).pixmap(24, 24))
        self.dictate_shortcut_recorder.setAttentionAccent(self.palette.accent)
        self.polish_shortcut_recorder.setAttentionAccent(self.palette.accent)
        self.dictation_practice_shortcut_chip.setAttentionAccent(self.palette.accent)

    def stylesheet(self) -> str:
        from .settings_style import settings_stylesheet

        p = self.palette
        return (
            settings_stylesheet(p)
            + f"""
        QScrollArea#OnboardingPage, QScrollArea#OnboardingPage > QWidget,
        QScrollArea#OnboardingPage > QWidget > QWidget, QWidget#OnboardingPageContent {{
            background: transparent; border: none;
        }}
        QFrame#PageHeader {{ background: transparent; border: none; }}
        QLabel#PageTitle {{ color: {p.text}; font-size: 26px; font-weight: 600; }}
        QLabel#PageSubtitle {{ color: {p.muted}; font-size: 13px; font-weight: 400; }}
        QLabel#BrandName {{ color: {p.text}; font-size: 17px; font-weight: 650; }}
        QLabel#BrandSubtitle {{ color: {p.muted}; font-size: 11px; font-weight: 500; }}
        QLabel#SetupCounter {{ color: {p.text}; font-size: 12px; font-weight: 600; }}
        QProgressBar#SetupProgress {{
            background: {p.surface_3}; border: none; border-radius: 2px;
            min-height: 4px; max-height: 4px;
        }}
        QProgressBar#SetupProgress::chunk {{ background: {p.accent}; border-radius: 2px; }}
        QFrame#StepItem {{
            background: transparent; border: 1px solid transparent; border-radius: 12px;
        }}
        QFrame#StepItem[active="true"] {{
            background: {p.sidebar_active}; border-color: {p.border_soft};
            border-left: 3px solid {p.accent};
        }}
        QLabel#StepIcon {{
            color: {p.muted}; background: transparent; border: none;
        }}
        QLabel#StepIcon[active="true"] {{
            color: {p.accent}; background: transparent; border: none;
        }}
        QLabel#StepIcon[complete="true"] {{
            color: {p.accent}; background: transparent; border: none;
        }}
        QLabel#StepTitle {{ color: {p.text}; font-size: 12px; font-weight: 600; }}
        QLabel#StepDetail {{ color: {p.muted}; font-size: 10px; font-weight: 400; }}
        QToolButton#ThemeToggle {{
            background: transparent; border: 1px solid transparent; border-radius: 8px;
        }}
        QToolButton#ThemeToggle:hover {{ background: {p.surface_3}; border-color: {p.border_soft}; }}
        QFrame#SetupFooter {{
            background: {p.surface}; border: none; border-top: 1px solid {p.border_soft};
        }}
        QFrame#SetupCard, QFrame#FinishCard {{
            background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 16px;
        }}
        QFrame#PolishDisabledState {{
            background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 12px;
        }}
        QLabel#PolishDisabledIcon {{
            background: {p.sidebar_active}; border: 1px solid {p.border_soft}; border-radius: 19px;
        }}
        QLabel#PolishDisabledTitle {{ color: {p.text}; font-size: 14px; font-weight: 650; }}
        QLabel#PolishDisabledCopy {{ color: {p.muted}; font-size: 12px; }}
        QFrame#FinishCard {{ border-top: 2px solid {p.accent}; }}
        QFrame#SetupSummary {{
            background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 11px;
        }}
        QFrame#SetupRow {{ background: transparent; border: none; }}
        QFrame#FeatureRow {{
            background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 11px;
        }}
        QLabel#FeatureMark {{
            color: {p.accent}; background: {p.sidebar_active}; border: 1px solid {p.border_soft};
            border-radius: 12px; font-size: 14px; font-weight: 700;
        }}
        QLabel#FinishMark {{
            color: {p.on_accent}; background: {p.accent}; border: none;
            border-radius: 25px; font-size: 24px; font-weight: 700;
        }}
        QLabel#StatusBox, QLabel#TranscriptBox {{
            color: {p.text}; background: {p.surface}; border: 1px solid {p.border_soft};
            border-radius: 11px; padding: 11px 13px; font-size: 12px;
        }}
        QFrame#SetupNote {{
            background: {p.sidebar_active}; border: 1px solid {p.border_soft}; border-radius: 12px;
        }}
        QLabel#SetupNoteText {{ color: {p.muted}; font-size: 12px; }}
        QLabel#SetupNoteIcon {{ background: transparent; border: none; }}
        QLabel#TranscriptBox {{ min-height: 48px; }}
        QLabel#HotkeyCheck {{ color: {p.muted}; font-size: 12px; font-weight: 500; }}
        QLabel#HotkeyCheck[tone="good"] {{ color: {p.accent}; font-weight: 650; }}
        QLabel#SummaryLabel {{ color: {p.muted}; font-size: 12px; font-weight: 500; }}
        QLabel#SummaryValue {{ color: {p.text}; font-size: 12px; font-weight: 650; }}
        QFrame#QualityChoiceRow {{
            background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 12px;
        }}
        QFrame#QualityChoiceRow:hover {{ background: {p.surface_3}; border-color: {p.border}; }}
        QFrame#QualityChoiceRow[selected="true"] {{
            background: {p.sidebar_active}; border-color: {p.accent};
        }}
        QFrame#QualityChoiceRow:disabled {{ background: {p.surface_2}; border-color: {p.border_soft}; }}
        QPushButton#QualityChoiceControl {{
            color: {p.text}; background: transparent; border: none; padding: 0;
            font-size: 12px; font-weight: 650; text-align: left;
        }}
        QLabel#QualityChoiceDetail {{ color: {p.muted}; font-size: 11px; }}
        QLabel#QualityModelName {{ color: {p.muted}; font-size: 11px; font-weight: 600; }}
        QLabel#ModelReadyTick {{ background: transparent; border: none; }}
        QPushButton#QuietButton {{
            background: {p.surface}; color: {p.text}; border-color: {p.border_soft};
        }}
        QToolButton#AppChoice {{
            color: {p.text}; background: {p.surface}; border: 1px solid {p.border_soft};
            border-radius: 10px; padding: 7px 10px; font-size: 11px; font-weight: 600;
        }}
        QToolButton#AppChoice:hover {{ background: {p.surface_3}; border-color: {p.border}; }}
        QToolButton#AppChoice:checked {{ background: {p.sidebar_active}; border-color: {p.accent}; }}
        QTextEdit#SelectionExercise {{
            color: {p.text}; background: {p.surface}; border: 1px solid {p.border_soft};
            border-radius: 11px; padding: 10px; selection-background-color: {p.accent};
            selection-color: {p.on_accent};
        }}
        QFrame#DictationReadyPanel {{
            background: {p.sidebar_active}; border: 1px solid {p.border_soft}; border-radius: 12px;
        }}
        QFrame#DictationReadyPanel:focus {{ border-color: {p.accent}; }}
        QFrame#ShortcutPracticePrompt {{
            background: {p.surface_3}; border: 1px solid {p.border_soft}; border-radius: 11px;
        }}
        QFrame#ShortcutDisplay {{
            background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px;
        }}
        QLabel#ShortcutPracticeCopy {{ color: {p.text}; font-size: 12px; font-weight: 550; }}
        QLabel#DictationStateIcon {{
            background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 18px;
        }}
        QLabel#DictationStateTitle {{ color: {p.text}; font-size: 13px; font-weight: 650; }}
        QFrame#TranscriptCanvas {{
            background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 12px;
            min-height: 112px;
        }}
        QLabel#TranscriptStateIcon {{ background: transparent; border: none; }}
        QLabel#TranscriptText {{ color: {p.muted}; font-size: 13px; padding: 8px 1px; }}
        QPushButton#PolishModeButton {{
            color: {p.muted}; background: {p.surface}; border: 1px solid {p.border_soft};
            border-radius: 11px; padding: 11px 16px; min-height: 42px;
            font-size: 14px; font-weight: 600; text-align: left;
        }}
        QPushButton#PolishModeButton:hover {{ background: {p.surface_3}; border-color: {p.border}; }}
        QPushButton#PolishModeButton:checked {{
            color: {p.text}; background: {p.sidebar_active}; border-color: {p.accent};
        }}
        QLabel#OptionEyebrow {{ color: {p.accent}; font-size: 10px; font-weight: 700; }}
        QFrame#ReadAloudPrompt {{
            background: {p.surface}; border: 1px solid {p.accent}; border-radius: 11px;
        }}
        QLabel#TriggerReadAloudText {{
            color: {p.text}; background: transparent; border: none;
            font-size: 14px; font-weight: 650;
        }}
        QFrame#SetupCard[taskComplete="true"] {{ border-color: {p.success}; }}
        QFrame#SetupCard[activeTask="true"] {{ border-color: {p.accent}; border-width: 2px; }}
        QProgressBar {{
            background: {p.surface}; border: none; border-radius: 3px;
            min-height: 6px; max-height: 6px;
        }}
        QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}
        """
        )
