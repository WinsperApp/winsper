from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

_HUD_FONT_FAMILY: str | None = None


def hud_font(point_size: int, *, bold: bool = False) -> QFont:
    global _HUD_FONT_FAMILY
    if _HUD_FONT_FAMILY is None:
        available = set(QFontDatabase.families())
        _HUD_FONT_FAMILY = next(
            (family for family in ("Segoe UI", "Segoe UI Variable Display", "Arial") if family in available),
            QFont().defaultFamily(),
        )
    font = QFont(_HUD_FONT_FAMILY, point_size)
    if bold:
        font.setWeight(QFont.Bold)
    font.setStyleStrategy(QFont.PreferAntialias)
    return font
