from __future__ import annotations


def _settings_cursor_policy(widget):
    """Find the Settings cursor policy through a modal's parent chain."""
    current = widget
    while current is not None:
        policy = getattr(current, "_winsper_cursor_policy", None)
        if policy is not None:
            return policy
        current = current.parentWidget()
    return None


def _create_settings_confirmation_dialog(
    parent,
    palette,
    *,
    title: str,
    message: str,
    confirm_label: str,
) -> object:
    """Build a compact confirmation that belongs visually to Winsper Settings."""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtWidgets import (
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
    )

    from .settings_icons import settings_nav_icon
    from .windows_ui import apply_native_window_style

    dialog = QDialog(parent)
    dialog.setObjectName("SettingsConfirmDialog")
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setFixedWidth(440)
    dialog.setStyleSheet(parent.styleSheet())

    root = QVBoxLayout(dialog)
    root.setContentsMargins(24, 22, 24, 22)
    root.setSpacing(20)

    heading = QHBoxLayout()
    heading.setSpacing(14)
    icon_tile = QFrame()
    icon_tile.setObjectName("SettingsConfirmIconTile")
    icon_tile.setFixedSize(44, 44)
    icon_layout = QHBoxLayout(icon_tile)
    icon_layout.setContentsMargins(0, 0, 0, 0)
    icon = QLabel()
    icon.setAlignment(Qt.AlignCenter)
    icon.setPixmap(settings_nav_icon("trash", palette.muted, 18).pixmap(QSize(18, 18)))
    icon_layout.addWidget(icon)
    heading.addWidget(icon_tile, 0, Qt.AlignTop)

    copy = QVBoxLayout()
    copy.setSpacing(5)
    title_label = QLabel(title)
    title_label.setObjectName("SettingsConfirmTitle")
    message_label = QLabel(message)
    message_label.setObjectName("SettingsConfirmMessage")
    message_label.setWordWrap(True)
    copy.addWidget(title_label)
    copy.addWidget(message_label)
    heading.addLayout(copy, 1)
    root.addLayout(heading)

    actions = QHBoxLayout()
    actions.setSpacing(10)
    actions.addStretch(1)
    cancel = QPushButton("Cancel")
    cancel.setObjectName("SettingsConfirmCancel")
    cancel.setCursor(Qt.PointingHandCursor)
    cancel.clicked.connect(dialog.reject)
    confirm = QPushButton(confirm_label)
    confirm.setObjectName("SettingsConfirmAccept")
    confirm.setCursor(Qt.PointingHandCursor)
    confirm.setDefault(True)
    confirm.clicked.connect(dialog.accept)
    actions.addWidget(cancel)
    actions.addWidget(confirm)
    root.addLayout(actions)

    apply_native_window_style(dialog, palette)
    return dialog


def confirm_settings_action(
    parent,
    palette,
    *,
    title: str,
    message: str,
    confirm_label: str,
) -> bool:
    dialog = _create_settings_confirmation_dialog(
        parent,
        palette,
        title=title,
        message=message,
        confirm_label=confirm_label,
    )
    cursor_policy = _settings_cursor_policy(parent)
    if cursor_policy is not None:
        cursor_policy.apply_tree(dialog)
    try:
        return bool(dialog.exec())
    finally:
        if cursor_policy is not None:
            cursor_policy.restore_after_modal()
