from __future__ import annotations

import queue
import threading
import time

from .ollama import OllamaHealth, check_ollama_health
from .settings_helpers import (
    friendly_check_error,
    model_matches,
    ollama_detail_text,
    ollama_status_bar_text,
    ollama_status_text,
    ollama_tone,
    text_value,
)
from types import SimpleNamespace

OLLAMA_UI_TIMEOUT_SECONDS = 4.0


def build_ollama_runtime_sections(owner, _layout, ollama_health_state, refresh_model_status):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

    from .settings_toggle import ToggleSwitch
    from .windows_ui import motion_enabled

    initial_health = OllamaHealth(
        reachable=False,
        model_available=False,
        model=owner.config.rewrite.model,
        models=(),
        tags_url=f"{owner.config.rewrite.ollama_url.rstrip('/')}/api/tags",
        message="Connection not checked",
        detail="Check the connection when you want to use Ollama.",
    )
    ollama_health_state["value"] = initial_health
    test = QPushButton("Check connection")
    test.setObjectName("DownloadControlButton")
    health_wrapper = QFrame()
    health_wrapper.hide()
    health_card = QVBoxLayout(health_wrapper)
    health_card.setContentsMargins(0, 0, 0, 0)
    health_card.addWidget(test)
    health = QLabel(ollama_status_text(initial_health))
    health.setObjectName("StatusPanel")
    health.setProperty("tone", "neutral")
    health.setWordWrap(True)
    detail = QLabel(ollama_detail_text(initial_health, owner.config.rewrite.model))
    detail.setObjectName("Muted")
    detail.setWordWrap(True)
    detail.hide()
    health_card.addWidget(health)
    health_card.addWidget(detail)

    def test_ollama() -> None:
        health.setText("Checking Ollama background service...")
        owner._set_tone(health, "neutral")
        detail.setText("This checks Ollama's local API and usually returns in under two seconds.")
        detail.show()
        test.setEnabled(False)
        events: "queue.Queue[OllamaHealth]" = queue.Queue(maxsize=1)
        config = owner._current_rewrite_config()
        deadline = time.monotonic() + OLLAMA_UI_TIMEOUT_SECONDS

        def worker() -> None:
            try:
                result = check_ollama_health(config, timeout_seconds=2.0)
            except Exception as exc:
                result = OllamaHealth(
                    reachable=False,
                    model_available=False,
                    model=config.model,
                    models=(),
                    tags_url=f"{config.ollama_url.rstrip('/')}/api/tags",
                    message="Ollama could not be checked",
                    detail=friendly_check_error(exc),
                )
            try:
                events.put_nowait(result)
            except queue.Full:
                pass

        timer = QTimer(health)

        def finish(result: OllamaHealth) -> None:
            timer.stop()
            test.setEnabled(True)
            ollama_health_state["value"] = result
            owner._sync_ollama_model_widget(result, model_widget)
            health.setText(ollama_status_text(result))
            owner._set_tone(health, ollama_tone(result))
            detail.setText(ollama_detail_text(result, text_value(owner.widgets["rewrite.model"])))
            detail.show()
            owner.status.setText(ollama_status_bar_text(result))
            refresh_model_status()

        def poll() -> None:
            # Timeout wins even if the GUI event loop was briefly busy and the
            # worker completed after the deadline. Accepting that late result
            # would make the visible contract depend on machine load.
            if time.monotonic() >= deadline:
                finish(
                    OllamaHealth(
                        reachable=False,
                        model_available=False,
                        model=config.model,
                        models=(),
                        tags_url=f"{config.ollama_url.rstrip('/')}/api/tags",
                        message="Ollama did not respond",
                        detail="Check that Ollama is running and the service address is correct.",
                    )
                )
                return
            try:
                result = events.get_nowait()
            except queue.Empty:
                return
            finish(result)

        timer.timeout.connect(poll)
        timer.start(max(10, min(100, int(OLLAMA_UI_TIMEOUT_SECONDS * 1000))))
        threading.Thread(target=worker, name="WinsperOllamaHealth", daemon=True).start()

    test.clicked.connect(test_ollama)

    model_wrapper = QFrame()
    model_wrapper.hide()
    model_card = QVBoxLayout(model_wrapper)
    model_card.setContentsMargins(0, 0, 0, 0)
    model_widget = owner._combo("rewrite.model", "", [])
    model_widget.setEditable(True)
    model_widget.lineEdit().setReadOnly(True)
    blocked = model_widget.blockSignals(True)
    model_widget.clear()
    model_widget.blockSignals(blocked)
    model_widget.lineEdit().setPlaceholderText("Check connection first")
    model_card.addWidget(model_widget)

    def refresh_selected_model_status() -> None:
        result = ollama_health_state["value"]
        selected = model_widget.currentText().strip()
        available = bool(
            result is not None and result.reachable and selected and any(model_matches(selected, candidate) for candidate in result.models)
        )
        if available:
            health.setText(f"Ollama connection established · {selected}")
            owner._set_tone(health, "accent")
            detail.setText(ollama_detail_text(result, selected))
            detail.show()
        elif result is not None and result.reachable:
            health.setText(ollama_status_text(result))
            owner._set_tone(health, ollama_tone(result))

    model_widget.currentTextChanged.connect(lambda _value: refresh_selected_model_status())

    options_wrapper = QFrame()
    options_wrapper.hide()
    options_card = QVBoxLayout(options_wrapper)
    options_card.setContentsMargins(0, 0, 0, 0)
    service_widget = owner._line("rewrite.ollama_url", owner.config.rewrite.ollama_url)
    options_card.addWidget(service_widget)
    keep_ready = ToggleSwitch.create(
        checked=owner.config.rewrite.ollama_keep_alive > 0,
        accent=owner.palette.accent,
        accent2=owner.palette.accent_2,
        motion_provider=motion_enabled,
    )
    owner.theme_toggles.append(keep_ready)

    def set_keep_ready(enabled: bool) -> None:
        value = 300 if enabled else 0
        widget = owner.widgets.get("rewrite.ollama_keep_alive")
        if widget is not None:
            widget.setText(str(value))
        owner.config.rewrite.ollama_keep_alive = value
        owner._save(silent=True)

    keep_ready.toggled.connect(set_keep_ready)
    options_card.addWidget(keep_ready)

    return SimpleNamespace(
        health_wrapper=health_wrapper,
        model_wrapper=model_wrapper,
        options_wrapper=options_wrapper,
        model_widget=model_widget,
        keep_ready=keep_ready,
        service_widget=service_widget,
        check_button=test,
        connection_status=health,
        connection_detail=detail,
    )
