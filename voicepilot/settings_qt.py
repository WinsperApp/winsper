from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

from .branding import set_windows_app_user_model_id
from .config import ProfileRule, ProfileStyle, Snippet, load_config
from .corrections import CorrectionRule, CorrectionStore
from .models import (
    engine_runtime_available,
    find_speech_model,
    installed_status,
)
from .hotkeys import GlobalHoldHotkeys
from .process_control import watch_owner_process
from .settings_sync import WidgetRegistry
from .settings_widgets import (
    ToggleSwitch as BaseToggleSwitch,
    create_settings_button_cursor_policy,
)
from .model_storage import configure_model_storage
from .settings_helpers import (
    apply_qt_palette,
)
from .speed_lab import (
    SpeedLabStore,
)
from .theme import get_palette
from .windows_ui import apply_native_window_style, motion_enabled

from .settings_home import SettingsHomeMixin
from .settings_core_pages import SettingsCorePagesMixin
from .settings_consumer_pages import SettingsConsumerPagesMixin
from .settings_models import SettingsModelsMixin
from .settings_pages import SettingsPagesMixin
from .settings_layout import SettingsLayoutMixin
from .settings_persistence import SettingsPersistenceMixin
from .settings_feedback import SettingsFeedbackMixin
from .settings_registry import SettingsRegistryMixin
from .settings_shell import build_settings_navigation
from .settings_window_navigation import SettingsWindowNavigationMixin
from .settings_update_prompt import SettingsUpdatePromptMixin


class ToggleSwitch:
    @staticmethod
    def create(checked: bool = False, accent: str = "#007fd4", accent2: str = "#5b43f2"):
        return BaseToggleSwitch.create(checked, accent, accent2, motion_enabled)


def run_settings_window(
    config_path: Path,
    auto_close_seconds: float | None = None,
    owner_process_id: int = 0,
    initial_page: str = "",
) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWidgets import QStyleFactory

    set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Winsper")
    if "Fusion" in QStyleFactory.keys():
        app.setStyle(QStyleFactory.create("Fusion"))
    apply_qt_palette(app, get_palette(load_config(config_path).hud.theme), QColor, QPalette)
    window = SettingsWindow(config_path, initial_page=initial_page)
    window.show()
    owner_timer = watch_owner_process(window.window, owner_process_id)
    app.aboutToQuit.connect(window.shutdown)
    if auto_close_seconds is not None:
        QTimer.singleShot(int(auto_close_seconds * 1000), window.close)
    try:
        app.exec()
    finally:
        if owner_timer is not None:
            owner_timer.stop()
        window.shutdown()
        try:
            app.aboutToQuit.disconnect(window.shutdown)
        except (RuntimeError, TypeError):
            pass


