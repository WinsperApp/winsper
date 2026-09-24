from __future__ import annotations

from pathlib import Path


_APP_ICON_FILES = {
    "outlook": "outlook.svg",
    "slack": "slack.png",
    "chatgpt": "chatgpt.png",
    "vscode": "vscode.png",
    "terminal": "terminal.png",
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
    """Load an unmodified app mark from Winsper's app assets."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QPainter, QPixmap

    path = app_icon_path(app_id)
    if path is None:
        return QIcon()
    if app_id.casefold() != "terminal":
        return QIcon(str(path))
    source = QPixmap(str(path))
    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    scaled_size = round(size * 3.45)  # Match winsper.app's treatment of this padded mark.
    scaled = source.scaled(
        scaled_size,
        scaled_size,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    painter = QPainter(canvas)
    painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return QIcon(canvas)


__all__ = ["app_icon", "app_icon_path"]
