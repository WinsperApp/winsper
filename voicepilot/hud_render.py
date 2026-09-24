from __future__ import annotations

import math

from .hud_core import (
    COMPACT_HUD_HEIGHT,
    COMPACT_HUD_WIDTH,
    HUD_HEIGHT,
    HUD_WIDTH,
    HudMessage,
    status_microcopy,
)
from .hud_fonts import hud_font
from .hud_icons import draw_icon
from .hud_layout import (
    ACCESSORY_RIGHT,
    ACTIVITY_CENTER_Y,
    CONTENT_LEFT,
    accessory_rect,
    accessory_width_for_text,
    subtitle_rect,
    timer_width,
    title_rect,
)
from .hud_state import (
    clean_hud_text,
    display_title,
    format_elapsed,
    is_listening_message,
    is_timed_message,
    should_show_status_pill,
    split_subtitle,
    status_label_for_kind,
)

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPen

HUD_FRAME_INTERVAL_MS = 16
HUD_READY_TIMEOUT_SECONDS = 2.0
HUD_SHOW_RESPONSE_PER_SECOND = 45.0
HUD_HIDE_RESPONSE_PER_SECOND = 28.0
HUD_SLIDE_RESPONSE_PER_SECOND = 22.0
_HUD_FONT_FAMILY: str | None = None


def draw_card(
    painter,
    palette,
    kind: str = "idle",
    phase: int = 0,
    reduced_motion: bool = False,
    *,
    listening: bool = False,
) -> None:
    painter.setPen(Qt.NoPen)

    painter.setBrush(translucent(palette.shadow, 17 if palette.mode == "dark" else 9))
    painter.drawRoundedRect(QRectF(4, 6, HUD_WIDTH - 8, HUD_HEIGHT - 4), 36, 36)
    painter.setBrush(translucent(palette.shadow, 68 if palette.mode == "dark" else 24))
    painter.drawRoundedRect(QRectF(9, 11, HUD_WIDTH - 18, HUD_HEIGHT - 16), 32, 32)

    body_rect = QRectF(8, 6, HUD_WIDTH - 16, HUD_HEIGHT - 14)
    body = QLinearGradient(body_rect.left(), body_rect.top(), body_rect.right(), body_rect.bottom())
    alpha = 226 if palette.mode == "dark" else 242
    body.setColorAt(0.0, translucent(palette.surface, alpha))
    bottom = palette.surface_2 if palette.mode == "light" else palette.field
    body.setColorAt(1.0, translucent(bottom, alpha - 12))
    painter.setBrush(body)
    painter.setPen(QPen(translucent(palette.border, 130 if palette.mode == "dark" else 118), 1))
    body_radius = body_rect.height() / 2
    painter.drawRoundedRect(body_rect, body_radius, body_radius)

    draw_top_indicator(painter, palette, kind, phase, reduced_motion, listening=listening)


def draw_compact_card(
    painter,
    palette,
    kind: str,
    phase: int,
    reduced_motion: bool,
) -> None:
    """Draw the low-profile listening capsule without visible status copy."""

    painter.setPen(Qt.NoPen)
    shadow_rect = QRectF(5, 5, COMPACT_HUD_WIDTH - 10, COMPACT_HUD_HEIGHT - 7)
    painter.setBrush(translucent(palette.shadow, 60 if palette.mode == "dark" else 20))
    painter.drawRoundedRect(shadow_rect, shadow_rect.height() / 2, shadow_rect.height() / 2)

    body_rect = QRectF(4, 2, COMPACT_HUD_WIDTH - 8, COMPACT_HUD_HEIGHT - 5)
    body = QLinearGradient(body_rect.left(), body_rect.top(), body_rect.left(), body_rect.bottom())
    alpha = 234 if palette.mode == "dark" else 247
    body.setColorAt(0.0, translucent(palette.surface, alpha))
    body.setColorAt(1.0, translucent(palette.field, alpha - 10))
    painter.setBrush(body)
    painter.setPen(QPen(translucent(palette.border, 142 if palette.mode == "dark" else 126), 1))
    painter.drawRoundedRect(body_rect, body_rect.height() / 2, body_rect.height() / 2)

    pulse = 188
    if not reduced_motion:
        pulse += round(34 * (0.5 + 0.5 * math.sin(phase * 0.18)))
    indicator = QRectF(19, 7, COMPACT_HUD_WIDTH - 38, 1.5)
    signal = QLinearGradient(indicator.left(), indicator.top(), indicator.right(), indicator.top())
    signal.setColorAt(0.0, translucent(palette.accent, 18))
    signal.setColorAt(0.22, translucent(palette.accent, pulse))
    signal.setColorAt(0.78, translucent(palette.accent_2, pulse))
    signal.setColorAt(1.0, translucent(palette.accent_2, 18))
    painter.setPen(Qt.NoPen)
    painter.setBrush(signal)
    painter.drawRoundedRect(indicator, 0.75, 0.75)
    if not reduced_motion:
        draw_indicator_shimmer(painter, indicator, phase, width=22, alpha=58)