class SettingsWindow(
    SettingsWindowNavigationMixin,
    SettingsUpdatePromptMixin,
    SettingsHomeMixin,
    SettingsConsumerPagesMixin,
    SettingsCorePagesMixin,
    SettingsModelsMixin,
    SettingsPagesMixin,
    SettingsLayoutMixin,
    SettingsPersistenceMixin,
    SettingsFeedbackMixin,
    SettingsRegistryMixin,
):
    def __init__(self, config_path: Path, initial_page: str = "") -> None:
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtGui import QFont, QIcon, QPixmap
        from PySide6.QtWidgets import (
            QFrame,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QApplication,
            QPushButton,
            QScrollArea,
            QVBoxLayout,
            QWidget,
        )

        self.config_path = config_path
        self.config = load_config(config_path)
        configure_model_storage(self.config.model_storage.path)
        self.palette = get_palette(self.config.hud.theme)
        self.widgets: dict[str, object] = {}
        self.theme_toggles: list[object] = []
        self.widget_registry = WidgetRegistry(self._schedule_auto_save)
        self.snippets: list[Snippet] = list(self.config.snippets.items)
        self.profile_styles: dict[str, ProfileStyle] = dict(self.config.profiles.styles)
        self.profile_rules: list[ProfileRule] = list(self.config.profiles.rules)
        self.correction_store = CorrectionStore.for_config(
            config_path,
            max_rules=self.config.correction_memory.max_rules,
            enabled=self.config.correction_memory.enabled,
        )
        self.corrections: list[CorrectionRule] = self.correction_store.list()
        self._saved_corrections = tuple(self.corrections)
        self.speed_store = SpeedLabStore.for_config(config_path)
        self.home_fields: dict[str, tuple[object, object]] = {}
        self.home_summary = None
        self.home_detail = None
        self.home_state_dot = None
        self.home_state_title = None
        self.home_state_detail = None
        self.home_pause_button = None
        self.home_check_status = None
        self.home_check_result = None
        self.home_test_buttons: dict[str, object] = {}
        self.home_test_events: "queue.Queue[tuple[str, str, str]]" = queue.Queue()
        self.home_test_timer = None
        self.home_test_kind = ""
        self.home_hotkey_tester: GlobalHoldHotkeys | None = None
        self.home_resume_listener_after_hotkey = False
        self.model_download_events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.model_download_timer = None
        self.model_download_running = False
        self.model_download_paused = False
        self.model_download_pause_event = threading.Event()
        self.model_download_cancel_event = threading.Event()
        self.ai_runtime_cancel_event = None
        self._model_download_context = None
        self.model_fit_warning = None
        self.polish_test_timer = None
        self._modal_dialogs: dict[str, object] = {}
        self._shutdown_started = False

        self.window = QMainWindow()
        self.window.setWindowTitle("Winsper Settings")
        # Qt's offscreen renderer and some stripped Windows environments fall
        # back to a fixed-width generic font unless the native family is set
        # explicitly. The live app and its visual regression gallery must use
        # the same Windows typography.
        self.window.setFont(QFont("Segoe UI", 10))
        self.window.resize(1180, 780)
        self.window.setMinimumSize(820, 500)
        self.window.setStyleSheet(self.stylesheet())
        self._apply_icon(QIcon, QPixmap)
        self._button_cursor_policy = create_settings_button_cursor_policy(self.window)
        # Dialog helpers can recover the native Windows cursor by walking their
        # parent chain back to this window. Keep one shared policy per Settings
        # process instead of letting each modal invent cursor cleanup.
        self.window._winsper_cursor_policy = self._button_cursor_policy
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._button_cursor_policy)
        self._init_settings_update_prompt()

        root = QWidget()
        root.setObjectName("AppCanvas")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(12)
        self.window.setCentralWidget(root)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(218)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 22, 16, 16)
        sidebar_layout.setSpacing(4)

        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 0)
        brand.setSpacing(10)
        brand.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        brand_logo = QLabel()
        brand_logo.setObjectName("BrandLogo")
        brand_logo.setAlignment(Qt.AlignCenter)
        brand_logo.setFixedSize(QSize(30, 30))
        self.brand_logo = brand_logo
        self._refresh_brand_logo()
        brand.addWidget(brand_logo, 0, Qt.AlignVCenter)

        brand_name = QLabel("Winsper")
        brand_name.setObjectName("BrandName")
        brand_name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        brand_name.setFixedHeight(30)
        brand.addWidget(brand_name, 0, Qt.AlignVCenter)
        brand.addStretch(1)
        sidebar_layout.addLayout(brand)
        sidebar_layout.addSpacing(24)

        nav_scroll = QScrollArea()
        nav_scroll.setObjectName("NavScroll")
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_scroll.setFrameShape(QFrame.NoFrame)
        nav_container = QWidget()
        nav_container.setObjectName("NavContainer")
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        nav_scroll.setWidget(nav_container)
        sidebar_layout.addWidget(nav_scroll, 1)

        build_settings_navigation(self, nav_layout, sidebar_layout)

        # Quiet, stable auto-save state in the top-right of the content area.
        from PySide6.QtCore import QEvent, QObject, QTimer, Qt

        self._save_indicator = QFrame(self.window)
        self._save_indicator.setObjectName("SaveIndicator")
        self._save_indicator.setVisible(False)
        save_layout = QHBoxLayout(self._save_indicator)
        save_layout.setContentsMargins(10, 6, 11, 6)
        save_layout.setSpacing(6)
        self._save_icon = QLabel()
        self._save_icon.setObjectName("SaveIndicatorIcon")
        self._save_icon.setFixedSize(15, 15)
        self._save_icon.setAlignment(Qt.AlignCenter)
        self._save_text = QLabel("")
        self._save_text.setObjectName("SaveIndicatorText")
        self._save_retry = QPushButton("")
        self._save_retry.setObjectName("ToastActionButton")
        self._save_retry.setVisible(False)
        self._toast_action_callback = None
        self._save_retry.clicked.connect(self._run_toast_action)
        save_layout.addWidget(self._save_icon)
        save_layout.addWidget(self._save_text)
        save_layout.addWidget(self._save_retry)

        class ResizeFilter(QObject):
            def __init__(self, owner):
                super().__init__(owner.window)
                self.owner = owner

            def eventFilter(self, obj, event):
                if event.type() == QEvent.Resize:
                    self.owner._position_save_indicator()
                return False

        self._resize_filter = ResizeFilter(self)
        self.window.installEventFilter(self._resize_filter)
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        self._save_opacity = QGraphicsOpacityEffect(self._save_indicator)
        self._save_indicator.setGraphicsEffect(self._save_opacity)
        self._toast_anim = None
        self._toast_hide_timer = QTimer(self.window)
        self._toast_hide_timer.setSingleShot(True)
        self._toast_hide_timer.timeout.connect(self._fade_out_toast)

        # Hidden status label — used by internal methods for status messages
        self.status = QLabel("")
        self.status.setObjectName("Tiny")
        self.status.setVisible(False)
        sidebar_layout.addWidget(self.status)

        # Debounce timer for text field auto-save
        from PySide6.QtCore import QTimer

        self._autosave_timer = QTimer(self.window)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._auto_save)

        content_panel = QFrame()
        content_panel.setObjectName("ContentPanel")
        content_layout = QVBoxLayout(content_panel)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.stack, 1)
        root_layout.addWidget(sidebar)
        root_layout.addWidget(content_panel, 1)
        self._show_named_page(initial_page) if initial_page else self._show_page(0)
        self._button_cursor_policy.apply_tree(self.window)

    def show(self) -> None:
        self.window.show()
        apply_native_window_style(self.window, self.palette)
        self._schedule_settings_open_update_check()

    def close(self) -> None:
        self.shutdown()
        self.window.close()

    def shutdown(self) -> None:
        """Stop Settings-owned activity before Qt begins destroying widgets."""
        from PySide6.QtWidgets import QApplication

        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._shutdown_settings_update_prompt()
        self.model_download_cancel_event.set()
        if self.ai_runtime_cancel_event is not None:
            self.ai_runtime_cancel_event.set()
        self._cleanup_home_tests()
        self._autosave_timer.stop()
        self._toast_hide_timer.stop()
        for dialog in tuple(self._modal_dialogs.values()):
            try:
                dialog.close()
            except RuntimeError:
                pass
        self._modal_dialogs.clear()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self._button_cursor_policy)

    def _apply_icon(self, QIcon, QPixmap) -> None:
        from .branding import qt_window_icon

        icon = qt_window_icon(QIcon, QPixmap)
        if not icon.isNull():
            self.window.setWindowIcon(icon)

    def _refresh_brand_logo(self) -> None:
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QApplication

        from .branding import logo_pixmap

        screen = QApplication.primaryScreen()
        dpr = max(1.0, screen.devicePixelRatio() if screen else 1.0)
        pixmap = logo_pixmap(QPixmap, int(26 * dpr))
        pixmap.setDevicePixelRatio(dpr)
        self.brand_logo.setPixmap(pixmap)

    def _refresh_model_status_label(self) -> None:
        model = self.config.dictation.ramble_model or self.config.speech.model
        preset = find_speech_model(model)
        if model.startswith("parakeet-tdt-0.6b-v2"):
            label = "Parakeet v2"
        elif model.startswith("parakeet-tdt-0.6b-v3"):
            label = "Parakeet v3"
        elif preset is not None:
            label = preset.label
        else:
            label = model or "No model"
        if preset is None:
            state = "selected"
        else:
            ready = installed_status(preset, include_size=False).installed and engine_runtime_available(preset.engine)
            state = "ready" if ready else "setup needed"
        self.model_status_label.setText(f"● {label}  ·  {state}")

    def _logo_pixmap(self, QPixmap, size: int):
        from .branding import logo_pixmap

        return logo_pixmap(QPixmap, size)
