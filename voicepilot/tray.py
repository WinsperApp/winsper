from __future__ import annotations

import threading
import subprocess
import os
import webbrowser
from collections.abc import Callable
from pathlib import Path

from . import __download_page_url__, __release_channel__, __update_feed_url__, __version__
from .branding import create_tray_icon_image
from .config import AppConfig
from .process_control import close_process_gracefully
from .theme import resolve_theme
from .updates import UpdateInfo, check_for_update, manual_download_url
from .windows_ui import apply_native_menu_theme


def create_branded_tray_icon(pystray, *args, **kwargs):
    """Supply Windows balloon branding without changing other tray behavior."""
    if os.name != "nt":
        return pystray.Icon(*args, **kwargs)

    class BrandedIcon(pystray.Icon):
        def _notify(self, message, title=None):
            from pystray._util import win32

            self._assert_icon_handle()
            self._message(
                win32.NIM_MODIFY,
                win32.NIF_INFO,
                szInfo=message,
                szInfoTitle=title or self.title or "Winsper",
                dwInfoFlags=0x00000004,  # NIIF_USER: use the application icon.
                hIcon=self._icon_handle,
                hBalloonIcon=self._icon_handle,
            )

    return BrandedIcon(*args, **kwargs)


class NoopTray:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close_owned_windows(self) -> None:
        pass

    def set_paused(self, _paused: bool) -> None:
        pass


class WinsperTray:
    _window_lock = threading.Lock()
    _window_processes: dict[str, subprocess.Popen] = {}

    def __init__(
        self,
        config: AppConfig,
        config_path: Path,
        on_quit: Callable[[], None],
        on_pause: Callable[[], None] | None = None,
        on_resume: Callable[[], None] | None = None,
        on_copy_last_result: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self.config_path = config_path
        self.on_quit = on_quit
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_copy_last_result = on_copy_last_result
        self._icon = None
        self._thread: threading.Thread | None = None
        self._pystray = None
        self._paused = False
        self._stopping = False
        self._update_info: UpdateInfo | None = None

    def start(self) -> None:
        if not self.config.tray.enabled or self._thread is not None:
            return

        try:
            import pystray
        except Exception as exc:
            print(f"Tray unavailable: {exc}")
            return

        apply_native_menu_theme(resolve_theme(self.config.hud.theme))
        self._pystray = pystray
        self._icon = create_branded_tray_icon(
            pystray,
            "Winsper",
            create_tray_icon_image(),
            "Winsper",
            menu=self._build_menu(),
        )
        self._thread = threading.Thread(target=self._icon.run, name="WinsperTray", daemon=True)
        self._thread.start()
        if self.config.updates.auto_check:
            threading.Thread(target=self._check_for_updates, name="WinsperUpdateCheck", daemon=True).start()

    def stop(self) -> None:
        icon = self._icon
        thread = self._thread
        self._icon = None
        self._thread = None
        if icon is not None:
            icon.stop()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def close_owned_windows(self) -> None:
        with self._window_lock:
            self._stopping = True
            processes = list(self._window_processes.values())
            self._window_processes.clear()
        for process in processes:
            try:
                close_process_gracefully(process)
            except Exception as exc:
                print(f"Could not close Winsper window process {process.pid}: {exc}")

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if self._icon is None:
            return
        try:
            self._icon.title = "Winsper paused" if paused else "Winsper ready"
            if self._pystray is not None:
                self._icon.menu = self._build_menu()
                self._icon.update_menu()
        except Exception:
            pass

    def _build_menu(self):
        pystray = self._pystray
        if pystray is None:
            return None
        items = [
            pystray.MenuItem("Open Winsper", self._settings, default=True),
        ]
        if self._update_info is not None:
            items.extend(
                (
                    pystray.MenuItem(
                        f"Update available · Winsper {self._update_info.version}",
                        self._open_update_page,
                    ),
                )
            )
        items.extend(
            (
                pystray.MenuItem(
                    "Resume Winsper" if self._paused else "Pause Winsper",
                    self._resume if self._paused else self._pause,
                    enabled=(self.on_resume if self._paused else self.on_pause) is not None,
                ),
                pystray.MenuItem(
                    "Copy Last Dictation",
                    self._copy_last_result,
                    enabled=self.on_copy_last_result is not None,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit Winsper", self._quit),
            )
        )
        return pystray.Menu(*items)

    def _quit(self, _icon=None, _item=None) -> None:
        self.on_quit()

    def _settings(self, _icon=None, _item=None) -> None:
        self._open_window("--settings")

    def _check_for_updates(self) -> None:
        from .distribution import uses_store_updates

        if uses_store_updates():
            return
        feed_url = self.config.updates.feed_url.strip() or __update_feed_url__
        if not feed_url:
            return
        try:
            info = check_for_update(feed_url, __version__)
        except Exception:
            return
        if info is None or info.channel != __release_channel__ or self._stopping:
            return
        self._update_info = info
        icon = self._icon
        if icon is None:
            return
        try:
            icon.menu = self._build_menu()
            icon.update_menu()
            icon.notify(
                f"Winsper {info.version} is ready to download from winsper.app.",
                "Winsper update available",
            )
        except Exception:
            pass

    def _open_update_page(self, _icon=None, _item=None) -> None:
        info = self._update_info
        if info is None:
            return
        webbrowser.open(manual_download_url(info, __download_page_url__))

    def _open_window(self, flag: str) -> None:
        with self._window_lock:
            if self._stopping:
                return
            existing = self._window_processes.get(flag)
            if existing is not None and existing.poll() is None:
                return
            self._window_processes[flag] = self._launch_window(flag)

    def _pause(self, _icon=None, _item=None) -> None:
        if self.on_pause is not None:
            self.on_pause()

    def _resume(self, _icon=None, _item=None) -> None:
        if self.on_resume is not None:
            self.on_resume()

    def _copy_last_result(self, _icon=None, _item=None) -> None:
        if self.on_copy_last_result is not None:
            self.on_copy_last_result()

    def _launch_window(self, flag: str) -> subprocess.Popen:
        from .process_launch import app_command, app_working_directory

        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        return subprocess.Popen(
            app_command(
                [
                "--config",
                str(self.config_path),
                "--owner-pid",
                str(os.getpid()),
                flag,
                ]
            ),
            cwd=str(app_working_directory()),
            close_fds=True,
            creationflags=creationflags,
        )
