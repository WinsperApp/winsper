from types import SimpleNamespace
from unittest.mock import Mock, patch

from voicepilot.tray import create_branded_tray_icon


def test_windows_notification_supplies_application_icon():
    class FakeIcon:
        def __init__(self, *args, **kwargs):
            self.title = "Winsper"
            self._icon_handle = 123
            self._assert_icon_handle = Mock()
            self._message = Mock()

    win32 = SimpleNamespace(NIM_MODIFY=1, NIF_INFO=16)
    with patch("voicepilot.tray.os.name", "nt"), patch.dict(
        "sys.modules", {"pystray._util": SimpleNamespace(win32=win32)}
    ):
        icon = create_branded_tray_icon(SimpleNamespace(Icon=FakeIcon))
        icon._notify("Winsper 1.2.0 is ready to download from winsper.app.", "Winsper update available")
    icon._assert_icon_handle.assert_called_once()
    icon._message.assert_called_once_with(
        1, 16, szInfo="Winsper 1.2.0 is ready to download from winsper.app.",
        szInfoTitle="Winsper update available", dwInfoFlags=4, hIcon=123, hBalloonIcon=123,
    )


def test_other_platforms_keep_standard_tray():
    factory = Mock()
    with patch("voicepilot.tray.os.name", "posix"):
        create_branded_tray_icon(SimpleNamespace(Icon=factory), "Winsper")
    factory.assert_called_once_with("Winsper")
