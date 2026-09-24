from __future__ import annotations

from .settings_helpers import apply_qt_palette
from .settings_icons import settings_nav_icon
from .theme import get_palette


class SettingsSurfacePagesMixin:
    def _update_theme_preview(self, theme: str) -> None:
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication

        self.palette = get_palette(theme)
        app = QApplication.instance()
        if app is not None:
            apply_qt_palette(app, self.palette, QColor, QPalette)
        self.window.setStyleSheet(self.stylesheet())
        from .windows_ui import apply_native_window_style

        apply_native_window_style(self.window, self.palette)
        for dialog in self._modal_dialogs.values():
            dialog.setStyleSheet(self.window.styleSheet())
            apply_native_window_style(dialog, self.palette)
        self._refresh_brand_logo()
        for toggle in self.theme_toggles:
            toggle.setAccentColors(self.palette.accent, self.palette.accent_2)
        self._refresh_home_action_icon()
        self._show_page(self.stack.currentIndex())

    def _build_privacy_page(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

        from .history import RETENTION_OPTIONS, retention_label

        page, layout = self._page(
            "Privacy",
            "Voice processing stays on your PC. You choose whether transcript history is kept.",
        )

        trust_panel = QFrame()
        trust_panel.setObjectName("PrivacyTrustPanel")
        trust_layout = QHBoxLayout(trust_panel)
        trust_layout.setContentsMargins(18, 17, 20, 17)
        trust_layout.setSpacing(15)

        icon_tile = QLabel()
        icon_tile.setObjectName("PrivacyTrustIcon")
        icon_tile.setFixedSize(42, 42)
        icon_tile.setAlignment(Qt.AlignCenter)
        icon_tile.setPixmap(settings_nav_icon("privacy", self.palette.accent, 22).pixmap(22, 22))
        icon_tile.setAccessibleName("Privacy protected")
        trust_layout.addWidget(icon_tile, 0, Qt.AlignTop)

        trust_copy = QVBoxLayout()
        trust_copy.setSpacing(4)
        trust_title = QLabel("Private by design")
        trust_title.setObjectName("PrivacyTrustTitle")
        trust_detail = QLabel(
            "Audio is processed in memory and discarded after each action. "
            "Dictation and Polish run locally."
        )
        trust_detail.setObjectName("PrivacyTrustDetail")
        trust_detail.setWordWrap(True)
        trust_copy.addWidget(trust_title)
        trust_copy.addWidget(trust_detail)
        trust_layout.addLayout(trust_copy, 1)
        layout.addWidget(trust_panel)
        layout.addSpacing(10)

        section_title = QLabel("Transcript history")
        section_title.setObjectName("CardTitle")
        layout.addWidget(section_title)
        section_detail = QLabel("Keep recent results available in History.")
        section_detail.setObjectName("Muted")
        layout.addWidget(section_detail)

        settings_list = QFrame()
        settings_list.setObjectName("PrivacySettingsList")
        settings_layout = QVBoxLayout(settings_list)
        settings_layout.setContentsMargins(0, 2, 0, 0)
        settings_layout.setSpacing(0)

        history_toggle = self._check("history.enabled", self.config.history.enabled)
        self._simple_row(
            settings_layout,
            "Save dictation history",
            "Keep successful Dictation and Polish results on this PC.",
            history_toggle,
        )
        max_items = self._line("history.max_items", str(self.config.history.max_items))
        max_items.hide()
        retention = self._combo(
            "history.retention_days",
            retention_label(self.config.history.retention_days),
            [label for _days, label in RETENTION_OPTIONS],
        )
        retention.setEnabled(history_toggle.isChecked())
        history_toggle.toggled.connect(retention.setEnabled)
        self._simple_row(
            settings_layout,
            "Keep history",
            "Older transcripts are removed automatically.",
            retention,
            last=True,
        )
        layout.addWidget(settings_list)

        layout.addStretch(1)
        return page
