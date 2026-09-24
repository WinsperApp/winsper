from __future__ import annotations

from .autostart import is_start_with_windows_enabled
from .app_context import AppContextDetector, friendly_process_label, is_winsper_window
from .config import load_config
from .control import request_control_command
from .history import HistoryStore
from .instance import SingleInstanceGuard
from .models import list_installed_models
from .rewrite_backends import check_rewrite_backend_health
from .runtime_state import read_runtime_state
from .settings_microphone import microphone_home_status
from .system_audio import list_audio_devices
from .usage import format_minutes, usage_summary
from .settings_widgets import format_shortcut
from .windows_ui import motion_enabled
from .settings_home_checks import SettingsHomeChecksMixin


class SettingsHomeMixin(SettingsHomeChecksMixin):
    def _build_home_page(self):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
        from .usage import usage_summary
        from .settings_widgets import create_settings_combo, create_theme_combo

        page, layout = self._page("General", "")
        self.home_fields = {}
        self.home_test_buttons = {}

        # Animated once, then stable. Reduced-motion users get final values.
        try:
            summary = usage_summary(self.config_path)
            words_val = str(summary.today_words)
            time_val = f"{int(summary.today_minutes_saved)} min"
            sessions_val = str(summary.today_actions)
        except Exception:
            words_val, time_val, sessions_val = "—", "—", "—"

        stats_panel = QFrame()
        stats_panel.setObjectName("StatsStrip")
        stats_row = QHBoxLayout(stats_panel)
        stats_row.setSpacing(0)
        stats_row.setContentsMargins(18, 18, 18, 18)

        p = self.palette
        grad_line = f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {p.accent_2}); border: none;"

        def _stat_col(value: str, label: str):
            col = QVBoxLayout()
            col.setSpacing(6)
            col.setAlignment(Qt.AlignCenter)
            v = QLabel("0" if value.removesuffix(" min").isdigit() else value)
            v.setObjectName("StatNumber")
            v.setAlignment(Qt.AlignCenter)
            underline = QFrame()
            underline.setFixedHeight(2)
            underline.setStyleSheet(grad_line)
            k = QLabel(label)
            k.setObjectName("StatLabel")
            k.setAlignment(Qt.AlignCenter)
            col.addWidget(v)
            col.addWidget(underline)
            col.addSpacing(4)
            col.addWidget(k)
            return col, v

        col1, self._stat_words = _stat_col(words_val, "Words spoken")
        col2, self._stat_time = _stat_col(time_val, "Time saved")
        col3, self._stat_sessions = _stat_col(sessions_val, "Dictations")
        stats_row.addLayout(col1, 1)
        stats_row.addLayout(col2, 1)
        stats_row.addLayout(col3, 1)
        layout.addWidget(stats_panel)

        self._animate_home_stats(words_val, time_val, sessions_val)

        control = QFrame()
        control.setObjectName("WinsperControl")
        control_layout = QHBoxLayout(control)
        control_layout.setContentsMargins(18, 15, 16, 15)
        control_layout.setSpacing(12)

        self.home_state_dot = QFrame()
        self.home_state_dot.setObjectName("WinsperStateDot")
        self.home_state_dot.setFixedSize(10, 10)
        control_layout.addWidget(self.home_state_dot, 0, Qt.AlignVCenter)

        state_copy = QVBoxLayout()
        state_copy.setSpacing(3)
        self.home_state_title = QLabel("Checking Winsper")
        self.home_state_title.setObjectName("WinsperStateTitle")
        self.home_state_detail = QLabel("Confirming shortcut availability.")
        self.home_state_detail.setObjectName("WinsperStateDetail")
        self.home_state_detail.setWordWrap(True)
        state_copy.addWidget(self.home_state_title)
        state_copy.addWidget(self.home_state_detail)
        control_layout.addLayout(state_copy, 1)

        self.home_pause_button = QPushButton("Pause")
        self.home_pause_button.setObjectName("WinsperStateButton")
        self.home_pause_button.clicked.connect(self._toggle_listener_state)
        control_layout.addWidget(self.home_pause_button, 0, Qt.AlignVCenter)
        layout.addWidget(control)

        settings_panel = QFrame()
        settings_panel.setObjectName("GeneralSettingsList")
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(0)

        theme = create_theme_combo(lambda: self.palette)
        theme.addItem("System", "system")
        theme.addItem("Light", "light")
        theme.addItem("Dark", "dark")
        theme_index = theme.findData(self.config.hud.theme)
        theme.setCurrentIndex(theme_index if theme_index >= 0 else 0)
        self.widget_registry.register("hud.theme", theme, "currentIndexChanged")
        self.widgets.setdefault("hud.theme", theme)
        theme.currentIndexChanged.connect(lambda _index: self._update_theme_preview(str(theme.currentData() or "system")))
        self._simple_row(
            settings_layout,
            "Appearance",
            "Use the Windows setting or choose a consistent theme.",
            theme,
        )
        hud_mode = create_settings_combo(lambda: self.palette)
        hud_mode.addItem("Full HUD", "standard")
        hud_mode.addItem("Compact HUD", "compact")
        hud_mode_index = hud_mode.findData(self.config.hud.mode)
        hud_mode.setCurrentIndex(hud_mode_index if hud_mode_index >= 0 else 0)
        self.widget_registry.register("hud.mode", hud_mode, "currentIndexChanged")
        self.widgets.setdefault("hud.mode", hud_mode)
        self._simple_row(
            settings_layout,
            "HUD style",
            "Choose full status details or a minimal recording wave.",
            hud_mode,
        )
        hud_position = create_settings_combo(lambda: self.palette)
        for label, value in (("Bottom center", "center"), ("Bottom left", "left"), ("Bottom right", "right"), ("Top center", "top")):
            hud_position.addItem(label, value)
        hud_position.setCurrentIndex(max(0, hud_position.findData(self.config.hud.position)))
        self.widget_registry.register("hud.position", hud_position, "currentIndexChanged")
        self.widgets.setdefault("hud.position", hud_position)
        self._simple_row(settings_layout, "HUD position", "Choose where Winsper appears on your primary screen.", hud_position)
        self._simple_row(
            settings_layout,
            "Launch at login",
            "Start Winsper automatically each time you log in to Windows.",
            self._check(
                "startup.start_with_windows",
                self.config.startup.start_with_windows or is_start_with_windows_enabled(self.config_path),
            ),
        )
        self._simple_row(
            settings_layout,
            "Restore clipboard",
            "Put your original clipboard content back after inserting text.",
            self._check("paste.restore_clipboard", self.config.paste.restore_clipboard),
        )
        recording_sounds = self._check("hud.recording_chimes", self.config.hud.recording_chimes)
        self._simple_row(
            settings_layout,
            "Recording sounds",
            "Hear a readiness chime before listening and another when recording stops.",
            recording_sounds,
        )
        self._simple_row(
            settings_layout,
            "Show the floating HUD",
            "Show quiet feedback while Winsper listens and works.",
            self._check("hud.enabled", self.config.hud.enabled),
            last=True,
        )
        layout.addWidget(settings_panel)

        layout.addStretch(1)
        layout.activate()
        page.widget().setMinimumHeight(layout.sizeHint().height())
        QTimer.singleShot(80, self._refresh_home_status)
        return page

    def _animate_home_stats(self, words_text: str, minutes_text: str, sessions_text: str) -> None:
        from PySide6.QtCore import QElapsedTimer, QTimer

        labels = (self._stat_words, self._stat_time, self._stat_sessions)
        final_texts = (words_text, minutes_text, sessions_text)
        try:
            targets = (int(words_text), int(minutes_text.removesuffix(" min")), int(sessions_text))
        except (TypeError, ValueError):
            for label, text in zip(labels, final_texts, strict=True):
                label.setText(text)
            return
        if not motion_enabled():
            for label, text in zip(labels, final_texts, strict=True):
                label.setText(text)
            return

        previous = getattr(self, "_stats_timer", None)
        if previous is not None:
            previous.stop()
        elapsed = QElapsedTimer()
        elapsed.start()
        timer = QTimer(self.window)
        timer.setInterval(32)

        def tick() -> None:
            progress = min(1.0, elapsed.elapsed() / 520.0)
            eased = 1.0 - (1.0 - progress) ** 3
            values = tuple(round(target * eased) for target in targets)
            labels[0].setText(str(values[0]))
            labels[1].setText(f"{values[1]} min")
            labels[2].setText(str(values[2]))
            if progress >= 1.0:
                timer.stop()
                for label, text in zip(labels, final_texts, strict=True):
                    label.setText(text)

        timer.timeout.connect(tick)
        self._stats_timer = timer
        tick()
        timer.start()

    def _home_tile(self, key: str, title: str):
        from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

        tile = QFrame()
        tile.setObjectName("StatusTile")
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(16, 14, 16, 14)
        tile_layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("RowTitle")
        state = QLabel("Checking")
        state.setObjectName("HealthState")
        state.setProperty("tone", "neutral")
        detail = QLabel("")
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        tile_layout.addWidget(title_label)
        tile_layout.addWidget(state)
        tile_layout.addWidget(detail)
        self.home_fields[key] = (state, detail)
        return tile

    def _refresh_home_status(self) -> None:
        self.config = load_config(self.config_path)
        running = self._listener_is_running()
        state = read_runtime_state(self.config_path, max_age_seconds=60) if running else None

        if not running:
            self._set_home_control(
                "Winsper is not running",
                "Open Winsper to enable Dictation and Polish shortcuts.",
                "offline",
                "pause",
                False,
            )
        elif state and state.paused:
            self._set_home_control(
                "Winsper is paused",
                "Dictation and Polish shortcuts are paused.",
                "paused",
                "resume",
                True,
            )
        else:
            self._set_home_control(
                "Winsper is active",
                "Dictation and Polish shortcuts are available.",
                "active",
                "pause",
                True,
            )

        self.status.setText("Winsper status refreshed.")

    def _refresh_home_microphone(self) -> None:
        try:
            devices = list_audio_devices()
        except Exception:
            devices = []
        title, detail, tone = microphone_home_status(self.config.audio.input_device, devices)
        self._set_home_tile("microphone", title, detail, tone)

    def _refresh_home_speed(self) -> None:
        label = self._speed_profile_label()
        language = self.config.speech.language or "Auto / mixed"
        acceleration = "GPU" if self.config.speech.device == "cuda" else "CPU"
        detail = f"{language} · {acceleration} · processed locally"
        tone = "warn" if label == "Precise" and self.config.speech.device == "cpu" else "good"
        self._set_home_tile("speed", f"{language} · {label}", detail, tone)

    def _refresh_home_models(self) -> None:
        ramble = self.config.dictation.ramble_model or self.config.speech.model
        try:
            statuses = {item.preset.model: item for item in list_installed_models(include_sizes=False)}
        except Exception as exc:
            self._set_home_tile("models", "Check failed", str(exc), "warn")
            return
        status = statuses.get(ramble)
        detail = f"{ramble} on {self.config.speech.device}/{self.config.speech.compute_type}"
        if status is None:
            self._set_home_tile("models", "Custom model", detail, "neutral")
        elif status.installed:
            self._set_home_tile("models", "Ready", detail, "accent")
        else:
            self._set_home_tile("models", "Not downloaded", f"{detail}. First use may download model files.", "warn")

    def _refresh_home_rewrite(self) -> None:
        if not self.config.dictation.polish_enabled:
            self._set_home_tile("rewrite", "Off", "Polish is disabled. Dictate still works.", "neutral")
            return
        provider = self.config.rewrite.provider.lower()
        health = check_rewrite_backend_health(self.config.rewrite, timeout_seconds=0.35)
        if health.ready:
            detail = health.detail or f"{self.config.rewrite.model} is available."
            self._set_home_tile("rewrite", "Ready", detail, "accent")
        elif self.config.dictation.polish_fallback_to_ramble:
            self._set_home_tile("rewrite", "Fallback ready", "Polish AI is unavailable. Dictate still works.", "warn")
        else:
            label = "Needs Ollama" if provider == "ollama" else "Needs AI runtime"
            self._set_home_tile("rewrite", label, health.message or "Configure Polish AI.", "bad")

    def _refresh_home_context(self) -> None:
        try:
            context = AppContextDetector(self.config).detect()
        except Exception as exc:
            self._set_home_tile("context", "Check failed", str(exc), "warn")
            return
        if is_winsper_window(context.process_name, context.window_title):
            self._set_home_tile("context", context.app_label, "Switch to another app or browser tab to preview awareness.", "neutral")
            return
        label = context.app_label or "Unknown"
        detail = context.profile.label
        if context.site_style is not None:
            detail = f"{detail} | {context.site_style.label}"
        if context.browser_domain:
            detail = f"{detail} | {context.browser_domain}"
        tone = "good" if context.process_name or context.window_title else "neutral"
        self._set_home_tile("context", label, detail, tone)

    def _refresh_home_history(self) -> None:
        if not self.config.history.enabled:
            self._set_home_tile("history", "Off", "Local history is disabled.", "neutral")
            return
        try:
            event = HistoryStore.for_config(
                self.config_path,
                max_items=self.config.history.max_items,
                enabled=self.config.history.enabled,
                retention_days=self.config.history.retention_days,
            ).latest()
        except Exception:
            self._set_home_tile("history", "Unavailable", "Encrypted history could not be opened.", "warn")
            return
        if event is None:
            self._set_home_tile("history", "No activity yet", "Dictations and rewrites will appear here after use.", "neutral")
            return
        app = event.browser_label or event.browser_domain or friendly_process_label(event.process_name, event.window_title)
        created = event.created_at.replace("T", " ")[:16]
        self._set_home_tile("history", f"{event.mode.title()} · {event.word_count} words", f"{app} · {created}", "good")

    def _refresh_home_usage(self) -> None:
        summary = usage_summary(self.config_path)
        if summary.today_words <= 0:
            self._set_home_tile("usage", "No dictation yet", "Use Winsper once and this will show words and time saved.", "neutral")
            return
        detail = (
            f"{summary.today_actions} action(s) today | "
            f"{summary.total_words} total words | "
            f"{format_minutes(summary.total_minutes_saved)} total saved"
        )
        self._set_home_tile(
            "usage", f"{summary.today_words} words", f"About {format_minutes(summary.today_minutes_saved)} saved today. {detail}", "good"
        )

    def _listener_is_running(self) -> bool:
        guard = SingleInstanceGuard(self.config_path)
        try:
            acquired = guard.acquire()
        except Exception:
            return False
        finally:
            guard.release()
        return not acquired

    def _send_listener_command(self, command: str) -> None:
        if not self._listener_is_running():
            self.status.setText("Winsper is not running.")
            self._refresh_home_status()
            return
        try:
            request_control_command(self.config_path, command)
        except Exception as exc:
            self.status.setText(f"Could not {command} Winsper: {exc}")
            return
        if command == "pause":
            self._set_home_control(
                "Pausing Winsper",
                "Dictation and Polish shortcuts will be unavailable.",
                "paused",
                "pause",
                False,
            )
        elif command == "resume":
            self._set_home_control(
                "Resuming Winsper",
                "Restoring Dictation and Polish shortcuts.",
                "active",
                "resume",
                False,
            )
        self.status.setText(f"{command.title()} requested.")
        from PySide6.QtCore import QTimer

        QTimer.singleShot(450, self._refresh_home_status)

    def _toggle_listener_state(self) -> None:
        state = read_runtime_state(self.config_path, max_age_seconds=60)
        self._send_listener_command("resume" if state and state.paused else "pause")

    def _speed_profile_label(self) -> str:
        ramble = (self.config.dictation.ramble_model or self.config.speech.model).lower()
        if self.config.speech.device == "cuda":
            return "GPU Boost"
        if "parakeet" in ramble or "medium" in ramble or "large" in ramble:
            return "Precise"
        if ramble in {"tiny.en", "base.en"}:
            return "Instant"
        return "Balanced"

    def _home_hotkey_summary(self) -> str:
        parts = [f"Dictate {format_shortcut(self.config.hotkeys.dictate)}"]
        if self.config.dictation.polish_enabled:
            parts.append(f"Polish {format_shortcut(self.config.hotkeys.polish)}")
        if self.config.hotkeys.cancel:
            parts.append(f"Cancel {format_shortcut(self.config.hotkeys.cancel)}")
        return " · ".join(parts)

    def _set_home_summary(self, text: str, detail: str, tone: str) -> None:
        if self.home_summary is None or self.home_detail is None:
            return
        self.home_summary.setText(text)
        self.home_detail.setText(detail)
        self._set_tone(self.home_summary, tone)

    def _set_home_control(
        self,
        title: str,
        detail: str,
        tone: str,
        action: str,
        enabled: bool,
    ) -> None:
        if self.home_state_title is None or self.home_state_detail is None:
            return
        self.home_state_title.setText(title)
        self.home_state_detail.setText(detail)
        self.home_state_dot.setProperty("tone", tone)
        self.home_pause_button.setProperty("action", action)
        self.home_pause_button.setText("Resume" if action == "resume" else "Pause")
        self.home_pause_button.setEnabled(enabled)
        self._refresh_home_action_icon()
        for widget in (self.home_state_dot, self.home_pause_button):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def _refresh_home_action_icon(self) -> None:
        if self.home_pause_button is None:
            return
        from PySide6.QtCore import QSize
        from .settings_icons import settings_nav_icon

        action = str(self.home_pause_button.property("action") or "pause")
        color = self.palette.on_accent if action == "resume" else self.palette.text
        if not self.home_pause_button.isEnabled():
            color = self.palette.subtle
        self.home_pause_button.setIcon(settings_nav_icon("play" if action == "resume" else "pause", color, 16))
        self.home_pause_button.setIconSize(QSize(16, 16))

    def _set_home_tile(self, key: str, state: str, detail: str, tone: str) -> None:
        labels = self.home_fields.get(key)
        if labels is None:
            return
        state_label, detail_label = labels
        state_label.setText(state)
        detail_label.setText(detail)
        detail_label.setVisible(bool(detail))
        state_label.setToolTip(detail)
        self._set_tone(state_label, tone)

    def _set_tone(self, widget, tone: str) -> None:
        widget.setProperty("tone", tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
