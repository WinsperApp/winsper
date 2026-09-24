from __future__ import annotations

def _shortcut_label(value: str) -> str:
    labels = {
        "ctrl": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "win": "Win",
        "space": "Space",
        "esc": "Esc",
        "enter": "Enter",
        "tab": "Tab",
        "backspace": "Backspace",
        "delete": "Delete",
        "page_up": "Page Up",
        "page_down": "Page Down",
        "caps_lock": "Caps Lock",
    }
    part = value.strip().lower()
    if part.startswith("f") and part[1:].isdigit():
        return part.upper()
    return labels.get(part, part.replace("_", " ").title())


def format_shortcut(value: str) -> str:
    parts = [part.strip().lower() for part in value.split("+") if part.strip()]
    return "  +  ".join(_shortcut_label(part) for part in parts)


def create_shortcut_recorder(value: str = ""):
    from PySide6.QtCore import QEasingCurve, Property, QPropertyAnimation, Qt, Signal
    from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

    from .windows_ui import motion_enabled

    class ShortcutRecorder(QPushButton):
        shortcutChanged = Signal(str)

        def __init__(self, shortcut: str):
            super().__init__()
            self._value = ""
            self._recording = False
            self._attention_active = False
            self._attention_dismissed = False
            self._attention_progress = 0.0
            self._attention_color = QColor("#1597e5")
            self._attention_animation = QPropertyAnimation(self, b"attentionProgress", self)
            self._attention_animation.setDuration(1200)
            self._attention_animation.setKeyValueAt(0.0, 0.25)
            self._attention_animation.setKeyValueAt(0.5, 1.0)
            self._attention_animation.setKeyValueAt(1.0, 0.25)
            self._attention_animation.setEasingCurve(QEasingCurve.InOutSine)
            self._attention_animation.setLoopCount(-1)
            self.setObjectName("ShortcutRecorder")
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.StrongFocus)
            self.setMinimumWidth(220)
            self.setMinimumHeight(38)

            self._keycap_layout = QHBoxLayout(self)
            self._keycap_layout.setContentsMargins(12, 0, 12, 0)
            self._keycap_layout.setAlignment(Qt.AlignCenter)
            self._keycap_layout.setSpacing(5)

            self.setValue(shortcut)
            self.clicked.connect(self.begin_capture)

        def value(self) -> str:
            return self._value

        def text(self) -> str:
            return self._value

        def setValue(self, shortcut) -> None:
            self._value = str(shortcut or "").strip().lower()
            self.setProperty("empty", not bool(self._value))
            self._refresh_style()

        def begin_capture(self) -> None:
            self.dismissAttention()
            self._recording = True
            self.setProperty("recording", True)
            self.setFocus(Qt.MouseFocusReason)
            self._refresh_style()

        def keyPressEvent(self, event: QKeyEvent) -> None:
            if not self._recording:
                super().keyPressEvent(event)
                return
            if event.isAutoRepeat():
                event.accept()
                return
            key = _key_name(event.key(), event.text())
            if not key:
                event.accept()
                return
            parts = _modifier_names(event.modifiers())
            if key not in parts:
                parts.append(key)
            self.setValue("+".join(parts))
            self.shortcutChanged.emit(self._value)
            self._finish_capture()
            event.accept()

        def focusOutEvent(self, event) -> None:
            if self._recording:
                self._finish_capture()
            super().focusOutEvent(event)

        def _finish_capture(self) -> None:
            self._recording = False
            self.setProperty("recording", False)
            self._refresh_style()

        def setAttentionAccent(self, color: str) -> None:
            self._attention_color = QColor(color)
            self.update()

        def setAttentionActive(self, active: bool) -> None:
            active = bool(active) and not self._attention_dismissed
            if self._attention_active == active:
                return
            self._attention_active = active
            self._attention_animation.stop()
            if not active:
                self.setAttentionProgress(0.0)
            elif motion_enabled():
                self._attention_animation.start()
            else:
                self.setAttentionProgress(0.85)

        def dismissAttention(self) -> None:
            self._attention_dismissed = True
            self.setAttentionActive(False)

        def attentionActive(self) -> bool:
            return self._attention_active

        def attentionProgress(self) -> float:
            return self._attention_progress

        def setAttentionProgress(self, value: float) -> None:
            self._attention_progress = max(0.0, min(1.0, float(value)))
            self.update()

        attentionProgress = Property(float, attentionProgress, setAttentionProgress)

        def paintEvent(self, event) -> None:
            super().paintEvent(event)
            if not self._attention_active or self._recording or self._attention_progress <= 0:
                return
            color = QColor(self._attention_color)
            color.setAlpha(round(110 + (145 * self._attention_progress)))
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(color, 2.0 + (0.5 * self._attention_progress)))
            outline = self.rect().adjusted(2, 2, -2, -2)
            painter.drawRoundedRect(outline, 10, 10)

        def _refresh_style(self) -> None:
            self.style().unpolish(self)
            self.style().polish(self)

            while self._keycap_layout.count():
                item = self._keycap_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            if self._recording:
                label = QLabel("Press your shortcut…")
                label.setObjectName("ShortcutHint")
                label.setProperty("recording", True)
                label.setAttribute(Qt.WA_TransparentForMouseEvents)
                self._keycap_layout.addWidget(label)
            elif not self._value:
                label = QLabel("Click, then press shortcut")
                label.setObjectName("ShortcutHint")
                label.setAttribute(Qt.WA_TransparentForMouseEvents)
                self._keycap_layout.addWidget(label)
            else:
                parts = [part.strip() for part in self._value.split("+") if part.strip()]
                for index, part in enumerate(parts):
                    if index:
                        separator = QLabel("+")
                        separator.setObjectName("ShortcutSeparator")
                        separator.setAttribute(Qt.WA_TransparentForMouseEvents)
                        self._keycap_layout.addWidget(separator)
                    keycap = QLabel(_shortcut_label(part))
                    keycap.setObjectName("ShortcutKeycap")
                    keycap.setAttribute(Qt.WA_TransparentForMouseEvents)
                    self._keycap_layout.addWidget(keycap)
            self.update()

    return ShortcutRecorder(value)


