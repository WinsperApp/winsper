from __future__ import annotations

from pathlib import Path


def run_settings_window(
    config_path: Path,
    auto_close_seconds: float | None = None,
    owner_process_id: int = 0,
    initial_page: str = "",
) -> None:
    from .settings_qt import run_settings_window as run_qt_settings_window

    run_qt_settings_window(config_path, auto_close_seconds, owner_process_id, initial_page)
