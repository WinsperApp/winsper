import json
from unittest.mock import patch

import pytest

from voicepilot.config import AppConfig
from voicepilot.tray import WinsperTray
from voicepilot.updates import UpdateInfo, manual_download_url, parse_update_manifest


class _FakeIcon:
    def __init__(self):
        self.menu = None
        self.updated = 0
        self.notifications = []

    def update_menu(self):
        self.updated += 1

    def notify(self, message, title):
        self.notifications.append((title, message))


def test_stable_tray_ignores_early_access_manifest():
    tray = WinsperTray.__new__(WinsperTray)
    tray.config = AppConfig()
    tray.config.updates.feed_url = ""
    tray._stopping = False
    tray._update_info = None
    tray._icon = _FakeIcon()
    tray._build_menu = lambda: "updated menu"
    info = UpdateInfo(
        "0.3.0",
        "https://winsper.app/downloads/WinsperSetup-0.3.0-early-access.exe",
        "a" * 64,
        download_page_url="https://winsper.app/download/",
        channel="early-access",
    )

    with patch("voicepilot.tray.check_for_update", return_value=info) as check:
        tray._check_for_updates()

    check.assert_called_once()
    assert tray._update_info is None
    assert tray._icon.menu is None
    assert tray._icon.updated == 0
    assert tray._icon.notifications == []

    with patch("voicepilot.tray.webbrowser.open") as opened:
        tray._open_update_page()
    opened.assert_not_called()


def test_stable_tray_notifies_for_matching_stable_manifest():
    tray = WinsperTray.__new__(WinsperTray)
    tray.config = AppConfig()
    tray._stopping = False
    tray._update_info = None
    tray._icon = _FakeIcon()
    tray._build_menu = lambda: "updated menu"
    info = UpdateInfo(
        "1.0.1",
        "https://winsper.app/downloads/WinsperSetup-1.0.1.exe",
        "a" * 64,
        download_page_url="https://winsper.app/download/",
        channel="stable",
    )

    with patch("voicepilot.tray.check_for_update", return_value=info):
        tray._check_for_updates()

    assert tray._update_info == info
    assert tray._icon.updated == 1
    assert tray._icon.notifications == [
        ("Winsper update available", "Winsper 1.0.1 is ready to download from winsper.app.")
    ]


def test_early_access_manifest_uses_manual_https_download_page():
    payload = json.dumps(
        {
            "version": "0.3.0",
            "installer_url": "https://winsper.app/downloads/WinsperSetup-0.3.0-early-access.exe",
            "download_page_url": "https://winsper.app/download/",
            "sha256": "b" * 64,
            "channel": "early-access",
            "size_bytes": 123456,
        }
    ).encode()
    info = parse_update_manifest(payload)
    assert info.channel == "early-access"
    assert info.size_bytes == 123456
    assert manual_download_url(info, "https://fallback.example/download/") == "https://winsper.app/download/"

    without_page = UpdateInfo(info.version, info.installer_url, info.sha256)
    with pytest.raises(ValueError, match="Manual update page"):
        manual_download_url(without_page, "http://example.com")
