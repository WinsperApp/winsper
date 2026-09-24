from __future__ import annotations

import logging
import queue
import threading

from . import distribution
from .settings_helpers import friendly_check_error


LOGGER = logging.getLogger(__name__)


class SettingsUpdatePromptMixin:
    """One update-check and prompt flow shared by Settings and About."""

    def _init_settings_update_prompt(self) -> None:
        from PySide6.QtCore import QTimer

        self._settings_update_events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._settings_update_in_flight = False
        self._settings_update_manual_requested = False
        self._settings_update_check_button = None
        self._settings_update_status_label = None
        self._settings_update_info = None
        self._settings_update_dialog = None

        self._settings_update_timer = QTimer(self.window)
        self._settings_update_timer.setInterval(90)
        self._settings_update_timer.timeout.connect(self._poll_settings_update_events)

        # Let Settings paint first. The check itself runs off the UI thread.
        self._settings_update_open_timer = QTimer(self.window)
        self._settings_update_open_timer.setSingleShot(True)
        self._settings_update_open_timer.setInterval(350)
        self._settings_update_open_timer.timeout.connect(self._check_updates_when_settings_opens)

    def _bind_about_update_widgets(self, button, status_label) -> None:
        self._settings_update_check_button = button
        self._settings_update_status_label = status_label
        status_label.clear()
        status_label.hide()
        if distribution.uses_store_updates():
            button.setText("Open Microsoft Store")
            button.clicked.connect(self._open_store_updates)
            return
        button.clicked.connect(lambda: self._check_settings_update(manual=True))

    def _schedule_settings_open_update_check(self) -> None:
        if self._shutdown_started:
            return
        if distribution.uses_store_updates():
            return
        self._settings_update_open_timer.start()

    def _check_updates_when_settings_opens(self) -> None:
        self._check_settings_update(manual=False)

    def _open_store_updates(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if not QDesktopServices.openUrl(QUrl("ms-windows-store://downloadsandupdates")):
            self._show_toast("Could not open Microsoft Store", "bad")

    def _check_settings_update(self, *, manual: bool) -> None:
        if self._shutdown_started:
            return
        if manual:
            self._settings_update_open_timer.stop()
        if self._settings_update_in_flight:
            self._settings_update_manual_requested |= manual
            if manual:
                self._set_about_update_checking()
            return

        from . import __update_feed_url__

        feed_url = self.config.updates.feed_url.strip() or __update_feed_url__
        if not feed_url:
            if manual:
                self._show_toast("Update checks are unavailable in this build", "bad")
            return

        self._settings_update_in_flight = True
        self._settings_update_manual_requested = manual
        if manual:
            self._set_about_update_checking()
        self._settings_update_timer.start()

        def worker() -> None:
            try:
                from . import __release_channel__, __version__
                from . import updates as updates_module

                info = updates_module.check_for_update(feed_url, __version__)
                if info is not None and info.channel != __release_channel__:
                    raise ValueError("The update feed returned a different release channel")
                self._settings_update_events.put(
                    ("available", info) if info is not None else ("current", None)
                )
            except Exception as exc:
                self._settings_update_events.put(("error", exc))

        threading.Thread(
            target=worker,
            name="WinsperSettingsUpdateCheck",
            daemon=True,
        ).start()

    def _set_about_update_checking(self) -> None:
        button = self._settings_update_check_button
        status = self._settings_update_status_label
        try:
            if button is not None:
                button.setEnabled(False)
                button.setText("Checking...")
            if status is not None:
                status.setText("Checking for updates...")
                status.show()
        except RuntimeError:
            pass

    def _poll_settings_update_events(self) -> None:
        handled = False
        while True:
            try:
                kind, payload = self._settings_update_events.get_nowait()
            except queue.Empty:
                break
            handled = True
            manual = self._settings_update_manual_requested
            self._settings_update_manual_requested = False
            self._settings_update_in_flight = False
            self._restore_about_update_button()

            if kind == "available":
                info = payload
                self._set_about_update_status(f"Version {info.version} is available")
                self._show_update_available_dialog(info)
            elif kind == "current":
                self._hide_settings_update_dialog()
                if manual:
                    message = "You're on the latest version"
                    self._set_about_update_status(message)
                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(
                        1800,
                        lambda expected=message: self._hide_about_update_status(expected),
                    )
                else:
                    self._clear_about_update_status()
            else:
                self._clear_about_update_status()
                if manual:
                    self._show_toast(
                        f"Could not check: {friendly_check_error(payload)}",
                        "bad",
                    )
                else:
                    LOGGER.warning("Settings update check failed: %s", payload)

        if handled and not self._settings_update_in_flight:
            self._settings_update_timer.stop()

    def _restore_about_update_button(self) -> None:
        try:
            if self._settings_update_check_button is not None:
                self._settings_update_check_button.setEnabled(True)
                self._settings_update_check_button.setText("Check for updates")
        except RuntimeError:
            pass

    def _set_about_update_status(self, text: str) -> None:
        try:
            if self._settings_update_status_label is not None:
                self._settings_update_status_label.setText(text)
                self._settings_update_status_label.show()
        except RuntimeError:
            pass

    def _clear_about_update_status(self) -> None:
        try:
            if self._settings_update_status_label is not None:
                self._settings_update_status_label.clear()
                self._settings_update_status_label.hide()
        except RuntimeError:
            pass

    def _hide_about_update_status(self, expected: str) -> None:
        try:
            status = self._settings_update_status_label
            if status is not None and status.text() == expected:
                status.clear()
                status.hide()
        except RuntimeError:
            pass

    def _show_update_available_dialog(self, info) -> None:
        from PySide6.QtCore import QEvent, QPointF, QSize, Qt, QTimer
        from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
        from PySide6.QtWidgets import (
            QDialog,
            QFrame,
            QGraphicsDropShadowEffect,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QVBoxLayout,
        )

        from .branding import logo_pixmap
        from .settings_icons import settings_nav_icon

        class UpdateDialog(QDialog):
            def center_on_owner(dialog_self) -> None:
                owner = dialog_self.parentWidget()
                target = (
                    owner.window().frameGeometry()
                    if owner is not None
                    else dialog_self.screen().availableGeometry()
                )
                frame = dialog_self.frameGeometry()
                frame.moveCenter(target.center())
                dialog_self.move(frame.topLeft())

            def showEvent(dialog_self, event) -> None:
                super().showEvent(event)
                dialog_self.center_on_owner()
                QTimer.singleShot(0, dialog_self.center_on_owner)

        class UpdateDragHeader(QFrame):
            def __init__(header_self, parent=None) -> None:
                super().__init__(parent)
                header_self._drag_offset = None

            def add_drag_target(header_self, widget) -> None:
                widget.installEventFilter(header_self)

            def _begin_drag(header_self, event) -> bool:
                if event.button() != Qt.LeftButton:
                    return False
                window = header_self.window()
                header_self._drag_offset = (
                    event.globalPosition().toPoint()
                    - window.frameGeometry().topLeft()
                )
                event.accept()
                return True

            def _continue_drag(header_self, event) -> bool:
                if (
                    header_self._drag_offset is None
                    or not event.buttons() & Qt.LeftButton
                ):
                    return False
                header_self.window().move(
                    event.globalPosition().toPoint() - header_self._drag_offset
                )
                event.accept()
                return True

            def _end_drag(header_self, event) -> bool:
                if (
                    event.button() != Qt.LeftButton
                    or header_self._drag_offset is None
                ):
                    return False
                header_self._drag_offset = None
                event.accept()
                return True

            def mousePressEvent(header_self, event) -> None:
                if header_self._begin_drag(event):
                    return
                super().mousePressEvent(event)

            def mouseMoveEvent(header_self, event) -> None:
                if header_self._continue_drag(event):
                    return
                super().mouseMoveEvent(event)

            def mouseReleaseEvent(header_self, event) -> None:
                if header_self._end_drag(event):
                    return
                super().mouseReleaseEvent(event)

            def eventFilter(header_self, watched, event) -> bool:
                event_type = event.type()
                if event_type == QEvent.MouseButtonPress:
                    return header_self._begin_drag(event)
                if event_type == QEvent.MouseMove:
                    return header_self._continue_drag(event)
                if event_type == QEvent.MouseButtonRelease:
                    return header_self._end_drag(event)
                return super().eventFilter(watched, event)

        class UpdateCloseButton(QPushButton):
            def __init__(button_self, normal_color: str, parent=None) -> None:
                super().__init__(parent)
                button_self._normal_color = QColor(normal_color)
                button_self._hovered = False
                button_self.setAttribute(Qt.WA_Hover, True)

            def enterEvent(button_self, event) -> None:
                button_self._hovered = True
                super().enterEvent(event)
                button_self.update()

            def leaveEvent(button_self, event) -> None:
                button_self._hovered = False
                super().leaveEvent(event)
                button_self.update()

            def paintEvent(button_self, event) -> None:
                super().paintEvent(event)
                painter = QPainter(button_self)
                painter.setRenderHint(QPainter.Antialiasing)
                color = (
                    QColor("#ffffff")
                    if button_self._hovered or button_self.isDown()
                    else button_self._normal_color
                )
                painter.setPen(
                    QPen(color, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                )
                center = QPointF(button_self.rect().center())
                radius = 4.5
                painter.drawLine(
                    QPointF(center.x() - radius, center.y() - radius),
                    QPointF(center.x() + radius, center.y() + radius),
                )
                painter.drawLine(
                    QPointF(center.x() + radius, center.y() - radius),
                    QPointF(center.x() - radius, center.y() + radius),
                )

        self._hide_settings_update_dialog()
        self._settings_update_info = info

        dialog = UpdateDialog(self.window)
        dialog.setObjectName("SettingsUpdateDialog")
        dialog.setWindowTitle("Winsper update")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        dialog.setAttribute(Qt.WA_TranslucentBackground)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setFixedWidth(650)

        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(18, 18, 18, 18)

        shell = QFrame()
        shell.setObjectName("SettingsUpdateDialogShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(30, 22, 30, 24)
        shell_layout.setSpacing(0)
        outer.addWidget(shell)

        shadow = QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(self.palette.shadow))
        shell.setGraphicsEffect(shadow)

        header_frame = UpdateDragHeader()
        header_frame.setObjectName("SettingsUpdateDragHeader")
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(9)
        logo = QLabel()
        logo.setObjectName("SettingsUpdateHeaderLogo")
        logo.setFixedSize(22, 22)
        logo.setPixmap(logo_pixmap(QPixmap, 22))
        logo.setAlignment(Qt.AlignCenter)
        header.addWidget(logo)
        header_title = QLabel("Winsper update")
        header_title.setObjectName("SettingsUpdateHeaderTitle")
        header.addWidget(header_title)
        header_frame.add_drag_target(logo)
        header_frame.add_drag_target(header_title)
        header.addStretch(1)
        close_button = UpdateCloseButton(self.palette.muted)
        close_button.setObjectName("SettingsUpdateClose")
        close_button.setAccessibleName("Close update")
        close_button.setFocusPolicy(Qt.NoFocus)
        close_button.clicked.connect(dialog.close)
        header.addWidget(close_button, 0, Qt.AlignTop | Qt.AlignRight)
        # Polish after parenting so inherited QSS cannot later replace the
        # close target's explicit square geometry.
        close_button.ensurePolished()
        close_button.setFixedSize(34, 34)
        shell_layout.addWidget(header_frame)
        shell_layout.addSpacing(18)

        hero = QHBoxLayout()
        hero.setSpacing(18)
        hero_icon = QLabel()
        hero_icon.setObjectName("SettingsUpdateHeroIcon")
        hero_icon.setFixedSize(64, 64)
        hero_icon.setAlignment(Qt.AlignCenter)
        hero_icon.setPixmap(
            settings_nav_icon("update", self.palette.accent, 27).pixmap(QSize(27, 27))
        )
        hero.addWidget(hero_icon, 0, Qt.AlignTop)

        hero_copy = QVBoxLayout()
        hero_copy.setSpacing(5)
        title = QLabel("Update available")
        title.setObjectName("SettingsUpdateTitle")
        hero_copy.addWidget(title)

        version_row = QHBoxLayout()
        version_row.setSpacing(4)
        version_row.addWidget(self._update_dialog_label("Winsper", "SettingsUpdateVersion"))
        version_row.addWidget(
            self._update_dialog_label(str(info.version), "SettingsUpdateVersionAccent")
        )
        version_row.addWidget(
            self._update_dialog_label("is ready to download.", "SettingsUpdateVersion")
        )
        version_row.addStretch(1)
        hero_copy.addLayout(version_row)
        hero.addLayout(hero_copy, 1)
        shell_layout.addLayout(hero)
        shell_layout.addSpacing(22)

        changes = QFrame()
        changes.setObjectName("SettingsUpdateChanges")
        changes_layout = QVBoxLayout(changes)
        changes_layout.setContentsMargins(20, 17, 20, 17)
        changes_layout.setSpacing(15)
        for row_title, row_detail in self._release_note_rows(info.notes):
            row = QFrame()
            row.setObjectName("SettingsUpdateChangeRow")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(3)
            title_label = QLabel(row_title)
            title_label.setObjectName("SettingsUpdateChangeTitle")
            detail_label = QLabel(row_detail)
            detail_label.setObjectName("SettingsUpdateChangeDetail")
            detail_label.setWordWrap(True)
            row_layout.addWidget(title_label)
            row_layout.addWidget(detail_label)
            changes_layout.addWidget(row)
        shell_layout.addWidget(changes)
        shell_layout.addSpacing(16)

        divider = QFrame()
        divider.setObjectName("SettingsUpdateDivider")
        divider.setFixedHeight(1)
        shell_layout.addWidget(divider)
        shell_layout.addSpacing(16)

        actions = QHBoxLayout()
        actions.setSpacing(14)
        later_button = QPushButton("Remind me later")
        later_button.setObjectName("SettingsUpdateLater")
        later_button.setFixedHeight(46)
        later_button.clicked.connect(dialog.close)
        actions.addWidget(later_button, 1)
        download_button = QPushButton("Download update")
        download_button.setObjectName("SettingsUpdateDownload")
        download_button.setFixedHeight(46)
        download_button.setIcon(
            settings_nav_icon("download", "#FFFFFF", 17)
        )
        download_button.setIconSize(QSize(17, 17))
        download_button.clicked.connect(self._open_settings_update_download)
        actions.addWidget(download_button, 1)
        shell_layout.addLayout(actions)
        shell_layout.addSpacing(15)

        footer = QHBoxLayout()
        footer.setSpacing(7)
        footer.addStretch(1)
        footer_icon = QLabel()
        footer_icon.setObjectName("SettingsUpdateFooterIcon")
        footer_icon.setPixmap(
            settings_nav_icon("privacy", self.palette.muted, 15).pixmap(QSize(15, 15))
        )
        footer.addWidget(footer_icon)
        size = self._format_update_size(getattr(info, "size_bytes", 0))
        footer_text = "Secure download"
        if size:
            footer_text += f"  \u00b7  Size: {size}"
        footer_label = QLabel(footer_text)
        footer_label.setObjectName("SettingsUpdateFooter")
        footer.addWidget(footer_label)
        footer.addStretch(1)
        shell_layout.addLayout(footer)

        def clear_dialog() -> None:
            if self._settings_update_dialog is dialog:
                self._settings_update_dialog = None
            self._modal_dialogs.pop("update", None)

        dialog.finished.connect(clear_dialog)
        self._settings_update_dialog = dialog
        self._modal_dialogs["update"] = dialog
        self._button_cursor_policy.apply_tree(dialog)

        dialog.adjustSize()
        dialog.center_on_owner()
        dialog.open()

    @staticmethod
    def _update_dialog_label(text: str, object_name: str):
        from PySide6.QtWidgets import QLabel

        label = QLabel(text)
        label.setObjectName(object_name)
        return label

    @staticmethod
    def _release_note_rows(notes: str) -> list[tuple[str, str]]:
        paragraphs = [
            [line.strip() for line in paragraph.splitlines() if line.strip()]
            for paragraph in (notes or "").split("\n\n")
            if paragraph.strip()
        ]
        rows: list[tuple[str, str]] = []
        for lines in paragraphs[:3]:
            if len(lines) > 1:
                rows.append((lines[0], " ".join(lines[1:])))
            elif ":" in lines[0]:
                title, detail = lines[0].split(":", 1)
                rows.append((title.strip(), detail.strip()))
            else:
                rows.append(("What's new", lines[0]))
        return rows or [
            ("Product improvements", "A faster, smoother Winsper experience."),
            ("More reliable", "Bug fixes and stability improvements."),
        ]

    @staticmethod
    def _format_update_size(size_bytes: int) -> str:
        if not size_bytes:
            return ""
        return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _hide_settings_update_dialog(self) -> None:
        dialog = self._settings_update_dialog
        if dialog is not None:
            dialog.close()

    def _open_settings_update_download(self) -> None:
        info = self._settings_update_info
        if info is None:
            return

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        try:
            from . import __download_page_url__
            from .updates import manual_download_url

            destination = manual_download_url(info, __download_page_url__)
        except Exception:
            self._show_toast("Could not prepare the download page", "bad")
            return
        if not QDesktopServices.openUrl(QUrl(destination)):
            self._show_toast("Could not open the download page", "bad")
            return
        self._hide_settings_update_dialog()

    def _shutdown_settings_update_prompt(self) -> None:
        self._settings_update_open_timer.stop()
        self._settings_update_timer.stop()
        self._settings_update_in_flight = False
        self._settings_update_manual_requested = False
        self._hide_settings_update_dialog()
