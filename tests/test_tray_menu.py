from voicepilot.config import AppConfig
from voicepilot.tray import WinsperTray
from voicepilot.updates import UpdateInfo


class _MenuItem:
    def __init__(self, text, action, *, enabled=True, default=False):
        self.text = text
        self.action = action
        self.enabled = enabled
        self.default = default


class _Menu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = items


class _Pystray:
    MenuItem = _MenuItem
    Menu = _Menu


def _tray(tmp_path, calls):
    tray = WinsperTray(
        AppConfig(),
        tmp_path / "config.yaml",
        lambda: calls.append("quit"),
        lambda: calls.append("pause"),
        lambda: calls.append("resume"),
        lambda: calls.append("copy"),
    )
    tray._pystray = _Pystray
    return tray


def _labels(menu):
    return [
        item.text if isinstance(item, _MenuItem) else "<separator>"
        for item in menu.items
    ]


def test_tray_menu_contains_only_essential_ready_actions(tmp_path):
    calls = []
    tray = _tray(tmp_path, calls)

    menu = tray._build_menu()

    assert _labels(menu) == [
        "Open Winsper",
        "Pause Winsper",
        "Copy Last Dictation",
        "<separator>",
        "Quit Winsper",
    ]
    assert menu.items[0].default is True
    menu.items[1].action()
    menu.items[2].action()
    menu.items[4].action()
    assert calls == ["pause", "copy", "quit"]


def test_tray_menu_swaps_pause_for_resume_and_surfaces_update(tmp_path):
    calls = []
    tray = _tray(tmp_path, calls)
    tray._paused = True
    tray._update_info = UpdateInfo(
        version="0.3.0",
        installer_url="https://winsper.app/downloads/WinsperSetup.exe",
        sha256="a" * 64,
    )

    menu = tray._build_menu()

    assert _labels(menu) == [
        "Open Winsper",
        "Update available · Winsper 0.3.0",
        "Resume Winsper",
        "Copy Last Dictation",
        "<separator>",
        "Quit Winsper",
    ]
    menu.items[2].action()
    assert calls == ["resume"]
