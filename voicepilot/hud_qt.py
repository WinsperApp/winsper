from __future__ import annotations

import multiprocessing as mp

from .config import HudConfig
from .hud_core import HudMessage

HUD_FRAME_INTERVAL_MS = 16
HUD_READY_TIMEOUT_SECONDS = 2.0
HUD_SHOW_RESPONSE_PER_SECOND = 45.0
HUD_HIDE_RESPONSE_PER_SECOND = 28.0
HUD_SLIDE_RESPONSE_PER_SECOND = 22.0


def hud_accessible_text(message: HudMessage) -> tuple[str, str]:
    """Return the same status content the painted HUD presents visually."""

    from .hud_core import status_microcopy
    from .hud_state import clean_hud_text, display_title

    title = clean_hud_text(display_title(message)) or "Winsper status"
    detail = clean_hud_text(message.subtitle) or status_microcopy(message.kind) or f"Winsper status: {message.kind.replace('_', ' ')}."
    return title, detail


def hud_accessibility_announcement(
    previous: HudMessage | None,
    current: HudMessage,
) -> tuple[str, bool] | None:
    """Return a concise live-region announcement and whether it is urgent."""

    title, detail = hud_accessible_text(current)
    if previous is not None:
        previous_title, previous_detail = hud_accessible_text(previous)
        if (title, detail) == (previous_title, previous_detail):
            return None
        # Partial transcripts and progress details can update many times per
        # second. Keep the accessible object current without making a screen
        # reader repeat the same stage heading for every incremental update.
        if title == previous_title and current.kind in {
            "listening",
            "process",
            "preparing",
            "record",
            "rewrite",
        }:
            return None
    spoken = title if not detail or detail == title else f"{title}. {detail}"
    return spoken, current.kind in {"error", "warning"}


class QtStatusHUD:
    def __init__(self, config: HudConfig) -> None:
        self.config = config
        self._queue = None
        self._process: mp.Process | None = None
        self._latest_action_id = 0
        self._latest_terminal_action_id = 0

    def start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        context = mp.get_context("spawn")
        self._queue = context.Queue()
        ready_event = context.Event()
        self._process = context.Process(
            target=run_hud_process,
            args=(self._queue, self.config, ready_event),
            name="WinsperQtHUD",
            daemon=True,
        )
        self._process.start()
        ready_event.wait(timeout=HUD_READY_TIMEOUT_SECONDS)

    def stop(self) -> None:
        if self._queue is not None:
            self._queue.put(None)
        if self._process is not None:
            self._process.join(timeout=2.0)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=1.0)
        self._process = None
        self._queue = None

    def show(self, title: str, subtitle: str = "", kind: str = "idle") -> None:
        if self._queue is None:
            return
        self._queue.put(HudMessage(title, subtitle, kind))

    def show_action_event(self, event) -> None:
        from .action_state import ActionStage
        from .hud_events import message_for_action_event

        if event.action_id and (
            event.action_id < self._latest_action_id
            or (
                event.action_id <= self._latest_terminal_action_id
                and event.stage not in {ActionStage.COMPLETED, ActionStage.CANCELLED, ActionStage.FAILED}
            )
        ):
            return
        self._latest_action_id = max(self._latest_action_id, event.action_id)
        if event.stage in {ActionStage.COMPLETED, ActionStage.CANCELLED, ActionStage.FAILED}:
            self._latest_terminal_action_id = max(self._latest_terminal_action_id, event.action_id)
        message = message_for_action_event(event)
        if message is not None:
            self.show(message.title, message.subtitle, message.kind)

    def show_action_message(self, action_id: int, title: str, subtitle: str = "", kind: str = "idle") -> None:
        if action_id < self._latest_action_id or action_id <= self._latest_terminal_action_id:
            return
        self._latest_action_id = max(self._latest_action_id, action_id)
        self.show(title, subtitle, kind)