def draw_top_indicator(painter, palette, kind: str, phase: int, reduced_motion: bool, *, listening: bool = False) -> None:
    rect = QRectF(28, 10, 116, 2.0)
    alpha = 210
    if listening and not reduced_motion:
        alpha = int(168 + 30 * (0.5 + 0.5 * math.sin(phase * 0.18)))

    state_color = {
        "success": palette.success,
        "warning": palette.amber,
        "error": palette.coral,
        "cancelled": palette.amber,
        "paused": palette.subtle,
    }.get(kind)

    if state_color:
        state = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        state.setColorAt(0.0, translucent(state_color, 62))
        state.setColorAt(0.18, translucent(state_color, 214))
        state.setColorAt(0.82, translucent(state_color, 214))
        state.setColorAt(1.0, translucent(state_color, 62))
        painter.setBrush(state)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 2, 2)
        return

    accent = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
    accent.setColorAt(0.0, translucent(palette.accent, 54))
    accent.setColorAt(0.18, translucent(palette.accent, alpha))
    accent.setColorAt(0.72, translucent(palette.accent_2, alpha))
    accent.setColorAt(1.0, translucent(palette.accent_2, 54))
    painter.setBrush(accent)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(rect, 2, 2)

    if (listening or kind in {"process", "preparing", "rewrite"}) and not reduced_motion:
        draw_indicator_shimmer(painter, rect, phase, width=34, alpha=54)


def draw_indicator_shimmer(painter, rect: QRectF, phase: int, *, width: float, alpha: int) -> None:
    travel = rect.width() + width
    left = rect.left() - width + ((phase * 1.7) % travel)
    shimmer = QLinearGradient(left, rect.top(), left + width, rect.top())
    shimmer.setColorAt(0.0, translucent("#ffffff", 0))
    shimmer.setColorAt(0.5, translucent("#ffffff", alpha))
    shimmer.setColorAt(1.0, translucent("#ffffff", 0))
    clipped_left = max(rect.left(), left)
    clipped_right = min(left + width, rect.right())
    if clipped_right <= clipped_left:
        return
    painter.setBrush(shimmer)
    painter.setPen(Qt.NoPen)
    radius = rect.height() / 2
    painter.drawRoundedRect(
        QRectF(clipped_left, rect.top(), clipped_right - clipped_left, rect.height()),
        radius,
        radius,
    )


def draw_icon_well(painter, accent: str, palette) -> None:
    outer = QRectF(13, 13, 52, 52)
    painter.setPen(Qt.NoPen)
    painter.setBrush(translucent(palette.shadow, 34 if palette.mode == "dark" else 22))
    painter.drawEllipse(outer.adjusted(1, 2, 1, 2))
    painter.setBrush(QColor(palette.surface))
    painter.setPen(QPen(translucent(palette.border, 180 if palette.mode == "dark" else 142), 1.1))
    painter.drawEllipse(outer)
    painter.setBrush(translucent(accent, 18 if palette.mode == "dark" else 13))
    painter.setPen(QPen(translucent(accent, 122), 1.2))
    painter.drawEllipse(outer.adjusted(3.5, 3.5, -3.5, -3.5))


