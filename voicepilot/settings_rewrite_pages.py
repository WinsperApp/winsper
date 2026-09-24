from __future__ import annotations

from dataclasses import replace
from pathlib import Path


from .ai_catalog import DEFAULT_POLISH_MODEL_ID, POLISH_MODELS, polish_model
from .ai_runtime import model_is_installed
from .settings_rewrite_embedded import build_embedded_runtime_section
from .settings_rewrite_ollama import build_ollama_runtime_sections
from .settings_widgets import create_settings_combo
from .settings_helpers import (
    ollama_combo_values,
    ollama_selected_model,
    text_value,
)


class SettingsRewritePagesMixin:
    def _build_rewrite_page(self):
        from PySide6.QtCore import QSignalBlocker, QTimer, Qt
        from PySide6.QtWidgets import (
            QButtonGroup,
            QFileDialog,
            QFrame,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QVBoxLayout,
        )

        page, layout = self._page(
            "Polish AI",
            "Choose how Winsper improves your writing and manage optional local setup.",
        )
        provider_widget = self._combo(
            "rewrite.provider",
            self.config.rewrite.provider,
            ["embedded", "ollama"],
        )
        provider_widget.setParent(page)
        provider_widget.hide()

        embedded = build_embedded_runtime_section(self, layout, provider_widget)
        self._ollama_health_state = embedded.ollama_health_state
        ollama = build_ollama_runtime_sections(
            self,
            layout,
            embedded.ollama_health_state,
            embedded.refresh_model_status,
        )
        self._ollama_model_widget = ollama.model_widget

        provider_intro = QFrame()
        provider_intro.setObjectName("ProviderIntro")
        provider_intro_layout = QVBoxLayout(provider_intro)
        provider_intro_layout.setContentsMargins(18, 16, 18, 16)
        provider_intro_layout.setSpacing(12)
        engine_title = QLabel("AI provider")
        engine_title.setObjectName("ProviderTitle")
        engine_detail = QLabel("Use Winsper AI for managed local Polish, or connect an Ollama setup you already use.")
        engine_detail.setObjectName("Muted")
        engine_detail.setWordWrap(True)
        provider_intro_layout.addWidget(engine_title)
        provider_intro_layout.addWidget(engine_detail)

        engine_selector = QFrame()
        engine_selector.setObjectName("QualitySelector")
        engine_selector_layout = QHBoxLayout(engine_selector)
        engine_selector_layout.setContentsMargins(4, 4, 4, 4)
        engine_selector_layout.setSpacing(4)
        engine_group = QButtonGroup(engine_selector)
        engine_group.setExclusive(True)
        engine_buttons = {}
        for label, value in (("Winsper AI", "embedded"), ("Ollama", "ollama")):
            button = QPushButton(label)
            button.setObjectName("ProviderOption")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(f"Use {label} for Polish")
            engine_group.addButton(button)
            engine_selector_layout.addWidget(button, 1)
            engine_buttons[value] = button
        provider_intro_layout.addWidget(engine_selector)

        def connection_surface(status, detail, button, object_name: str):
            surface = QFrame()
            surface.setObjectName(object_name)
            surface_layout = QHBoxLayout(surface)
            surface_layout.setContentsMargins(0, 2, 0, 0)
            surface_layout.setSpacing(16)
            copy = QVBoxLayout()
            copy.setSpacing(4)
            copy.addWidget(status)
            copy.addWidget(detail)
            surface_layout.addLayout(copy, 1)
            button.setMinimumWidth(118)
            button.setMaximumWidth(140)
            surface_layout.addWidget(button, 0, Qt.AlignRight | Qt.AlignVCenter)
            return surface

        winsper_connection = connection_surface(
            embedded.connection_status,
            embedded.connection_detail,
            embedded.check_button,
            "WinsperProviderConnection",
        )
        ollama_connection = connection_surface(
            ollama.connection_status,
            ollama.connection_detail,
            ollama.check_button,
            "OllamaProviderConnection",
        )
        provider_intro_layout.addWidget(winsper_connection)
        provider_intro_layout.addWidget(ollama_connection)

        ollama_settings = QFrame()
        ollama_settings.setObjectName("OllamaProviderSettings")
        ollama_settings_layout = QVBoxLayout(ollama_settings)
        ollama_settings_layout.setContentsMargins(0, 2, 0, 0)
        ollama_settings_layout.setSpacing(10)
        self._row(
            ollama_settings_layout,
            "Model",
            "Choose a model detected in your local Ollama service.",
            ollama.model_widget,
        )
        self._row(
            ollama_settings_layout,
            "Service address",
            "Where Winsper connects to Ollama on this PC.",
            ollama.service_widget,
        )
        self._row(
            ollama_settings_layout,
            "Keep model ready",
            "Faster repeat Polish actions, with higher memory use.",
            ollama.keep_ready,
        )
        provider_intro_layout.addWidget(ollama_settings)
        layout.addWidget(provider_intro)

        local_model = self._card(
            layout,
            "Local model",
            "Downloaded once and kept on this PC.",
            surface=True,
        )
        local_model_wrapper = local_model.parentWidget()
        local_model_wrapper.setObjectName("WinsperModelPanel")
        model_selector = create_settings_combo(
            lambda: self.palette,
            accessible_name="Polish model",
        )
        recommended_model = polish_model(DEFAULT_POLISH_MODEL_ID)
        ordered_models = [
            recommended_model,
            *(model for model in POLISH_MODELS if model.id != recommended_model.id),
        ]
        for model in ordered_models:
            model_selector.addItem(model.label, model.id)
        custom_model_key = "__custom_local_model__"
        model_selector.addItem("Custom local model…", custom_model_key)
        self._simple_row(
            local_model,
            "Polish model",
            "The recommended option appears first.",
            model_selector,
            compact=True,
        )
        recommendation = QLabel(f"Recommended · {recommended_model.label}")
        recommendation.setObjectName("Muted")
        local_model.addWidget(recommendation, alignment=Qt.AlignLeft)

        model_summary = QFrame()
        model_summary.setObjectName("ModelSummary")
        model_summary_layout = QHBoxLayout(model_summary)
        model_summary_layout.setContentsMargins(16, 12, 12, 12)
        model_summary_layout.setSpacing(14)
        model_summary_layout.addWidget(embedded.model_status, 1)
        model_summary_layout.addWidget(
            embedded.remove_model_button,
            0,
            Qt.AlignRight | Qt.AlignVCenter,
        )
        model_summary_layout.addWidget(
            embedded.install_model_button,
            0,
            Qt.AlignRight | Qt.AlignVCenter,
        )
        local_model.addWidget(model_summary)
        local_model.addWidget(embedded.model_feedback)

        advanced_model = self.widgets.get("rewrite.llama_model_id")
        path_widget = self.widgets.get("rewrite.llama_model_path")

        def sync_model_selector() -> None:
            model_id = text_value(advanced_model) if advanced_model is not None else self.config.rewrite.llama_model_id
            model_path = text_value(path_widget) if path_widget is not None else self.config.rewrite.llama_model_path
            custom_index = model_selector.findData(custom_model_key)
            blocker = QSignalBlocker(model_selector)
            try:
                model_selector.setItemText(custom_index, "Custom local model…")
                if model_path:
                    model_selector.setItemText(custom_index, f"Custom · {Path(model_path).name}")
                    target_index = custom_index
                else:
                    target_index = model_selector.findData(model_id)
                    if target_index < 0:
                        label = f"Custom · {model_id}" if model_id else "Custom local model…"
                        model_selector.setItemText(custom_index, label)
                        target_index = custom_index
                model_selector.setCurrentIndex(target_index)
            finally:
                del blocker

        def apply_model_widgets(model_id: str, model_path: str) -> None:
            updates = (
                (provider_widget, "setCurrentText", "embedded"),
                (advanced_model, "setCurrentText", model_id),
                (path_widget, "setText", model_path),
            )
            blockers = [QSignalBlocker(widget) for widget, _setter, _value in updates if widget is not None]
            for widget, setter, value in updates:
                if widget is not None:
                    getattr(widget, setter)(value)
            del blockers

        def refresh_model_choice() -> None:
            embedded.refresh_model_status()
            sync_model_selector()
            refresh_consumer = getattr(self, "_refresh_polish_quality", None)
            if callable(refresh_consumer):
                refresh_consumer()

        def choose_custom_local_model() -> bool:
            configured = self.config.rewrite.llama_model_path.strip()
            start_dir = str(Path(configured).parent) if configured else str(Path.home())
            selected, _filter = QFileDialog.getOpenFileName(
                self.window,
                "Choose a local Polish model",
                start_dir,
                "GGUF models (*.gguf)",
            )
            if not selected:
                return False
            selected_path = Path(selected)
            if selected_path.suffix.lower() != ".gguf" or not selected_path.is_file():
                self.status.setText("Choose a valid GGUF model file.")
                return False
            self._pending_polish_selection = None
            apply_model_widgets("", str(selected_path))
            self.config.rewrite.provider = "embedded"
            self.config.rewrite.llama_model_id = ""
            self.config.rewrite.llama_model_path = str(selected_path)
            self._save(silent=True)
            refresh_model_choice()
            self.status.setText("Custom local Polish model selected.")
            return True

        def select_local_model(index: int) -> None:
            selected = str(model_selector.itemData(index) or "")
            if selected == custom_model_key:
                if not choose_custom_local_model():
                    sync_model_selector()
                return
            if not selected:
                return
            model = polish_model(selected)
            if not model_is_installed(model):
                pending = getattr(self, "_pending_polish_selection", None)
                if pending is None or pending[-1] != model.id:
                    self._pending_polish_selection = (
                        self.config.rewrite.provider,
                        self.config.rewrite.llama_model_id,
                        self.config.rewrite.llama_model_path,
                        model.id,
                    )
                apply_model_widgets(model.id, "")
                refresh_model_choice()
                self.status.setText(f"{model.label} needs a one-time download.")
                QTimer.singleShot(0, embedded.ensure_embedded_model_ready)
                return
            self._pending_polish_selection = None
            apply_model_widgets(model.id, "")
            self.config.rewrite.provider = "embedded"
            self.config.rewrite.llama_model_id = model.id
            self.config.rewrite.llama_model_path = ""
            self._save(silent=True)
            refresh_model_choice()

        model_selector.currentIndexChanged.connect(select_local_model)
        if advanced_model is not None:
            advanced_model.currentTextChanged.connect(lambda _value: sync_model_selector())
        if path_widget is not None:
            path_widget.textChanged.connect(lambda _value: sync_model_selector())
        sync_model_selector()

        acceleration_row = QFrame()
        acceleration_row.setObjectName("NvidiaAccelerationRow")
        acceleration_layout = QVBoxLayout(acceleration_row)
        acceleration_layout.setContentsMargins(18, 14, 18, 14)
        acceleration_layout.setSpacing(8)
        acceleration_heading = QHBoxLayout()
        acceleration_heading.setSpacing(20)
        acceleration_copy = QVBoxLayout()
        acceleration_copy.setSpacing(4)
        acceleration_title = QLabel(embedded.runtime_action)
        acceleration_title.setObjectName("RowTitle")
        acceleration_copy.addWidget(acceleration_title)
        acceleration_copy.addWidget(embedded.runtime_status)
        acceleration_heading.addLayout(acceleration_copy, 1)
        acceleration_heading.addWidget(
            embedded.acceleration_toggle,
            0,
            Qt.AlignRight | Qt.AlignVCenter,
        )
        acceleration_layout.addLayout(acceleration_heading)
        acceleration_layout.addWidget(embedded.runtime_progress)
        acceleration_actions = QHBoxLayout()
        acceleration_actions.addStretch(1)
        acceleration_actions.addWidget(embedded.runtime_cancel_button)
        acceleration_layout.addLayout(acceleration_actions)
        layout.addWidget(acceleration_row)

        def sync_provider_surface(value: str) -> None:
            provider = value.strip() or "embedded"
            button = engine_buttons.get(provider)
            if button is not None:
                button.setChecked(True)
            embedded_selected = provider == "embedded"
            winsper_connection.setVisible(embedded_selected)
            ollama_connection.setVisible(not embedded_selected)
            ollama_settings.setVisible(not embedded_selected)
            local_model_wrapper.setVisible(embedded_selected)
            acceleration_row.setVisible(embedded_selected)
            embedded.refresh_model_status()
            if embedded_selected:
                QTimer.singleShot(0, embedded.ensure_embedded_model_ready)
            refresh_consumer = getattr(self, "_refresh_polish_quality", None)
            if callable(refresh_consumer):
                refresh_consumer()

        def select_engine(provider: str) -> None:
            if provider_widget.currentText().strip() == provider:
                return
            provider_widget.setCurrentText(provider)
            self._save(silent=True)
            self.status.setText("Winsper AI selected." if provider == "embedded" else "Ollama selected.")

        for provider, button in engine_buttons.items():
            button.clicked.connect(lambda _checked=False, selected=provider: select_engine(selected))
        provider_widget.currentTextChanged.connect(sync_provider_surface)

        def refresh_selected_model() -> None:
            embedded.refresh_model_status()
            if provider_widget.currentText().strip() == "embedded":
                QTimer.singleShot(0, embedded.ensure_embedded_model_ready)

        ollama.model_widget.currentTextChanged.connect(lambda _value: refresh_selected_model())
        sync_provider_surface(provider_widget.currentText())

        def refresh_polish_model_setup() -> None:
            sync_model_selector()
            sync_provider_surface(provider_widget.currentText())

        self._refresh_polish_model_setup = refresh_polish_model_setup
        layout.addStretch(1)
        return page

    def _current_rewrite_config(self):

        return replace(
            self.config.rewrite,
            provider=text_value(self.widgets["rewrite.provider"]),
            ollama_url=text_value(self.widgets["rewrite.ollama_url"]),
            model=text_value(self.widgets["rewrite.model"]),
            temperature=self.config.rewrite.temperature,
            timeout_seconds=self.config.rewrite.timeout_seconds,
            ollama_keep_alive=self.config.rewrite.ollama_keep_alive,
            llama_server_path=text_value(self.widgets["rewrite.llama_server_path"]),
            llama_model_id=text_value(self.widgets["rewrite.llama_model_id"]),
            llama_model_path=text_value(self.widgets["rewrite.llama_model_path"]),
            llama_device=text_value(self.widgets["rewrite.llama_device"]),
            llama_gpu_layers=text_value(self.widgets["rewrite.llama_gpu_layers"]),
        )

    def _sync_ollama_model_widget(self, health, model_widget=None) -> None:
        state = getattr(self, "_ollama_health_state", None)
        if isinstance(state, dict):
            state["value"] = health
        canonical = self.widgets.get("rewrite.model")
        widget = model_widget or canonical
        if widget is None:
            return
        current = text_value(widget)
        values = ollama_combo_values(health.models, current)
        selected = ollama_selected_model(health, current)
        targets = [widget]
        if selected and canonical is not None and canonical is not widget:
            targets.append(canonical)
        for target in targets:
            previous = target.blockSignals(True)
            try:
                if hasattr(target, "addItems"):
                    target.clear()
                    target.addItems(values)
                    target.setCurrentText(selected)
                    if hasattr(target, "lineEdit") and target.lineEdit() is not None:
                        placeholder = (
                            "Choose an installed model"
                            if health.models
                            else "No models installed"
                            if health.reachable
                            else "Check connection first"
                        )
                        target.lineEdit().setPlaceholderText(placeholder)
                else:
                    target.setText(selected)
            finally:
                target.blockSignals(previous)
