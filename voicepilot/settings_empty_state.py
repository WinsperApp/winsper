from __future__ import annotations


class SettingsEmptyStateMixin:
    def _empty_state(self, text: str, title: str = "Nothing here yet"):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout

        panel = QFrame()
        panel.setObjectName("EmptyStatePanel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        panel.setMinimumWidth(0)
        content = QVBoxLayout(panel)
        content.setContentsMargins(24, 22, 24, 22)
        content.setSpacing(5)

        mark = QLabel("\u2022")
        mark.setObjectName("EmptyStateMark")
        mark.setAlignment(Qt.AlignCenter)
        heading = QLabel(title)
        heading.setObjectName("EmptyStateTitle")
        heading.setAlignment(Qt.AlignCenter)
        detail = QLabel(text)
        detail.setObjectName("EmptyStateDetail")
        detail.setAlignment(Qt.AlignCenter)
        detail.setWordWrap(True)
        detail.setMinimumWidth(0)
        detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        content.addWidget(mark)
        content.addWidget(heading)
        content.addWidget(detail)
        return panel