def run_hud_process(message_queue, config: HudConfig, ready_event=None) -> None:
    import math
    import os
    import threading
    import time

    from .branding import set_windows_app_user_model_id
    from .hud_core import (
        COMPACT_HUD_HEIGHT,
        COMPACT_HUD_WIDTH,
        HUD_HEIGHT,
        HUD_WIDTH,
        hide_deadline,
    )
    from .hud_layout import hud_hidden_y_offset, hud_window_origin
    from .hud_render import (
        color_for_kind,
        draw_compact_card,
        draw_standard_hud,
        draw_wave,
        smoothstep,
    )
    from .hud_state import (
        should_restart_animation,
        should_restart_timer,
        should_hide_compact_hud,
        should_use_compact_hud,
    )
    from .theme import get_palette
    from .windows_ui import prefers_reduced_motion
    from PySide6.QtCore import QObject, Signal, QTimer, Qt
    from PySide6.QtGui import (
        QAccessible,
        QAccessibleAnnouncementEvent,
        QAccessibleEvent,
        QPainter,
    )
    from PySide6.QtWidgets import QApplication, QWidget

    set_windows_app_user_model_id()
    app = QApplication([])
    palette = get_palette(config.theme)
    reduced_motion = prefers_reduced_motion()

    class HudWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.message = HudMessage("Ready", "Hold the hotkey to speak", "idle")
            self.visible_state = False
            self.hide_after_at = 0.0
            self.phase = 0
            self.window_opacity = 0.0
            self.fade_target = 0.0
            self.message_started_at = time.monotonic()
            self.base_x = 0
            self.base_y = 0
            self.current_y = 0.0
            self.target_y = 0.0
            self.last_tick_at = time.monotonic()
            self.setFixedSize(HUD_WIDTH, HUD_HEIGHT)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
            self.setWindowOpacity(0.0)
            self._update_accessibility(None, self.message, announce=False)
            self._place(immediate=True)

        def _update_accessibility(
            self,
            previous: HudMessage | None,
            message: HudMessage,
            *,
            announce: bool,
        ) -> None:
            title, detail = hud_accessible_text(message)
            self.setAccessibleName(title)
            self.setAccessibleDescription(detail)
            if announce:
                QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.NameChanged))
                QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.DescriptionChanged))
                announcement = hud_accessibility_announcement(previous, message)
                if announcement is not None:
                    spoken, assertive = announcement
                    event = QAccessibleAnnouncementEvent(self, spoken)
                    event.setPoliteness(
                        QAccessible.AnnouncementPoliteness.Assertive if assertive else QAccessible.AnnouncementPoliteness.Polite
                    )
                    QAccessible.updateAccessibility(event)

        def _place(self, immediate: bool = False) -> None:
            screen = QApplication.primaryScreen()
            geo = screen.availableGeometry() if screen is not None else self.geometry()
            self.base_x, self.base_y = hud_window_origin(
                config.position,
                available_x=geo.x(),
                available_y=geo.y(),
                available_width=geo.width(),
                available_height=geo.height(),
                hud_width=self.width(),
                hud_height=self.height(),
            )
            self.target_y = float(self.base_y)
            if immediate:
                self.current_y = self.target_y
                self.move(self.base_x, int(self.current_y))

        def paintEvent(self, _event) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            visible_amount = max(0.0, min(1.0, self.window_opacity / max(config.opacity, 0.01)))
            scale = 1.0 if reduced_motion else 0.988 + 0.012 * smoothstep(visible_amount)
            width = self.width()
            height = self.height()
            painter.translate(width / 2, height / 2)
            painter.scale(scale, scale)
            painter.translate(-width / 2, -height / 2)

            accent = color_for_kind(self.message.kind, palette)
            if should_use_compact_hud(self.message, config.mode):
                draw_compact_card(painter, palette, self.message.kind, self.phase, reduced_motion)
                draw_wave(
                    painter,
                    20.0,
                    24.0,
                    accent,
                    0 if reduced_motion else self.phase,
                    bars=19,
                    spacing=4.45,
                    max_height=18.5,
                    stroke_width=2.15,
                    travel=not reduced_motion,
                )
                return
            draw_standard_hud(
                painter,
                self.message,
                palette,
                self.phase,
                time.monotonic() - self.message_started_at,
                reduced_motion,
            )

        def update_message(self, message: HudMessage) -> None:
            delivery_ms = (time.perf_counter() - message.queued_at) * 1000
            debug_timing = os.environ.get("WINSPER_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
            if debug_timing or delivery_ms >= 100:
                print(f"Winsper HUD timing: {message.title} delivered in {delivery_ms:.1f}ms")
            previous_message = self.message
            was_hidden = not self.isVisible() or self.window_opacity <= 0.03
            self.message = message
            compact = should_use_compact_hud(message, config.mode)
            target_size = (COMPACT_HUD_WIDTH, COMPACT_HUD_HEIGHT) if compact else (HUD_WIDTH, HUD_HEIGHT)
            if (self.width(), self.height()) != target_size:
                self.setFixedSize(*target_size)
            self._update_accessibility(previous_message, message, announce=True)

            if should_hide_compact_hud(message, config.mode):
                self.visible_state = False
                self.hide_after_at = 0.0
                self.fade_target = 0.0
                self.window_opacity = 0.0
                self.setWindowOpacity(0.0)
                self.current_y = self.target_y = float(self.base_y)
                self.move(self.base_x, self.base_y)
                self.hide()
                return

            if should_restart_animation(previous_message, message, was_hidden):
                self.phase = 0

            if should_restart_timer(previous_message, message, was_hidden):
                self.message_started_at = time.monotonic()
            if message.kind == "idle" and not config.show_idle:
                self.visible_state = False
                self.hide_after_at = 0.0
                self.fade_target = 0.0
                if reduced_motion:
                    self.window_opacity = 0.0
                    self.setWindowOpacity(0.0)
                    self.hide()
                return
            self.visible_state = True
            self.fade_target = config.opacity
            self.hide_after_at = hide_deadline(message.kind, config)
            if was_hidden:
                self._place(immediate=True)
                if reduced_motion:
                    self.window_opacity = config.opacity
                    self.current_y = self.target_y
                    self.setWindowOpacity(config.opacity)
                else:
                    self.window_opacity = 0.0
                    self.current_y = self.target_y + hud_hidden_y_offset(config.position)
            self._place()
            self.show()
            self.raise_()
            self.update()

        def tick(self) -> None:
            if not self.visible_state and self.window_opacity <= 0.001:
                self.last_tick_at = time.monotonic()
                return
            now = time.monotonic()
            delta_seconds = max(0.001, min(0.1, now - self.last_tick_at))
            self.last_tick_at = now
            if self.hide_after_at and now >= self.hide_after_at:
                self.visible_state = False
                self.hide_after_at = 0.0
                self.fade_target = 0.0
            if reduced_motion:
                self.window_opacity = config.opacity if self.visible_state else 0.0
                self.setWindowOpacity(self.window_opacity)
                self.current_y = self.target_y = float(self.base_y)
                self.move(self.base_x, self.base_y)
                if not self.visible_state:
                    self.hide()
                    return
                self.update()
                return

            self.phase += 1

            opacity_response = HUD_SHOW_RESPONSE_PER_SECOND if self.fade_target > self.window_opacity else HUD_HIDE_RESPONSE_PER_SECOND
            opacity_ease = 1.0 - math.exp(-opacity_response * delta_seconds)
            self.window_opacity += (self.fade_target - self.window_opacity) * opacity_ease
            if abs(self.fade_target - self.window_opacity) < 0.01:
                self.window_opacity = self.fade_target
            self.setWindowOpacity(self.window_opacity)

            if not self.visible_state:
                self.target_y = self.base_y + hud_hidden_y_offset(config.position)
            else:
                self.target_y = self.base_y

            position_ease = 1.0 - math.exp(-HUD_SLIDE_RESPONSE_PER_SECOND * delta_seconds)
            self.current_y += (self.target_y - self.current_y) * position_ease
            if abs(self.target_y - self.current_y) < 0.5:
                self.current_y = self.target_y
            self.move(self.base_x, int(self.current_y))

            if not self.visible_state and self.window_opacity <= 0.01:
                self.hide()
                return
            self.update()

    window = HudWindow()
    # Force Qt and the Windows compositor to create the native surface before
    # the first hotkey. Opacity zero keeps this warm-up completely invisible.
    window.setWindowOpacity(0.0)
    window.show()
    app.processEvents()
    window.hide()
    app.processEvents()

    class MessageBridge(QObject):
        received = Signal(object)

    bridge = MessageBridge()

    def handle_message(message) -> None:
        if message is None:
            app.quit()
            return
        window.update_message(message)
        window.tick()

    bridge.received.connect(handle_message)

    def read_messages() -> None:
        while True:
            message = message_queue.get()
            bridge.received.emit(message)
            if message is None:
                return

    reader = threading.Thread(target=read_messages, name="WinsperHUDMessages", daemon=True)
    reader.start()

    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.timeout.connect(window.tick)
    timer.start(HUD_FRAME_INTERVAL_MS)
    if ready_event is not None:
        ready_event.set()
    app.exec()


__all__ = ["QtStatusHUD", "hud_accessible_text", "run_hud_process"]
