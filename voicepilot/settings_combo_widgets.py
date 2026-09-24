from __future__ import annotations

SETTINGS_COMBO_WIDTH = 290
SETTINGS_COMBO_HEIGHT = 44


def create_settings_combo(
    palette_getter,
    *,
    object_name: str = "SettingsCombo",
    accessible_name: str = "",
):
    """Create Winsper's single-surface, keyboard-accessible Settings picker."""
    from PySide6.QtCore import QElapsedTimer, QEvent, QPoint, QSize, Qt
    from PySide6.QtGui import (
        QColor,
        QFont,
        QFontMetrics,
        QKeyEvent,
        QMouseEvent,
        QPainter,
        QPainterPath,
        QPen,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFrame,
        QListView,
        QStyle,
        QStyledItemDelegate,
        QStyleOptionViewItem,
        QVBoxLayout,
    )

    class SettingsOptionDelegate(QStyledItemDelegate):
        def sizeHint(self, option, index):
            return QSize(max(176, option.rect.width()), 40)

        def paint(self, painter: QPainter, option, index) -> None:
            palette = palette_getter()
            combo = self.parent()
            row_rect = option.rect.adjusted(6, 3, -6, -3)
            current = index.row() == combo.currentIndex()
            hovered = bool(option.state & QStyle.State_MouseOver) or (
                index.row() == combo.view().hovered_row
            )

            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            if current or hovered:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(palette.surface_3))
                painter.drawRoundedRect(row_rect, 8, 8)

            font = option.font
            font.setWeight(QFont.DemiBold if current else QFont.Normal)
            painter.setFont(font)
            painter.setPen(QColor(palette.text))
            text_rect = row_rect.adjusted(12, 0, -38, 0)
            text = QFontMetrics(font).elidedText(str(index.data() or ""), Qt.ElideRight, text_rect.width())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)

            if current:
                center_x = row_rect.right() - 18
                center_y = row_rect.center().y()
                check = QPainterPath()
                check.moveTo(center_x - 5, center_y)
                check.lineTo(center_x - 1, center_y + 4)
                check.lineTo(center_x + 6, center_y - 5)
                painter.setPen(QPen(QColor(palette.accent), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.drawPath(check)
            painter.restore()

    class SettingsPopupList(QListView):
        def __init__(self, owner, parent):
            super().__init__(parent)
            self._owner = owner
            self._hovered_row = -1
            self.setMouseTracking(True)
            self.setAttribute(Qt.WA_Hover, True)
            self.viewport().setMouseTracking(True)
            self.viewport().setAttribute(Qt.WA_Hover, True)
            self.entered.connect(self._set_hovered_index)
            self.viewportEntered.connect(self._clear_hover)
            self._update_cursor(False)

        @property
        def hovered_row(self) -> int:
            return self._hovered_row

        def _set_hovered_index(self, index) -> None:
            enabled = bool(index.isValid() and index.flags() & Qt.ItemIsEnabled)
            self._set_hovered_row(index.row() if enabled else -1)
            self._update_cursor(enabled)

        def _clear_hover(self) -> None:
            self._set_hovered_row(-1)
            self._update_cursor(False)

        def _update_cursor(self, over_enabled_item: bool) -> None:
            cursor = Qt.PointingHandCursor if over_enabled_item else Qt.ArrowCursor
            # Keep the container neutral and scope the hand to concrete rows.
            self.setCursor(Qt.ArrowCursor)
            self.viewport().setCursor(cursor)

        def _set_hovered_row(self, row: int) -> None:
            if row != self._hovered_row:
                self._hovered_row = row
                self.viewport().update()

        def mouseMoveEvent(self, event) -> None:
            index = self.indexAt(event.position().toPoint())
            self._set_hovered_index(index)
            super().mouseMoveEvent(event)

        def leaveEvent(self, event) -> None:
            self._clear_hover()
            super().leaveEvent(event)

        def keyPressEvent(self, event: QKeyEvent) -> None:
            if event.key() in {Qt.Key_Return, Qt.Key_Enter}:
                self._owner._choose_popup_index(self.currentIndex())
                event.accept()
                return
            if event.key() in {Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab}:
                self._owner.hidePopup()
                self._owner.setFocus()
                event.accept()
                return
            super().keyPressEvent(event)

    class SettingsPopup(QFrame):
        """Non-grabbing picker surface with explicit outside-click dismissal."""

        def __init__(self, owner):
            # Qt.Popup grabs the Windows pointer. Once an option selects the
            # hand cursor, that grab can leak the hand across unrelated UI.
            # Qt.Tool keeps the same independent surface without mouse capture.
            super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            self._owner = owner
            self.setCursor(Qt.ArrowCursor)
            self.setMouseTracking(True)
            self.setFocusPolicy(Qt.StrongFocus)

        def showEvent(self, event) -> None:
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
            super().showEvent(event)

        def hideEvent(self, event) -> None:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self._owner._popup_was_hidden()
            super().hideEvent(event)

        def eventFilter(self, watched, event) -> bool:
            if not self.isVisible():
                return super().eventFilter(watched, event)
            if event.type() in {QEvent.MouseMove, QEvent.HoverMove}:
                point = event.globalPosition().toPoint()
                view = self._owner._settings_view
                local = view.viewport().mapFromGlobal(point)
                if view.viewport().rect().contains(local):
                    view._set_hovered_index(view.indexAt(local))
                else:
                    view._clear_hover()
            elif event.type() == QEvent.MouseButtonPress:
                point = event.globalPosition().toPoint()
                inside_popup = self.geometry().contains(point)
                owner_point = self._owner.mapFromGlobal(point)
                inside_owner = self._owner.rect().contains(owner_point)
                if not inside_popup and not inside_owner:
                    self._owner.hidePopup()
            elif event.type() == QEvent.ApplicationDeactivate:
                self._owner.hidePopup()
            return super().eventFilter(watched, event)

        def mouseMoveEvent(self, event) -> None:
            view = getattr(self._owner, "_settings_view", None)
            if view is not None:
                local = view.viewport().mapFromGlobal(event.globalPosition().toPoint())
                if not view.viewport().rect().contains(local):
                    view._clear_hover()
            super().mouseMoveEvent(event)

        def leaveEvent(self, event) -> None:
            view = getattr(self._owner, "_settings_view", None)
            if view is not None:
                view._clear_hover()
            super().leaveEvent(event)

    class SettingsComboBox(QComboBox):
        def __init__(self):
            super().__init__()
            self.setObjectName(object_name)
            self.setFixedSize(SETTINGS_COMBO_WIDTH, SETTINGS_COMBO_HEIGHT)
            # The closed field and concrete option rows are interactive.
            # The surrounding page and popup container remain neutral.
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.StrongFocus)
            if accessible_name:
                self.setAccessibleName(accessible_name)

            # Remember dismissal so an owner click that closes the separate
            # tool surface cannot reopen it during the same event turn.
            self._popup_hide_timer = QElapsedTimer()
            self._popup_hide_timer.invalidate()
            popup = SettingsPopup(self)
            popup.setObjectName("SettingsComboPopup")
            popup.setAttribute(Qt.WA_TranslucentBackground, True)
            popup.setAutoFillBackground(False)
            popup_layout = QVBoxLayout(popup)
            popup_layout.setContentsMargins(0, 0, 0, 0)

            view = SettingsPopupList(self, popup)
            view.setObjectName("SettingsComboPopupList")
            view.setFrameShape(QListView.NoFrame)
            view.setUniformItemSizes(True)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            view.setModel(self.model())
            self._settings_delegate = SettingsOptionDelegate(self)
            self.setItemDelegate(self._settings_delegate)
            view.setItemDelegate(self._settings_delegate)
            view.clicked.connect(self._choose_popup_index)
            view.activated.connect(self._choose_popup_index)
            popup_layout.addWidget(view)

            self._settings_popup = popup
            self._settings_view = view

        def _popup_was_hidden(self) -> None:
            self._popup_hide_timer.start()
            self._settings_view._clear_hover()

        def view(self):
            """Return the custom popup view for tests and accessibility tooling."""
            return self._settings_view

        def _choose_popup_index(self, index) -> None:
            if index.isValid():
                self.setCurrentIndex(index.row())
            self.hidePopup()
            self.setFocus()

        def hidePopup(self) -> None:
            self._settings_popup.hide()
            self._settings_view._clear_hover()

        def showPopup(self) -> None:
            if not self.count():
                return
            self._popup_hide_timer.invalidate()
            row_height = self._settings_view.itemDelegate().sizeHint(
                QStyleOptionViewItem(), self.model().index(0, 0)
            ).height()
            visible_rows = min(self.count(), 8)
            popup_height = (row_height * visible_rows) + 2
            self._settings_view.setCurrentIndex(self.model().index(self.currentIndex(), 0))
            self._position_popup(popup_height)
            self._settings_popup.show()
            self._settings_popup.raise_()
            # Keep empty popup space neutral. SettingsPopupList changes the
            # cursor to a hand only while the pointer is over an enabled row.
            self._settings_view._clear_hover()
            self._settings_view.scrollTo(self._settings_view.currentIndex())
            self._settings_view.setFocus(Qt.PopupFocusReason)

        def mousePressEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.LeftButton:
                if self._settings_popup.isVisible():
                    self.hidePopup()
                    self.setFocus(Qt.MouseFocusReason)
                elif self._popup_hide_timer.isValid() and self._popup_hide_timer.elapsed() < 250:
                    # The tool surface already closed itself for this same
                    # click. Consume the owner event; reopening here creates
                    # the apparent "arrow will not collapse" bug.
                    self._popup_hide_timer.invalidate()
                    self.setFocus(Qt.MouseFocusReason)
                else:
                    self.showPopup()
                event.accept()
                return
            super().mousePressEvent(event)

        def wheelEvent(self, event) -> None:
            """Keep page scrolling from changing a focused setting."""
            event.ignore()

        def _position_popup(self, popup_height: int) -> None:
            popup = self._settings_popup
            popup.setWindowFlag(Qt.FramelessWindowHint, True)
            popup.setWindowFlag(Qt.NoDropShadowWindowHint, True)
            anchor = self.mapToGlobal(QPoint(0, self.height() + 6))
            screen = QApplication.screenAt(anchor) or self.screen()
            available = screen.availableGeometry()
            x = max(available.left(), min(anchor.x(), available.right() - self.width() + 1))
            y = anchor.y()
            if y + popup_height > available.bottom():
                y = self.mapToGlobal(QPoint(0, -popup_height - 6)).y()
            popup.setGeometry(x, y, self.width(), popup_height)

    return SettingsComboBox()


def create_theme_combo(palette_getter):
    """Compatibility wrapper for the General-page appearance picker."""
    return create_settings_combo(
        palette_getter,
        object_name="AppearanceCombo",
        accessible_name="Appearance theme",
    )
