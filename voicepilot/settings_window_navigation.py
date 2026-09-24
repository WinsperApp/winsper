from __future__ import annotations

from .settings_icons import settings_nav_icon
from .windows_ui import apply_native_window_style


class SettingsWindowNavigationMixin:
    """Page routing, lazy loading, and advanced settings dialogs."""

    def _show_page(self, index: int) -> None:
        self._ensure_page_loaded(index)
        self.stack.setCurrentIndex(index)
        for button_index, button in self.nav_buttons.items():
            active = button_index == index
            button.setChecked(active)
            color = self.palette.accent if active else self.palette.muted
            button.setIcon(settings_nav_icon(self.page_icons[button_index], color))

    def _show_named_page(self, name: str) -> None:
        personalize_tab = {
            "Dictionary": 0,
            "Memory": 0,
            "Word Memory": 0,
            "Snippets": 1,
            "Text Shortcuts": 1,
        }.get(name)
        name = {
            "Home": "General",
            "Voice": "Dictation",
            "More": "About",
            "Advanced": "About",
            "Diagnostics": "About",
            "Controls": "Dictation",
            "Hotkeys": "Dictation",
            "Shortcuts": "Dictation",
            "Settings": "General",
            "Interface": "General",
            "Audio": "Dictation",
            "Language": "Language + Speech",
            "AI Models": "Language + Speech",
            "Language & Speech": "Language + Speech",
            "Dictionary": "Personalize",
            "Memory": "Personalize",
            "Word Memory": "Personalize",
            "Snippets": "Personalize",
            "Text Shortcuts": "Personalize",
            "Config": "General",
            "Dictation Details": "Dictation",
        }.get(name, name)
        try:
            index = self.page_names.index(name)
        except ValueError:
            return
        self._show_page(index)
        if personalize_tab is not None:
            tabs = getattr(self, "personalize_tabs", None)
            if tabs is not None:
                tabs.setCurrentIndex(personalize_tab)

    def _open_modal_page(self, name: str, builder) -> None:
        from PySide6.QtWidgets import QDialog, QVBoxLayout

        self._ensure_page_loaded(self.page_names.index("Hidden Fields"))
        cached = self._modal_dialogs.get(name)
        existing = getattr(self, "_advanced_dialog", None)
        if existing is not None and existing.isVisible() and existing is not cached:
            existing.close()
        if cached is not None:
            cached.show()
            cached.raise_()
            cached.activateWindow()
            apply_native_window_style(cached, self.palette)
            self._advanced_dialog = cached
            return
        dialog = QDialog(self.window)
        dialog.setObjectName("SettingsModal")
        dialog.setWindowTitle(f"Winsper {name}")
        dialog.resize(1040, 720)
        dialog.setMinimumSize(900, 620)
        dialog.setStyleSheet(self.window.styleSheet())
        dialog.setModal(False)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(builder())
        self._button_cursor_policy.apply_tree(dialog)
        dialog.show()
        apply_native_window_style(dialog, self.palette)
        self._modal_dialogs[name] = dialog
        self._advanced_dialog = dialog

    def _open_advanced_models(self) -> None:
        self._open_modal_page("Dictation models", self._build_models_page)
        preferred_language = getattr(self, "_pending_dictation_language", None)
        preferred_model = getattr(self, "_pending_dictation_model", None)
        sync_controls = getattr(self, "_sync_advanced_model_controls", None)
        if callable(sync_controls):
            sync_controls(
                preferred_language,
                preferred_model,
                prefer_recommended=preferred_language is not None,
            )

    def _open_advanced_polish_ai(self) -> None:
        self._open_modal_page("Polish AI", self._build_rewrite_page)
        dialog = self._advanced_dialog
        if not dialog.property("polishRollbackConnected"):
            dialog.finished.connect(self._restore_staged_polish_selection)
            dialog.setProperty("polishRollbackConnected", True)

    def _restore_staged_polish_selection(self) -> None:
        """Restore the working preset when a requested model remains unavailable."""
        from PySide6.QtCore import QSignalBlocker

        from .ai_catalog import polish_model
        from .ai_runtime import model_is_installed
        from .settings_helpers import text_value

        pending = getattr(self, "_pending_polish_selection", None)
        self._pending_polish_selection = None
        if pending is None:
            return
        provider, model_id, model_path, requested_id = pending
        requested = polish_model(requested_id)
        provider_widget = self.widgets.get("rewrite.provider")
        advanced_model = self.widgets.get("rewrite.llama_model_id")
        path_widget = self.widgets.get("rewrite.llama_model_path")
        staged_provider = text_value(provider_widget) if provider_widget is not None else ""
        staged_path = text_value(path_widget) if path_widget is not None else ""
        should_restore = not model_is_installed(requested) and staged_provider == "embedded" and not staged_path
        if not should_restore:
            refresh_quality = getattr(self, "_refresh_polish_quality", None)
            if callable(refresh_quality):
                refresh_quality()
            return

        self.config.rewrite.provider = provider
        self.config.rewrite.llama_model_id = model_id
        self.config.rewrite.llama_model_path = model_path
        updates = (
            (provider_widget, "setCurrentText", provider),
            (advanced_model, "setCurrentText", model_id),
            (path_widget, "setText", model_path),
        )
        blockers = [QSignalBlocker(widget) for widget, _setter, _value in updates if widget is not None]
        for widget, setter, value in updates:
            if widget is not None:
                getattr(widget, setter)(value)
        del blockers
        self._save(silent=True)
        refresh_setup = getattr(self, "_refresh_polish_model_setup", None)
        if callable(refresh_setup):
            refresh_setup()
        refresh_quality = getattr(self, "_refresh_polish_quality", None)
        if callable(refresh_quality):
            refresh_quality()

    def _ensure_page_loaded(self, index: int) -> None:
        if self.pages_loaded[index]:
            return
        placeholder = self.stack.widget(index)
        page = self.page_builders[index]()
        self.stack.removeWidget(placeholder)
        placeholder.deleteLater()
        self.stack.insertWidget(index, page)
        self.pages_loaded[index] = True
        self._button_cursor_policy.apply_tree(page)

    def _ensure_all_pages_loaded(self) -> None:
        for index in range(len(self.page_builders)):
            self._ensure_page_loaded(index)

    def _page(self, title: str, subtitle: str):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

        scroll = QScrollArea()
        scroll.setObjectName("Page")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        scroll.viewport().setAutoFillBackground(True)
        content = QWidget()
        content.setObjectName("PageContent")
        content.setMinimumWidth(0)
        content.setMaximumWidth(1040)
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(14)
        header = QVBoxLayout()
        header.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        sub = QLabel(subtitle)
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        if title:
            header.addWidget(heading)
        if subtitle:
            header.addWidget(sub)
        if title or subtitle:
            layout.addLayout(header)
        scroll.setWidget(content)
        return scroll, layout
