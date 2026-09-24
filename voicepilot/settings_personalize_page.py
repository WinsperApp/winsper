from __future__ import annotations

from .settings_widgets import add_personalize_tab_separator


class SettingsPersonalizePageMixin:
    def _build_personalize_page(self):
        from PySide6.QtWidgets import QTabWidget

        page, layout = self._page(
            "Personalize",
            "Make Winsper fluent in the words and reusable text that are yours.",
        )

        tabs = QTabWidget()
        tabs.setObjectName("PersonalizeTabs")
        tabs.addTab(self._build_memory_page(embedded=True), "Words && corrections")
        tabs.addTab(self._build_snippets_page(embedded=True), "Text shortcuts")
        add_personalize_tab_separator(tabs)
        self.personalize_tabs = tabs
        layout.addWidget(tabs, 1)
        return page
