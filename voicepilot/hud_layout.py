"""DPI-safe HUD geometry helpers based on measured Qt text widths."""

from __future__ import annotations

from PySide6.QtCore import QRectF

from .hud_core import HUD_WIDTH


ACCESSORY_HEIGHT = 18
ACCESSORY_RIGHT = 20
ACCESSORY_TOP = 38
CONTENT_LEFT = 78
TITLE_TOP = 13
TITLE_HEIGHT = 20
SUBTITLE_TOP = 33
SUBTITLE_HEIGHT = 16
ACTIVITY_CENTER_Y = 61
HUD_EDGE_MARGIN = 42


def hud_window_origin(
    position: str,
    *,
    available_x: int,
    available_y: int,
    available_width: int,
    available_height: int,
    hud_width: int,
    hud_height: int,
) -> tuple[int, int]:
    """Return a stable primary-screen anchor for every consumer HUD position."""
    bottom = available_y + available_height - hud_height - HUD_EDGE_MARGIN
    if position == "left":
        return available_x + HUD_EDGE_MARGIN, bottom
    if position == "right":
        return available_x + available_width - hud_width - HUD_EDGE_MARGIN, bottom
    horizontal_center = available_x + (available_width - hud_width) // 2
    if position == "top":
        return horizontal_center, available_y + HUD_EDGE_MARGIN
    return horizontal_center, bottom


def hud_hidden_y_offset(position: str) -> int:
    """Slide toward the nearest screen edge while hiding."""
    return -18 if position == "top" else 18


def accessory_rect(width: int) -> QRectF:
    return QRectF(HUD_WIDTH - ACCESSORY_RIGHT - width, ACCESSORY_TOP, width, ACCESSORY_HEIGHT)


def title_rect(right_reserved: int) -> QRectF:
    width = max(100, HUD_WIDTH - CONTENT_LEFT - right_reserved)
    return QRectF(CONTENT_LEFT, TITLE_TOP, width, TITLE_HEIGHT)


def subtitle_rect(right_reserved: int) -> QRectF:
    width = max(100, HUD_WIDTH - CONTENT_LEFT - right_reserved)
    return QRectF(CONTENT_LEFT, SUBTITLE_TOP, width, SUBTITLE_HEIGHT)


def accessory_width_for_text(painter, text: str, *, min_width: int, max_width: int) -> int:
    text_width = painter.fontMetrics().horizontalAdvance(text)
    return max(min_width, min(max_width, text_width + 30))


def timer_width(painter, text: str, *, recording: bool) -> int:
    text_width = painter.fontMetrics().horizontalAdvance(text)
    padding = 30 if recording else 16
    minimum = 42 if recording else 34
    return max(minimum, min(64, text_width + padding))
