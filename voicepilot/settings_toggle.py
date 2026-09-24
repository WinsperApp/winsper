from __future__ import annotations

from .windows_ui import motion_enabled


class ToggleSwitch:
    """iOS-style pill toggle with spring-physics sliding thumb.
    ON  → same cyan-to-violet gradient as the Winsper logo and Save button
    OFF → semi-transparent grey pill that adapts to light/dark backgrounds
    """

    @staticmethod
    def create(
        checked: bool = False,
        accent: str = "#007fd4",
        accent2: str = "#5b43f2",
        motion_provider=motion_enabled,
    ):
        import math
        from PySide6.QtCore import Qt, QRectF, QTimer
        from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QBrush
        from PySide6.QtWidgets import QAbstractButton

        class _Toggle(QAbstractButton):
            def __init__(self):
                super().__init__()
                self._accent = accent
                self._accent_2 = accent2
                self.setCheckable(True)
                self.setChecked(checked)
                self.setFixedSize(44, 26)
                self.setCursor(Qt.PointingHandCursor)
                # Animated thumb: 0.0 = fully left/OFF, 1.0 = fully right/ON
                self._thumb_progress = 1.0 if checked else 0.0
                self._motion_enabled = motion_provider()
                self._anim_timer = QTimer(self)
                self._anim_timer.setInterval(16)  # ~60 fps
                self._anim_timer.timeout.connect(self._tick_anim)
                self.toggled.connect(self._on_toggled)

            def _on_toggled(self, _state: bool) -> None:
                if self._motion_enabled:
                    self._anim_timer.start()
                else:
                    self._thumb_progress = 1.0 if self.isChecked() else 0.0
                    self.update()

            def _tick_anim(self) -> None:
                target = 1.0 if self.isChecked() else 0.0
                # Exponential ease — same math as the HUD slide
                self._thumb_progress += (target - self._thumb_progress) * (1.0 - math.exp(-22 * 0.016))
                if abs(target - self._thumb_progress) < 0.005:
                    self._thumb_progress = target
                    self._anim_timer.stop()
                self.update()

            def paintEvent(self, _event):
                p = QPainter(self)
                p.setRenderHint(QPainter.Antialiasing)
                w, h = self.width(), self.height()
                t = self._thumb_progress  # 0.0–1.0
                p.setPen(Qt.NoPen)

                path = QPainterPath()
                path.addRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)

                # Smoothly blend track colour from grey (OFF) to gradient (ON)
                on_c1 = QColor(self._accent)
                on_c2 = QColor(self._accent_2)
                off_c = QColor(160, 170, 185, 120)

                def _blend(a: QColor, b: QColor, k: float) -> QColor:
                    return QColor(
                        int(a.red() * k + b.red() * (1 - k)),
                        int(a.green() * k + b.green() * (1 - k)),
                        int(a.blue() * k + b.blue() * (1 - k)),
                        int(a.alpha() * k + b.alpha() * (1 - k)),
                    )

                grad = QLinearGradient(0, 0, w, 0)
                grad.setColorAt(0, _blend(on_c1, off_c, t))
                grad.setColorAt(1, _blend(on_c2, off_c, t))
                p.setBrush(QBrush(grad))
                p.drawPath(path)

                margin = 3
                d = h - 2 * margin
                x_off = float(margin)
                x_on = float(w - d - margin)
                x = x_off + (x_on - x_off) * t
                p.setBrush(QColor(255, 255, 255, 230))
                p.drawEllipse(QRectF(x, margin, d, d))
                p.end()

            def sizeHint(self):
                from PySide6.QtCore import QSize

                return QSize(44, 26)

            def setCheckedInstantly(self, checked: bool) -> None:
                previous = self.blockSignals(True)
                try:
                    self.setChecked(checked)
                finally:
                    self.blockSignals(previous)
                self._anim_timer.stop()
                self._thumb_progress = 1.0 if checked else 0.0
                self.update()

            def setAccentColors(self, primary: str, secondary: str) -> None:
                self._accent = primary
                self._accent_2 = secondary
                self.update()

        return _Toggle()