def draw_wave(
    painter,
    x: float,
    y: float,
    accent: str,
    phase: int,
    bars: int = 15,
    spacing: float = 5,
    *,
    max_height: float = 16.0,
    stroke_width: float = 2.15,
    travel: bool = False,
) -> None:
    count = max(12, min(28, bars))
    for index in range(count):
        height, envelope = wave_bar_metrics(index, count, phase, max_height, travel=travel)
        alpha = int(150 + 70 * math.sqrt(envelope))
        pen = QPen(translucent(accent, alpha), stroke_width)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        x0 = x + index * spacing
        painter.drawLine(QPointF(x0, y - height / 2), QPointF(x0, y + height / 2))


def wave_bar_metrics(
    index: int,
    count: int,
    phase: int,
    max_height: float,
    *,
    travel: bool = False,
) -> tuple[float, float]:
    """Return a centre-weighted live-wave height and its normalized envelope."""

    midpoint = (count - 1) / 2
    center = midpoint
    if travel:
        center += count * 0.24 * math.sin(phase * 0.055)
    distance = abs(index - center) / max(midpoint, 1)
    envelope = math.exp(-6.0 * distance * distance)
    motion = 0.88 + 0.12 * math.sin(phase * 0.22 + index * 0.72)
    minimum = 3.5
    height = minimum + (max_height - minimum) * envelope * motion
    return max(minimum, min(max_height, height)), envelope


def draw_status_pill(painter, kind: str, accent: str, palette) -> None:
    label = status_label_for_kind(kind)
    painter.setFont(hud_font(7, bold=True))
    rect = accessory_rect(accessory_width_for_text(painter, label, min_width=50, max_width=86))
    pill = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
    pill.setColorAt(0.0, QColor(palette.surface_2))
    pill.setColorAt(1.0, QColor(palette.field))
    painter.setBrush(pill)
    painter.setPen(QPen(QColor(palette.border_soft), 1))
    painter.drawRoundedRect(rect, 9, 9)
    painter.setBrush(QColor(accent))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(rect.x() + 8, rect.center().y() - 2.5, 5, 5))
    painter.setPen(QColor(palette.text))
    label_rect = rect.adjusted(18, 0, -4, 0)
    label_metrics = painter.fontMetrics()
    painter.drawText(
        label_rect,
        Qt.AlignVCenter | Qt.AlignLeft,
        label_metrics.elidedText(label, Qt.ElideRight, int(label_rect.width())),
    )


def draw_timer(painter, elapsed: float, accent: str, palette, *, recording: bool) -> None:
    text = format_elapsed(elapsed)
    painter.setFont(hud_font(7, bold=True))
    rect = accessory_rect(timer_width(painter, text, recording=recording))
    painter.setBrush(translucent(accent, 32 if recording else 18))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(rect, 9, 9)
    if recording:
        painter.setBrush(QColor("#EF4444"))
        painter.drawEllipse(QRectF(rect.x() + 8, rect.center().y() - 2.5, 5, 5))
    painter.setPen(QColor(palette.text))
    text_width = painter.fontMetrics().horizontalAdvance(text)
    text_x = rect.x() + (18 + max(0, (rect.width() - 22 - text_width) / 2) if recording else (rect.width() - text_width) / 2)
    painter.drawText(QRectF(text_x, rect.y(), text_width + 2, rect.height()), Qt.AlignLeft | Qt.AlignVCenter, text)


def draw_live_line(painter, text: str, accent: str, palette) -> None:
    painter.setBrush(translucent(accent, 210))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(CONTENT_LEFT, ACTIVITY_CENTER_Y - 3, 6, 6))
    painter.setPen(QColor(palette.text))
    painter.setFont(hud_font(8))
    rect = QRectF(CONTENT_LEFT + 12, ACTIVITY_CENTER_Y - 9, HUD_WIDTH - CONTENT_LEFT - 34, 18)
    elided = painter.fontMetrics().elidedText(clean_hud_text(text), Qt.ElideRight, int(rect.width()))
    painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, elided)


