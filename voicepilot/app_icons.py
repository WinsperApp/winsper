from __future__ import annotations

from pathlib import Path


_APP_ICON_FILES = {
    "outlook": "outlook.svg",
    "slack": "slack.png",
    "chatgpt": "chatgpt.png",
    "vscode": "vscode.png",
    "terminal": "command-prompt.svg",
}


def app_icon_path(app_id: str) -> Path | None:
    """Resolve an app mark in both source and packaged Winsper layouts."""
    filename = _APP_ICON_FILES.get(app_id.casefold())
    if filename is None:
        return None
    module_root = Path(__file__).resolve().parent
    candidate = module_root / "assets" / "apps" / filename
    return candidate if candidate.is_file() else None


def app_icon(app_id: str, size: int = 32):
    """Load an app mark or generic command-window symbol from Winsper's assets."""
    from PySide6.QtGui import QIcon

    path = app_icon_path(app_id)
    if path is None:
        return QIcon()
    return QIcon(str(path))


__all__ = ["app_icon", "app_icon_path"]
