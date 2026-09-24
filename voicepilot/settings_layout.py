from __future__ import annotations


from .settings_helpers import (
    add_list_item,
    remove_selected,
)
from .settings_widgets import ToggleSwitch
from .windows_ui import motion_enabled


class SettingsLayoutMixin:
    def _card(
        self,
        layout,
        title: str,
        subtitle: str = "",
        *,
        surface: bool = False,
        header_widget=None,
    ):
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

        card = QFrame()
        card.setObjectName("SettingsSectionPanel" if surface else "Card")
        card_layout = QVBoxLayout(card)
        if surface:
            card_layout.setContentsMargins(18, 14, 18, 14)
        else:
            card_layout.setContentsMargins(0, 8, 0, 6)
        card_layout.setSpacing(10)
        label = QLabel(title)
        label.setObjectName("CardTitle")
        if header_widget is None:
            card_layout.addWidget(label)
        else:
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(16)
            header.addWidget(label)
            header.addStretch(1)
            header.addWidget(header_widget)
            card_layout.addLayout(header)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            card_layout.addWidget(sub)
        layout.addWidget(card)
        return card_layout

    def _row(self, layout, label: str, description: str, widget) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

        row = QHBoxLayout()
        row.setSpacing(24)
        text = QVBoxLayout()
        text.setSpacing(4)
        name = QLabel(label)
        name.setObjectName("RowTitle")
        desc = QLabel(description)
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        widget.setAccessibleName(label)
        widget.setAccessibleDescription(description)
        name.setBuddy(widget)
        text.addWidget(name)
        text.addWidget(desc)
        row.addLayout(text, 1)
        row.addWidget(widget)
        layout.addLayout(row)

    def _line(self, key: str, value: str, placeholder: str = ""):
        from PySide6.QtWidgets import QLineEdit

        edit = QLineEdit(value)
        edit.setPlaceholderText(placeholder)
        edit.setMinimumWidth(260)
        self.widget_registry.register(key, edit, "editingFinished")
        self.widgets.setdefault(key, self.widget_registry.canonical(key))
        return edit

    def _shortcut(self, key: str, value: str):
        from .settings_widgets import create_shortcut_recorder

        recorder = create_shortcut_recorder(value)
        self.widget_registry.register(key, recorder, "shortcutChanged")
        self.widgets.setdefault(key, self.widget_registry.canonical(key))
        return recorder

    def _combo(self, key: str, value: str, values: list[str]):
        from .settings_widgets import create_settings_combo

        combo = create_settings_combo(lambda: self.palette)
        combo.addItems(values)
        if value in values:
            combo.setCurrentText(value)
        else:
            combo.addItem(value)
            combo.setCurrentText(value)
        combo.setMinimumWidth(260)
        self.widget_registry.register(key, combo, "currentTextChanged")
        self.widgets.setdefault(key, self.widget_registry.canonical(key))
        return combo

    def _check(self, key: str, value: bool):
        # Use palette gradient colors so toggle ON matches the Save button exactly
        a1 = self.palette.accent
        a2 = self.palette.accent_2
        toggle = ToggleSwitch.create(checked=value, accent=a1, accent2=a2, motion_provider=motion_enabled)
        self.theme_toggles.append(toggle)
        self.widget_registry.register(key, toggle, "toggled")
        self.widgets.setdefault(key, self.widget_registry.canonical(key))
        return toggle

    def _text(self, key: str, value: str):
        from PySide6.QtWidgets import QTextEdit

        text = QTextEdit()
        text.setPlainText(value)
        text.setMinimumHeight(96)
        self.widget_registry.register(key, text, "textChanged")
        self.widgets.setdefault(key, self.widget_registry.canonical(key))
        return text

    def _schedule_auto_save(self) -> None:
        timer = getattr(self, "_autosave_timer", None)
        if timer is not None:
            timer.start(500)

    def _add_list_item_and_save(self, list_widget, entry) -> None:
        before = list_widget.count()
        add_list_item(list_widget, entry)
        if list_widget.count() != before:
            self._schedule_auto_save()

    def _remove_selected_and_save(self, list_widget) -> None:
        before = list_widget.count()
        remove_selected(list_widget)
        if list_widget.count() != before:
            self._schedule_auto_save()

    def _simple_row(
        self,
        layout,
        label: str,
        description: str,
        widget,
        last: bool = False,
        compact: bool = False,
    ) -> None:
        """Borderless setting row — label+desc on left, widget on right, 1px divider below."""
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

        row_frame = QFrame()
        row_frame.setObjectName("SimpleRow")
        if not last:
            row_frame.setStyleSheet(f"QFrame#SimpleRow {{ border-bottom: 1px solid {self.palette.border_soft}; }}")
        row_layout = QHBoxLayout(row_frame)
        vertical_margin = 10 if compact else 14
        row_layout.setContentsMargins(0, vertical_margin, 0, vertical_margin)
        row_layout.setSpacing(24)
        text = QVBoxLayout()
        text.setSpacing(3)
        name = QLabel(label)
        name.setObjectName("RowTitle")
        widget.setAccessibleName(label)
        widget.setAccessibleDescription(description)
        name.setBuddy(widget)
        text.addWidget(name)
        if description:
            desc = QLabel(description)
            desc.setObjectName("Muted")
            desc.setWordWrap(True)
            text.addWidget(desc)
        row_layout.addLayout(text, 1)
        row_layout.addWidget(widget)
        layout.addWidget(row_frame)

    def _advanced_expander(self, layout, text: str = "Advanced"):
        """Collapsible Advanced section — returns the inner layout to add rows to."""
        from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout

        adv_frame = QFrame()
        adv_layout = QVBoxLayout(adv_frame)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(0)

        toggle_btn = QPushButton(f"{text}  ›")
        toggle_btn.setObjectName("AdvancedToggle")
        toggle_btn.setStyleSheet(
            f"QPushButton#AdvancedToggle {{ background: transparent; border: none; "
            f"color: {self.palette.muted}; font-size: 11px; font-weight: 500; "
            f"letter-spacing: 0.1em; text-align: left; padding: 12px 0; }}"
            f"QPushButton#AdvancedToggle:hover {{ color: {self.palette.text}; }}"
        )

        inner = QFrame()
        inner.hide()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)

        def toggle():
            visible = inner.isVisible()
            inner.setVisible(not visible)
            toggle_btn.setText(f"{text}  {'‹' if not visible else '›'}")

        toggle_btn.clicked.connect(toggle)
        adv_layout.addWidget(toggle_btn)
        adv_layout.addWidget(inner)
        layout.addWidget(adv_frame)
        return inner_layout