def draw_microcopy(painter, text: str, accent: str, palette) -> None:
    if not text:
        return
    painter.setBrush(QColor(accent))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(CONTENT_LEFT, ACTIVITY_CENTER_Y - 3, 6, 6))
    painter.setPen(QColor(palette.muted))
    painter.setFont(hud_font(8))
    rect = QRectF(CONTENT_LEFT + 12, ACTIVITY_CENTER_Y - 9, HUD_WIDTH - CONTENT_LEFT - 96, 18)
    elided = painter.fontMetrics().elidedText(text, Qt.ElideRight, int(rect.width()))
    painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, elided)


def draw_standard_hud(
    painter,
    message: HudMessage,
    palette,
    phase: int,
    elapsed: float,
    reduced_motion: bool,
) -> None:
    """Render the complete standard HUD from one measured component layout."""

    accent = color_for_kind(message.kind, palette)
    listening = is_listening_message(message)
    timed = is_timed_message(message)
    show_pill = should_show_status_pill(message)

    draw_card(painter, palette, message.kind, phase, reduced_motion, listening=listening)
    draw_icon_well(painter, accent, palette)
    draw_icon(painter, message.kind, accent, phase)

    accessory_width = 0
    if timed:
        painter.setFont(hud_font(7, bold=True))
        accessory_width = timer_width(painter, format_elapsed(elapsed), recording=listening)
    elif show_pill:
        painter.setFont(hud_font(7, bold=True))
        accessory_width = accessory_width_for_text(
            painter,
            status_label_for_kind(message.kind),
            min_width=50,
            max_width=86,
        )
    right_reserved = accessory_width + ACCESSORY_RIGHT + 12 if accessory_width else 22

    title = display_title(message)
    painter.setPen(QColor(palette.text))
    painter.setFont(hud_font(11, bold=True))
    heading_rect = title_rect(right_reserved)
    painter.drawText(
        heading_rect,
        Qt.AlignLeft | Qt.AlignVCenter,
        painter.fontMetrics().elidedText(title, Qt.ElideRight, int(heading_rect.width())),
    )

    meta, preview = split_subtitle(message)
    painter.setPen(QColor(palette.muted))
    painter.setFont(hud_font(8))
    detail_rect = subtitle_rect(right_reserved)
    painter.drawText(
        detail_rect,
        Qt.AlignLeft | Qt.AlignVCenter,
        painter.fontMetrics().elidedText(clean_hud_text(meta), Qt.ElideRight, int(detail_rect.width())),
    )

    if show_pill:
        draw_status_pill(painter, message.kind, accent, palette)
    if timed:
        draw_timer(painter, elapsed, accent, palette, recording=listening)
    if preview:
        draw_live_line(painter, preview, accent, palette)
    elif listening:
        draw_wave(
            painter,
            CONTENT_LEFT + 1,
            ACTIVITY_CENTER_Y,
            accent,
            0 if reduced_motion else phase,
            bars=24,
            spacing=5,
            max_height=22,
            stroke_width=2.3,
            travel=not reduced_motion,
        )
    else:
        draw_microcopy(painter, status_microcopy(message.kind), accent, palette)


def translucent(color: str, alpha: int) -> QColor:
    value = QColor(color)
    value.setAlpha(max(0, min(255, alpha)))
    return value


def color_for_kind(kind: str, palette) -> str:
    return {
        "record": palette.accent,
        "rewrite": palette.accent_2,
        "process": palette.accent,
        "preparing": palette.accent,
        "success": palette.success,
        "warning": palette.amber,
        "error": palette.coral,
        "paused": palette.subtle,
        "cancelled": palette.amber,
        "idle": palette.text,
    }.get(kind, palette.text)


def smoothstep(value: float) -> float:
    amount = max(0.0, min(1.0, value))
    return amount * amount * (3.0 - 2.0 * amount)
