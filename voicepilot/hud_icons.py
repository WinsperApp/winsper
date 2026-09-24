"""Winsper HUD icon renderer. Geometry intentionally matches current live HUD."""

from __future__ import annotations

import math

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer


_RECORD_ICON_RENDERER: QSvgRenderer | None = None
HUD_ICON_SCALE = 0.90
HUD_ICON_SCALES = {
    "record": HUD_ICON_SCALE,
    "rewrite": 0.78,
    "process": 0.78,
    "preparing": 0.82,
    "success": 0.82,
    "warning": 0.78,
    "error": 0.78,
    "cancelled": 0.82,
    "paused": 0.84,
    "idle": 0.82,
}
_ICON_OPTICAL_OFFSETS = {
    "process": (-1.0, -1.5),
    "preparing": (0.0, -1.5),
    "success": (-1.0, -1.5),
    "warning": (0.0, -1.0),
    "error": (0.0, -2.0),
    "paused": (-1.0, 1.0),
    "idle": (0.0, -3.0),
}
_RECORD_ICON_SVG = b"""\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <defs>
    <linearGradient id="bg" x1="14" y1="9" x2="50" y2="55" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#60A5FA"/>
      <stop offset=".48" stop-color="#2563EB"/>
      <stop offset="1" stop-color="#1D4ED8"/>
    </linearGradient>
    <linearGradient id="mic" x1="23" y1="12" x2="41" y2="47" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="1" stop-color="#E7F0FF"/>
    </linearGradient>
  </defs>
  <circle cx="32" cy="32" r="27.5" fill="url(#bg)"/>
  <circle cx="32" cy="32" r="24.8" stroke="#DBEAFE" stroke-opacity=".56" stroke-width="1.4"/>
  <path d="M21.7 16.2c3.2-3.1 7-4.7 11.3-4.7" stroke="#EFF6FF" stroke-opacity=".36" stroke-width="2" stroke-linecap="round"/>
  <rect x="23.7" y="12.8" width="16.6" height="31.8" rx="8.3" fill="url(#mic)"/>
  <rect x="28.9" y="18.7" width="6.2" height="19.8" rx="3.1" fill="#2563EB" fill-opacity=".16"/>
  <path d="M19.2 33.7c0 7.65 5.25 12.95 12.8 12.95s12.8-5.3 12.8-12.95" stroke="#F8FAFC" stroke-width="3.45" stroke-linecap="round"/>
  <path d="M32 46.65v5.75" stroke="#F8FAFC" stroke-width="3.45" stroke-linecap="round"/>
  <path d="M25 52.4h14" stroke="#F8FAFC" stroke-width="3.45" stroke-linecap="round"/>
</svg>
"""


def record_icon_pixmap(size: int) -> QPixmap:
    """Render the exact microphone mark used by the live listening HUD."""
    global _RECORD_ICON_RENDERER
    if _RECORD_ICON_RENDERER is None:
        _RECORD_ICON_RENDERER = QSvgRenderer(QByteArray(_RECORD_ICON_SVG))
    edge = max(1, int(size))
    pixmap = QPixmap(edge, edge)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    _RECORD_ICON_RENDERER.render(painter, QRectF(0, 0, edge, edge))
    painter.end()
    return pixmap


def draw_icon(painter, kind: str, accent: str, phase: int) -> None:
    painter.save()
    offset_x, offset_y = _ICON_OPTICAL_OFFSETS.get(kind, (0.0, 0.0))
    painter.translate(offset_x, offset_y)
    painter.translate(39, 39)
    scale = HUD_ICON_SCALES.get(kind, 0.82)
    painter.scale(scale, scale)
    painter.translate(-39, -39)
    pen = QPen(QColor(accent), 2.1)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    if kind == "record":
        _draw_record_icon(painter)
    elif kind == "rewrite":
        _draw_polish_icon(painter, accent, phase)
    elif kind == "process":
        points = [QPointF(26, 39), QPointF(31, 39), QPointF(35, 30), QPointF(39, 51), QPointF(45, 35), QPointF(49, 39), QPointF(54, 39)]
        for left, right in zip(points, points[1:]):
            painter.drawLine(left, right)
    elif kind == "preparing":
        _draw_preparing_icon(painter, accent, phase)
    elif kind == "success":
        _draw_success_check(painter, phase)
    elif kind == "warning":
        path = QPainterPath()
        path.moveTo(39, 28)
        path.lineTo(51, 51)
        path.lineTo(27, 51)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(39, 36, 39, 44)
        painter.drawEllipse(QRectF(38, 47, 2, 2))
    elif kind == "error":
        _draw_mic_error_icon(painter, accent)
    elif kind == "cancelled":
        _draw_cancelled_icon(painter, accent)
    elif kind == "paused":
        _draw_paused_icon(painter, accent)
    elif kind == "idle":
        _draw_ready_icon(painter, accent)
    else:
        painter.drawEllipse(QRectF(31, 31, 16, 16))
        painter.drawLine(39, 35, 39, 43)
    painter.restore()


