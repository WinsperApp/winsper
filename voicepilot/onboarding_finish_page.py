from __future__ import annotations


class OnboardingFinishPageMixin:
    def _build_finish_page(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

        from .settings_icons import settings_nav_icon

        page, layout = self._page(
            "You're ready to speak.",
            "Review your setup, then choose how you want to continue.",
        )
        hero = self._card(layout, "", object_name="FinishCard")
        hero_header = QHBoxLayout()
        hero_header.setSpacing(14)
        mark = QLabel()
        mark.setObjectName("FinishMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(50, 50)
        mark.setPixmap(settings_nav_icon("check", "#ffffff", 25).pixmap(25, 25))
        hero_header.addWidget(mark, 0, Qt.AlignVCenter)
        complete_copy = QVBoxLayout()
        complete_copy.setSpacing(2)
        self.finish_title = QLabel("Setup complete")
        self.finish_title.setObjectName("CardTitle")
        self.finish_detail = QLabel("Winsper is ready to use across your apps.")
        self.finish_detail.setObjectName("Muted")
        self.finish_detail.setWordWrap(True)
        complete_copy.addWidget(self.finish_title)
        complete_copy.addWidget(self.finish_detail)
        hero_header.addLayout(complete_copy, 1)
        hero.addLayout(hero_header)

        summary = QFrame()
        summary.setObjectName("SetupSummary")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(16, 12, 16, 12)
        summary_layout.setSpacing(9)
        self.finish_language_value = self._summary_row(summary_layout, "Language")
        self.finish_quality_value = self._summary_row(summary_layout, "Transcription")
        self.finish_polish_value = self._summary_row(summary_layout, "Polish")
        self.finish_shortcut_value = self._summary_row(summary_layout, "Dictate shortcut")
        hero.addWidget(summary)
        hero.addWidget(self.startup_check)
        tip = QLabel("You can change any choice later from Winsper Settings.")
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        hero.addWidget(tip)

        ready = self._card(layout, "Ready to go", "Winsper is free to use. You can change these choices later in Settings.")
        self.finish_button = QPushButton("Launch Winsper")
        self.finish_button.setObjectName("PrimaryButton")
        self.finish_button.setAccessibleDescription("Finish setup and launch Winsper")
        self.finish_button.clicked.connect(self._finish)
        ready.addWidget(self.finish_button)
        layout.addStretch(1)
        return page
