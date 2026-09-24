import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from voicepilot.config import AppConfig, save_config
from voicepilot.updates import UpdateInfo


def _build_settings_window(path: Path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    save_config(AppConfig(), path)
    with patch.object(SettingsWindow, "_refresh_home_status"):
        window = SettingsWindow(path)
    return app, window


def test_about_update_button_uses_shared_manual_check_without_secure_copy():
    from PySide6.QtWidgets import QLabel, QPushButton

    with tempfile.TemporaryDirectory() as temp:
        app, window = _build_settings_window(Path(temp) / "config.yaml")
        window._show_named_page("About")
        page = window.stack.currentWidget()
        check_button = next(
            button
            for button in page.findChildren(QPushButton)
            if button.text() == "Check for updates"
        )

        calls = []
        window._check_settings_update = lambda *, manual: calls.append(manual)
        check_button.click()
        app.processEvents()

        visible_copy = " ".join(
            [
                *(label.text() for label in page.findChildren(QLabel)),
                *(button.text() for button in page.findChildren(QPushButton)),
            ]
        ).lower()
        assert calls == [True]
        assert "secure update" not in visible_copy
        assert "securely" not in visible_copy
        window.close()
        app.processEvents()


def test_settings_open_schedules_silent_update_check():
    with tempfile.TemporaryDirectory() as temp:
        app, window = _build_settings_window(Path(temp) / "config.yaml")
        calls = []
        window._check_settings_update = lambda *, manual: calls.append(manual)

        window.show()
        assert window._settings_update_open_timer.isActive()
        window._settings_update_open_timer.stop()
        window._check_updates_when_settings_opens()

        assert calls == [False]

        window.window.hide()
        window.show()
        assert window._settings_update_open_timer.isActive()
        window.close()
        app.processEvents()


def test_update_available_dialog_shows_text_only_release_rows():
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtWidgets import QFrame, QLabel, QPushButton

    with tempfile.TemporaryDirectory() as temp:
        app, window = _build_settings_window(Path(temp) / "config.yaml")
        info = UpdateInfo(
            version="9.9.9",
            installer_url="https://downloads.winsper.app/WinsperSetup.exe",
            sha256="a" * 64,
            notes=(
                "Performance improvements\n"
                "Faster startup and smoother transcription.\n\n"
                "More reliable\n"
                "Better device handling."
            ),
            download_page_url="https://winsper.app/download",
            size_bytes=82_208_358,
        )

        window._show_update_available_dialog(info)
        app.processEvents()
        dialog = window._settings_update_dialog
        card_copy = " ".join(
            label.text() for label in dialog.findChildren(QLabel)
        )
        button_copy = {
            button.text() for button in dialog.findChildren(QPushButton)
        }
        close_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.objectName() == "SettingsUpdateClose"
        )
        action_buttons = {
            button.objectName(): button
            for button in dialog.findChildren(QPushButton)
            if button.objectName()
            in {"SettingsUpdateLater", "SettingsUpdateDownload"}
        }

        assert dialog.isVisible()
        assert "Winsper 9.9.9 is ready to download." in card_copy
        assert "Performance improvements" in card_copy
        assert "Faster startup and smoother transcription." in card_copy
        assert "More reliable" in card_copy
        assert "Better device handling." in card_copy
        assert "Size: 78.4 MB" in card_copy
        assert {"Remind me later", "Download update"} <= button_copy
        assert close_button.text() == ""
        assert close_button.icon().isNull()
        assert type(close_button).__name__ == "UpdateCloseButton"
        assert close_button._hovered is False
        assert close_button.focusPolicy() == Qt.NoFocus
        assert close_button.size().width() == close_button.size().height() == 34
        assert dialog.findChild(QFrame, "SettingsUpdateDragHeader") is not None
        assert abs(
            dialog.frameGeometry().center().x()
            - window.window.frameGeometry().center().x()
        ) <= 1
        assert abs(
            dialog.frameGeometry().center().y()
            - window.window.frameGeometry().center().y()
        ) <= 1
        assert {
            name: button.height() for name, button in action_buttons.items()
        } == {
            "SettingsUpdateLater": 46,
            "SettingsUpdateDownload": 46,
        }
        assert not any(
            label.objectName() == "SettingsUpdateChangeIcon"
            for label in dialog.findChildren(QLabel)
        )

        class MouseEvent:
            def __init__(self, event_type, button, buttons, global_pos):
                self._event_type = event_type
                self._button = button
                self._buttons = buttons
                self._global_pos = global_pos

            def type(self):
                return self._event_type

            def button(self):
                return self._button

            def buttons(self):
                return self._buttons

            def globalPosition(self):
                return QPointF(self._global_pos)

            def accept(self):
                pass

        drag_header = dialog.findChild(QFrame, "SettingsUpdateDragHeader")
        header_title = dialog.findChild(QLabel, "SettingsUpdateHeaderTitle")
        start = dialog.frameGeometry().topLeft()
        press_at = header_title.mapToGlobal(QPoint(4, 4))
        assert drag_header.eventFilter(
            header_title,
            MouseEvent(
                QEvent.MouseButtonPress,
                Qt.LeftButton,
                Qt.LeftButton,
                press_at,
            ),
        )
        assert drag_header.eventFilter(
            header_title,
            MouseEvent(
                QEvent.MouseMove,
                Qt.NoButton,
                Qt.LeftButton,
                press_at + QPoint(31, 19),
            ),
        )
        assert dialog.frameGeometry().topLeft() == start + QPoint(31, 19)
        assert drag_header.eventFilter(
            header_title,
            MouseEvent(
                QEvent.MouseButtonRelease,
                Qt.LeftButton,
                Qt.NoButton,
                press_at + QPoint(31, 19),
            ),
        )
        assert drag_header._drag_offset is None

        window._hide_settings_update_dialog()
        app.processEvents()
        assert window._settings_update_dialog is None
        window.close()
        app.processEvents()
