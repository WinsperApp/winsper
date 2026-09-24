from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from voicepilot.config import AppConfig, save_config


def test_settings_tabs_show_hand_only_over_clickable_tabs():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QTabWidget
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with patch.object(SettingsWindow, "_refresh_home_status"):
            window = SettingsWindow(path)

        window.show()
        window._show_named_page("Personalize")
        app.processEvents()
        tabs = window.stack.currentWidget().findChild(QTabWidget, "PersonalizeTabs")
        assert tabs is not None
        bar = tabs.tabBar()

        blank = QPoint(bar.width() - 1, bar.height() - 1)
        if bar.tabAt(blank) < 0:
            QTest.mouseMove(bar, blank)
            app.processEvents()
            assert bar.cursor().shape() == Qt.ArrowCursor

        QTest.mouseMove(bar, bar.tabRect(0).center())
        app.processEvents()
        assert bar.cursor().shape() == Qt.PointingHandCursor
        window.close()
    app.processEvents()
