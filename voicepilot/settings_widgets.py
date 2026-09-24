from __future__ import annotations

from .settings_combo_widgets import create_settings_combo, create_theme_combo
from .settings_cursor_policy import create_settings_button_cursor_policy
from .settings_shortcut_widgets import create_shortcut_recorder, format_shortcut
from .settings_toggle import ToggleSwitch

def add_personalize_tab_separator(tabs) -> None:
    """Add a visible, non-interactive divider between two Personalize tabs."""

    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtWidgets import QFrame

    bar = tabs.tabBar()
    separator = QFrame(bar)
    separator.setObjectName("PersonalizeTabSeparator")
    separator.setFixedSize(1, 18)
    separator.setFocusPolicy(Qt.NoFocus)
    separator.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    class SeparatorPositioner(QObject):
        def reposition(self) -> None:
            if bar.count() < 2:
                separator.hide()
                return
            first = bar.tabRect(0)
            # Both tab styles reserve a 24 px trailing gap. Centre the line in
            # that gap so it never becomes part of the selected tab border.
            separator.move(first.right() - 12, max(0, (bar.height() - separator.height()) // 2))
            separator.show()
            separator.raise_()

        def eventFilter(self, watched, event) -> bool:
            if watched is bar and event.type() in {
                QEvent.LayoutRequest,
                QEvent.Resize,
                QEvent.Show,
                QEvent.StyleChange,
            }:
                self.reposition()
            return False

    positioner = SeparatorPositioner(bar)
    bar.installEventFilter(positioner)
    bar._winsper_separator_positioner = positioner
    positioner.reposition()


__all__ = [
    "ToggleSwitch",
    "add_personalize_tab_separator",
    "create_settings_button_cursor_policy",
    "create_settings_combo",
    "create_shortcut_recorder",
    "create_theme_combo",
    "format_shortcut",
]