def create_pulsing_shortcut_display(value: str, accent: str):
    """Create a non-interactive keycap display with the onboarding attention pulse."""
    from PySide6.QtCore import QEasingCurve, Property, QPropertyAnimation, Qt
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy

    from .windows_ui import motion_enabled

    class ShortcutDisplay(QFrame):
        def __init__(self, shortcut: str, color: str):
            super().__init__()
            self._value = ""
            self._attention_active = False
            self._attention_dismissed = False
            self._attention_progress = 0.0
            self._attention_color = QColor(color)
            self._attention_animation = QPropertyAnimation(self, b"attentionProgress", self)
            self._attention_animation.setDuration(1200)
            self._attention_animation.setKeyValueAt(0.0, 0.25)
            self._attention_animation.setKeyValueAt(0.5, 1.0)
            self._attention_animation.setKeyValueAt(1.0, 0.25)
            self._attention_animation.setEasingCurve(QEasingCurve.InOutSine)
            self._attention_animation.setLoopCount(-1)
            self.setObjectName("ShortcutDisplay")
            self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            self.setFocusPolicy(Qt.NoFocus)
            self._layout = QHBoxLayout(self)
            self._layout.setContentsMargins(11, 7, 11, 7)
            self._layout.setSpacing(5)
            self.setValue(shortcut)

        def setValue(self, shortcut: str) -> None:
            self._value = str(shortcut or "").strip().lower()
            while self._layout.count():
                item = self._layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            parts = [part.strip() for part in self._value.split("+") if part.strip()]
            for index, part in enumerate(parts):
                if index:
                    separator = QLabel("+")
                    separator.setObjectName("ShortcutSeparator")
                    self._layout.addWidget(separator)
                keycap = QLabel(_shortcut_label(part))
                keycap.setObjectName("ShortcutKeycap")
                self._layout.addWidget(keycap)
            self.setAccessibleDescription(format_shortcut(self._value))
            self.updateGeometry()

        def setAttentionAccent(self, color: str) -> None:
            self._attention_color = QColor(color)
            self.update()

        def setAttentionActive(self, active: bool) -> None:
            active = bool(active) and not self._attention_dismissed
            if self._attention_active == active:
                return
            self._attention_active = active
            self._attention_animation.stop()
            if not active:
                self.setAttentionProgress(0.0)
            elif motion_enabled():
                self._attention_animation.start()
            else:
                self.setAttentionProgress(0.85)

        def dismissAttention(self) -> None:
            self._attention_dismissed = True
            self.setAttentionActive(False)

        def attentionActive(self) -> bool:
            return self._attention_active

        def attentionProgress(self) -> float:
            return self._attention_progress

        def setAttentionProgress(self, value: float) -> None:
            self._attention_progress = max(0.0, min(1.0, float(value)))
            self.update()

        attentionProgress = Property(float, attentionProgress, setAttentionProgress)

        def paintEvent(self, event) -> None:
            super().paintEvent(event)
            if not self._attention_active or self._attention_progress <= 0:
                return
            color = QColor(self._attention_color)
            color.setAlpha(round(110 + (145 * self._attention_progress)))
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(color, 2.0 + (0.5 * self._attention_progress)))
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 9, 9)

    return ShortcutDisplay(value, accent)


def _modifier_names(modifiers) -> list[str]:
    from PySide6.QtCore import Qt

    mapping = [
        (Qt.ControlModifier, "ctrl"),
        (Qt.AltModifier, "alt"),
        (Qt.ShiftModifier, "shift"),
        (Qt.MetaModifier, "win"),
    ]
    return [name for flag, name in mapping if modifiers & flag]


def _key_name(key: int, text: str) -> str:
    from PySide6.QtCore import Qt

    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(ord("a") + key - Qt.Key_A)
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(ord("0") + key - Qt.Key_0)
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f"f{key - Qt.Key_F1 + 1}"
    special = {
        Qt.Key_Space: "space",
        Qt.Key_Backspace: "backspace",
        Qt.Key_Delete: "delete",
        Qt.Key_Return: "enter",
        Qt.Key_Enter: "enter",
        Qt.Key_Escape: "esc",
        Qt.Key_Tab: "tab",
        Qt.Key_Backtab: "tab",
        Qt.Key_Home: "home",
        Qt.Key_End: "end",
        Qt.Key_PageUp: "pageup",
        Qt.Key_PageDown: "pagedown",
        Qt.Key_Left: "left",
        Qt.Key_Right: "right",
        Qt.Key_Up: "up",
        Qt.Key_Down: "down",
        Qt.Key_Insert: "insert",
    }
    if key in special:
        return special[key]
    if key in {Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta}:
        return ""
    cleaned = text.strip().lower()
    return cleaned if len(cleaned) == 1 and cleaned.isprintable() else ""