def _draw_record_icon(painter) -> None:
    global _RECORD_ICON_RENDERER
    if _RECORD_ICON_RENDERER is None:
        _RECORD_ICON_RENDERER = QSvgRenderer(QByteArray(_RECORD_ICON_SVG))
    _RECORD_ICON_RENDERER.render(painter, QRectF(20, 20, 38, 38))


def _draw_polish_icon(painter, accent: str, _phase: int) -> None:
    painter.save()
    pen = QPen(QColor(accent), 2.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    star = QPainterPath()
    star.moveTo(39, 28)
    star.lineTo(42, 36)
    star.lineTo(50, 39)
    star.lineTo(42, 42)
    star.lineTo(39, 50)
    star.lineTo(36, 42)
    star.lineTo(28, 39)
    star.lineTo(36, 36)
    star.closeSubpath()
    painter.drawPath(star)
    painter.drawLine(QPointF(48, 29), QPointF(48, 33))
    painter.drawLine(QPointF(46, 31), QPointF(50, 31))
    painter.restore()


def _draw_ready_icon(painter, accent: str) -> None:
    painter.save()
    pen = QPen(QColor(accent), 2.1)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(35, 28, 8, 17), 4, 4)
    painter.drawArc(QRectF(30, 38, 18, 14), 205 * 16, 130 * 16)
    painter.drawLine(QPointF(39, 52), QPointF(39, 56))
    painter.drawLine(QPointF(34, 56), QPointF(44, 56))
    painter.restore()


def _draw_preparing_icon(painter, accent: str, phase: int) -> None:
    """Draw a quiet microphone with a restrained readiness orbit."""

    _draw_ready_icon(painter, accent)
    painter.save()
    pen = QPen(QColor(accent), 1.8)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(QRectF(27, 25, 24, 24), 28 * 16, 86 * 16)
    angle = math.radians((phase * 7 - 48) % 360)
    point = QPointF(39 + 12 * math.cos(angle), 37 + 12 * math.sin(angle))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(accent))
    painter.drawEllipse(QRectF(point.x() - 1.5, point.y() - 1.5, 3, 3))
    painter.restore()

def _draw_mic_error_icon(painter, accent: str) -> None:
    painter.save()
    pen = QPen(QColor(accent), 2.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(35, 27, 8, 17), 4, 4)
    painter.drawArc(QRectF(30, 37, 18, 14), 205 * 16, 130 * 16)
    painter.drawLine(QPointF(39, 51), QPointF(39, 55))
    painter.drawLine(QPointF(34, 55), QPointF(44, 55))
    painter.drawLine(QPointF(30, 29), QPointF(48, 55))
    painter.restore()


def _draw_cancelled_icon(painter, accent: str) -> None:
    painter.save()
    pen = QPen(QColor(accent), 2.1)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QRectF(29, 29, 20, 20))
    painter.drawLine(QPointF(35, 35), QPointF(43, 43))
    painter.drawLine(QPointF(43, 35), QPointF(35, 43))
    painter.restore()


def _draw_paused_icon(painter, accent: str) -> None:
    painter.save()
    painter.setBrush(QColor(accent))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QRectF(34, 29, 4, 18), 2, 2)
    painter.drawRoundedRect(QRectF(42, 29, 4, 18), 2, 2)
    painter.restore()


def _draw_success_check(painter, phase: int) -> None:
    progress = min(1.0, max(0.0, phase / 9))
    start = QPointF(32, 41)
    mid = QPointF(37, 47)
    end = QPointF(48, 34)
    if progress <= 0.5:
        painter.drawLine(start, _lerp_point(start, mid, progress / 0.5))
        return
    painter.drawLine(start, mid)
    painter.drawLine(mid, _lerp_point(mid, end, (progress - 0.5) / 0.5))


def _lerp_point(a: QPointF, b: QPointF, amount: float) -> QPointF:
    t = max(0.0, min(1.0, amount))
    return QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)
