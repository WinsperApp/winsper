from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

import pytest


pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(
        os.environ.get("WINSPER_REAL_TESTS") != "1",
        reason="Set WINSPER_REAL_TESTS=1 to run real Windows cursor tests.",
    ),
    pytest.mark.skipif(not sys.platform.startswith("win"), reason="Real cursor tests require Windows."),
]


class _CursorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("ptScreenPos", wintypes.POINT),
    ]


def _system_cursor_handle() -> int:
    info = _CursorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(info)):
        raise ctypes.WinError()
    return int(info.hCursor or 0)


def test_settings_dropdown_scopes_hand_cursor_to_option_rows() -> None:
    """Prove the open picker does not leak its hand cursor across Windows."""
    os.environ["QT_QPA_PLATFORM"] = "windows"

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    from voicepilot.settings_widgets import create_settings_combo
    from voicepilot.theme import get_palette

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.setWindowTitle("Winsper cursor regression")
    window.resize(520, 260)
    layout = QVBoxLayout(window)
    neutral = QLabel("Neutral Settings content")
    neutral.setMinimumHeight(100)
    neutral.setCursor(Qt.ArrowCursor)
    combo = create_settings_combo(lambda: get_palette("dark"))
    combo.addItems(["System", "Light", "Dark"])
    layout.addWidget(neutral)
    layout.addWidget(combo)

    original_position = QCursor.pos()
    try:
        window.show()
        window.raise_()
        window.activateWindow()
        QTest.qWaitForWindowExposed(window)

        neutral_point = neutral.mapToGlobal(neutral.rect().center())
        QCursor.setPos(neutral_point)
        QTest.qWait(80)
        # Qt owns native cursor handles; they need not equal Win32's stock
        # LoadCursor handles. Compare the actual pre/post handles instead.
        arrow_handle = _system_cursor_handle()

        combo.showPopup()
        QTest.qWait(80)
        assert combo._settings_popup.isVisible()

        option_index = combo.model().index(1, 0)
        option_rect = combo.view().visualRect(option_index)
        option_point = combo.view().viewport().mapToGlobal(option_rect.center())
        QCursor.setPos(option_point)
        QTest.qWait(80)
        hand_handle = _system_cursor_handle()
        assert hand_handle != arrow_handle

        # This is the reported failure: the popup remains open, but moving
        # over unrelated Settings content must restore the Windows arrow.
        QCursor.setPos(neutral_point)
        QTest.qWait(80)
        assert combo._settings_popup.isVisible()
        assert _system_cursor_handle() == arrow_handle
    finally:
        combo.hidePopup()
        window.close()
        QCursor.setPos(original_position)
        app.processEvents()


def test_settings_confirmation_releases_native_hand_cursor() -> None:
    """Closing a hovered modal button must restore Windows' native arrow."""
    os.environ["QT_QPA_PLATFORM"] = "windows"

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton

    from voicepilot.settings_dialogs import confirm_settings_action
    from voicepilot.settings_widgets import create_settings_button_cursor_policy
    from voicepilot.theme import get_palette

    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.setWindowTitle("Winsper modal cursor regression")
    window.resize(640, 420)
    neutral = QLabel("Neutral Settings content")
    window.setCentralWidget(neutral)
    policy = create_settings_button_cursor_policy(window)
    window._winsper_cursor_policy = policy
    app.installEventFilter(policy)
    original_position = QCursor.pos()

    def hover_confirm_then_close() -> None:
        dialog = app.activeModalWidget()
        assert dialog is not None
        confirm = dialog.findChild(QPushButton, "SettingsConfirmAccept")
        assert confirm is not None
        QCursor.setPos(confirm.mapToGlobal(confirm.rect().center()))
        QTimer.singleShot(90, dialog.reject)

    try:
        window.show()
        window.raise_()
        window.activateWindow()
        QTest.qWaitForWindowExposed(window)
        policy.apply_tree(window)
        QCursor.setPos(neutral.mapToGlobal(neutral.rect().center()))
        QTest.qWait(80)
        arrow_handle = _system_cursor_handle()
        QTimer.singleShot(80, hover_confirm_then_close)
        confirm_settings_action(
            window,
            get_palette("dark"),
            title="Test confirmation",
            message="Close this modal.",
            confirm_label="Save",
        )
        QTest.qWait(100)
        assert _system_cursor_handle() == arrow_handle
    finally:
        app.removeEventFilter(policy)
        window.close()
        QCursor.setPos(original_position)
        app.processEvents()
