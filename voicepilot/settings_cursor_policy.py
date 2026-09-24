from __future__ import annotations

def create_settings_button_cursor_policy(parent):
    """Keep button pointer feedback consistent across the Settings process."""
    from PySide6.QtCore import QEvent, QObject, QTimer, Qt
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import (
        QAbstractButton,
        QAbstractItemView,
        QApplication,
        QComboBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QTabBar,
        QTextEdit,
        QWidget,
    )

    class SettingsButtonCursorPolicy(QObject):
        def __init__(self, owner) -> None:
            super().__init__(owner)
            self._owner = owner

        @staticmethod
        def _set_cursor(widget, cursor, *, force: bool = False) -> None:
            """Apply a cursor, optionally forcing Qt to refresh native state.

            On Windows, closing a modal while its button is hovered can leave
            the native hand cursor visible even though QWidget.cursor() already
            resolves to ArrowCursor. Reissuing the same logical cursor through
            unset/set makes Qt update the native cursor instead of skipping it.
            """
            if not force and widget.cursor().shape() == cursor:
                return
            if force:
                widget.unsetCursor()
            widget.setCursor(cursor)

        def _apply(self, button, *, force: bool = False) -> None:
            role = str(button.property("winsperCursorRole") or "")
            if role == "forbidden":
                cursor = Qt.ForbiddenCursor
            elif role == "arrow":
                cursor = Qt.ArrowCursor
            elif button.isEnabled():
                cursor = Qt.PointingHandCursor
            else:
                cursor = Qt.ArrowCursor
            self._set_cursor(button, cursor, force=force)

        def _belongs_to_settings(self, widget) -> bool:
            current = widget
            while current is not None:
                if current is self._owner:
                    return True
                current = current.parentWidget()
            return False

        @staticmethod
        def _ancestor(widget, widget_type):
            current = widget
            while current is not None:
                if isinstance(current, widget_type):
                    return current
                current = current.parentWidget()
            return None

        @staticmethod
        def _click_surface(widget):
            current = widget
            while current is not None:
                if str(current.property("winsperCursorRole") or "") == "button":
                    return current
                current = current.parentWidget()
            return None

        @staticmethod
        def _label_has_link(widget) -> bool:
            return bool(
                isinstance(widget, QLabel)
                and "<a " in widget.text().lower()
                and widget.textInteractionFlags() & Qt.LinksAccessibleByMouse
            )

        @staticmethod
        def _text_editor(widget):
            return SettingsButtonCursorPolicy._ancestor(
                widget,
                (QLineEdit, QTextEdit, QPlainTextEdit),
            )

        def _normalize_surface(self, widget, *, force: bool = False) -> None:
            if not isinstance(widget, QWidget) or not self._belongs_to_settings(widget):
                return
            click_surface = self._click_surface(widget)
            if click_surface is not None:
                cursor = Qt.PointingHandCursor if click_surface.isEnabled() else Qt.ArrowCursor
                self._set_cursor(click_surface, cursor, force=force)
                return
            button = self._ancestor(widget, QAbstractButton)
            if button is not None:
                self._apply(button, force=force)
                return
            combo = self._ancestor(widget, QComboBox)
            if combo is not None:
                cursor = Qt.PointingHandCursor if combo.isEnabled() else Qt.ArrowCursor
                self._set_cursor(combo, cursor, force=force)
                return
            tab_bar = self._ancestor(widget, QTabBar)
            if tab_bar is not None:
                local_pos = tab_bar.mapFromGlobal(QCursor.pos())
                index = tab_bar.tabAt(local_pos)
                cursor = (
                    Qt.PointingHandCursor
                    if index >= 0 and tab_bar.isTabEnabled(index)
                    else Qt.ArrowCursor
                )
                self._set_cursor(tab_bar, cursor, force=force)
                return
            editor = self._text_editor(widget)
            if editor is not None:
                # QTextEdit receives pointer events through its viewport. Set
                # both surfaces so transcript editing always shows an I-beam,
                # including immediately after a modal button was hovered.
                self._set_cursor(editor, Qt.IBeamCursor, force=force)
                viewport = getattr(editor, "viewport", lambda: None)()
                if viewport is not None:
                    self._set_cursor(viewport, Qt.IBeamCursor, force=force)
                return
            if self._ancestor(widget, QAbstractItemView) is not None:
                return
            if self._label_has_link(widget):
                self._set_cursor(widget, Qt.PointingHandCursor, force=force)
                return
            if isinstance(widget, QLabel) and bool(
                widget.textInteractionFlags() & Qt.TextSelectableByMouse
            ):
                self._set_cursor(widget, Qt.IBeamCursor, force=force)
                return
            self._set_cursor(widget, Qt.ArrowCursor, force=force)

        def apply_tree(self, root) -> None:
            widgets = root.findChildren(QWidget)
            if isinstance(root, QWidget):
                widgets.insert(0, root)
            for widget in widgets:
                if isinstance(widget, QTabBar):
                    widget.setMouseTracking(True)
                    widget.installEventFilter(self)
                    # A tab bar is predominantly a click target. MouseMove and
                    # Leave still restore Arrow over empty space, while this
                    # default avoids a stale Arrow before the first native
                    # Windows move event reaches a newly shown lazy page.
                    widget.setCursor(
                        Qt.PointingHandCursor
                        if any(widget.isTabEnabled(index) for index in range(widget.count()))
                        else Qt.ArrowCursor
                    )
                    continue
                self._normalize_surface(widget)

        def restore_after_modal(self) -> None:
            """Reclaim arrow after Windows destroys a hovered hand-cursor control."""
            def restore() -> None:
                # Force this even when Qt already reports ArrowCursor: Windows
                # can still be displaying the modal button's stale hand cursor.
                self._set_cursor(self._owner, Qt.ArrowCursor, force=True)
                app = QApplication.instance()
                if app is not None:
                    self._normalize_surface(app.widgetAt(QCursor.pos()), force=True)

            # Native Windows cursor state can be updated once more after the
            # modal event loop returns. Restore now and once on Qt's next turn.
            restore()
            QTimer.singleShot(0, restore)

        def eventFilter(self, watched, event) -> bool:
            if isinstance(watched, QAbstractButton) and event.type() in {
                QEvent.Show,
                QEvent.ShowToParent,
                QEvent.EnabledChange,
            }:
                self._apply(watched)
            elif isinstance(watched, QTabBar) and event.type() == QEvent.MouseMove:
                index = watched.tabAt(event.position().toPoint())
                cursor = (
                    Qt.PointingHandCursor
                    if index >= 0 and watched.isTabEnabled(index)
                    else Qt.ArrowCursor
                )
                self._set_cursor(watched, cursor)
            elif isinstance(watched, QTabBar) and event.type() == QEvent.Leave:
                self._set_cursor(watched, Qt.ArrowCursor, force=True)
            elif event.type() in {QEvent.Enter, QEvent.HoverEnter}:
                # Enter must refresh native state even when QWidget's logical
                # cursor already matches. This closes the Windows modal-teardown
                # gap without doing cursor work on every mouse-move event.
                self._normalize_surface(watched, force=True)
            return False

    return SettingsButtonCursorPolicy(parent)
