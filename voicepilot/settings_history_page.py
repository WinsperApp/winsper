from __future__ import annotations

from pathlib import Path

from .history import HistoryStore, export_history_csv
from .history_ui_support import app_label, history_visible_count_text, mode_label
from .settings_dialogs import confirm_settings_action
from .settings_helpers import friendly_check_error


class SettingsHistoryPageMixin:
    def _build_transcripts_page(self):
        from datetime import datetime, timedelta

        from PySide6.QtCore import QSize, Qt, QTimer
        from PySide6.QtWidgets import (
            QApplication,
            QFrame,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QSizePolicy,
            QVBoxLayout,
            QWidget,
        )
        from .settings_icons import settings_nav_icon
        from .settings_widgets import create_settings_combo

        page, layout = self._page("History", "Search and reuse your recent dictations.")
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        search = QLineEdit()
        search.setObjectName("HistorySearch")
        search.setPlaceholderText("Search transcripts…")
        search.setAccessibleName("Search history")
        activity_filter = create_settings_combo(
            lambda: self.palette,
            accessible_name="Filter history",
        )
        activity_filter.addItem("All activity", "all")
        activity_filter.addItem("Dictation", "dictation")
        activity_filter.addItem("Polish", "polish")
        export_button = QPushButton("Export")
        export_button.setObjectName("HistoryExportButton")
        export_button.clicked.connect(self._export_history_data)
        clear_button = QPushButton("Clear all")
        clear_button.setObjectName("HistoryClearButton")
        privacy_badge = QFrame()
        privacy_badge.setObjectName("HistoryPrivacyBadge")
        privacy_layout = QHBoxLayout(privacy_badge)
        privacy_layout.setContentsMargins(9, 5, 10, 5)
        privacy_layout.setSpacing(6)
        privacy_icon = QLabel()
        privacy_icon.setObjectName("HistoryPrivacyIcon")
        privacy_icon.setPixmap(settings_nav_icon("privacy", self.palette.accent, 14).pixmap(14, 14))
        privacy_text = QLabel("Encrypted on this device")
        privacy_text.setObjectName("HistoryPrivacyText")
        privacy_layout.addWidget(privacy_icon)
        privacy_layout.addWidget(privacy_text)
        toolbar.addWidget(search, 1)
        toolbar.addWidget(activity_filter)
        layout.addLayout(toolbar)

        summary = QHBoxLayout()
        summary.setSpacing(10)
        count_label = QLabel("No transcripts")
        count_label.setObjectName("HistoryCount")
        summary.addWidget(count_label)
        summary.addWidget(privacy_badge)
        summary.addStretch(1)
        summary.addWidget(export_button)
        summary.addWidget(clear_button)
        layout.addLayout(summary)

        list_surface = QFrame()
        list_surface.setObjectName("HistoryListSurface")
        list_surface.setMinimumHeight(390)
        list_surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cards = QVBoxLayout(list_surface)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(0)
        layout.addWidget(list_surface, 1)

        store = HistoryStore.for_config(
            self.config_path,
            max_items=self.config.history.max_items,
            enabled=self.config.history.enabled,
            retention_days=self.config.history.retention_days,
        )
        page_size = 25
        state = {"events": [], "visible_count": page_size}

        def clear_cards() -> None:
            while cards.count():
                item = cards.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()

        def local_datetime(value: str) -> datetime | None:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
            except ValueError:
                return None

        def date_group(value: str) -> tuple[str, str]:
            parsed = local_datetime(value)
            if parsed is None:
                return ("earlier", "Earlier")
            today = datetime.now().astimezone().date()
            concise_date = parsed.strftime("%d %B").lstrip("0")
            if parsed.date() == today:
                return (parsed.date().isoformat(), f"Today  ·  {concise_date}")
            if parsed.date() == today - timedelta(days=1):
                return (parsed.date().isoformat(), f"Yesterday  ·  {concise_date}")
            label = parsed.strftime("%d %B %Y").lstrip("0")
            return (parsed.date().isoformat(), label)

        def display_time(value: str) -> str:
            parsed = local_datetime(value)
            if parsed is None:
                return value
            return parsed.strftime("%I:%M %p").lstrip("0")

        def activity_label(event) -> str:
            label = mode_label(event)
            if label in {"Dictate", "Entry"}:
                return "Dictation"
            if label in {"Polish Selection", "Rewrite"}:
                return "Polish"
            return label

        def history_meta(event) -> str:
            parts = [activity_label(event)]
            application = app_label(event)
            if application != "Unknown":
                parts.append(application)
            timestamp = display_time(event.created_at)
            if timestamp:
                parts.append(timestamp)
            return "  ·  ".join(parts)

        def compact_preview(value: str, limit: int = 260) -> str:
            preview = " ".join(value.split())
            return preview if len(preview) <= limit else f"{preview[: limit - 1].rstrip()}…"

        def add_empty_state(message: str, title: str, icon_name: str = "transcripts") -> None:
            wrapper = QWidget()
            wrapper.setObjectName("HistoryEmptyWrapper")
            wrapper_layout = QHBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 4, 0, 0)
            wrapper_layout.addStretch(1)
            panel = QFrame()
            panel.setObjectName("HistoryEmptyPanel")
            panel.setMaximumWidth(520)
            panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(28, 24, 28, 24)
            panel_layout.setSpacing(6)
            icon = QLabel()
            icon.setObjectName("HistoryEmptyIcon")
            icon.setAlignment(Qt.AlignCenter)
            icon.setFixedSize(40, 40)
            icon.setPixmap(settings_nav_icon(icon_name, self.palette.accent, 19).pixmap(QSize(19, 19)))
            heading = QLabel(title)
            heading.setObjectName("HistoryEmptyTitle")
            heading.setAlignment(Qt.AlignCenter)
            detail = QLabel(message)
            detail.setObjectName("HistoryEmptyDetail")
            detail.setAlignment(Qt.AlignCenter)
            detail.setWordWrap(True)
            panel_layout.addWidget(icon, 0, Qt.AlignHCenter)
            panel_layout.addWidget(heading)
            panel_layout.addWidget(detail)
            wrapper_layout.addWidget(panel, 1)
            wrapper_layout.addStretch(1)
            cards.addStretch(1)
            cards.addWidget(wrapper)
            cards.addStretch(1)

        def copy_to_clipboard(text: str) -> None:
            QApplication.clipboard().setText(text)
            self.status.setText("Copied to clipboard.")

        def delete_event(event) -> None:
            if not confirm_settings_action(
                self.window,
                self.palette,
                title="Delete transcript?",
                message="Delete this transcript from this device? This cannot be undone.",
                confirm_label="Delete",
            ):
                return
            if store.delete(event.id):
                self.status.setText("Transcript deleted.")
            else:
                self.status.setText("Transcript was already removed.")
            reload_history()

        def show_details(event) -> None:
            from .history_details import HistoryDetailsDialog

            latest = store.latest()
            dialog = HistoryDetailsDialog(
                self,
                event,
                is_latest=bool(latest and latest.id == event.id),
                on_saved=reload_history,
            )
            dialog.exec()

        def clear_history() -> None:
            if not confirm_settings_action(
                self.window,
                self.palette,
                title="Clear history?",
                message="Delete every locally stored transcript? This cannot be undone.",
                confirm_label="OK",
            ):
                return
            store.clear()
            self.status.setText("History cleared.")
            reload_history()

        def refresh() -> None:
            clear_cards()
            query = search.text().strip().casefold()
            events = state["events"]
            export_button.setEnabled(bool(events))
            clear_button.setEnabled(bool(events))
            activity = str(activity_filter.currentData() or "all")

            def matches_activity(event) -> bool:
                polish = event.mode in {"polish", "polish_selection", "prompt"} or event.mode.startswith("polish")
                if activity == "polish":
                    return polish
                if activity == "dictation":
                    return not polish
                return True

            matches = [
                event
                for event in events
                if matches_activity(event)
                and (not query or query in f"{event.output_text} {event.input_text} {event.profile_label}".casefold())
            ]
            visible_matches = matches[: state["visible_count"]]
            count_label.setText(
                history_visible_count_text(
                    len(visible_matches),
                    len(matches),
                    len(events),
                    self.config.history.max_items,
                )
            )
            if not matches:
                if not self.config.history.enabled:
                    message = "Transcript history is off. Enable it in Privacy to keep future dictations."
                elif (query or activity != "all") and events:
                    message = "No history matches your filters."
                else:
                    message = "No transcripts yet. Your next dictation will appear here."
                add_empty_state(
                    message,
                    "No matches" if (query or activity != "all") and events else "Your history starts here",
                    "privacy" if not self.config.history.enabled else "transcripts",
                )
                return
            grouped: list[tuple[str, list]] = []
            group_keys: dict[str, int] = {}
            for event in visible_matches:
                key, label = date_group(event.created_at)
                if key not in group_keys:
                    group_keys[key] = len(grouped)
                    grouped.append((label, []))
                grouped[group_keys[key]][1].append(event)

            for group_label, group_events in grouped:
                date_header = QFrame()
                date_header.setObjectName("HistoryDateHeader")
                date_header_layout = QHBoxLayout(date_header)
                date_header_layout.setContentsMargins(18, 15, 18, 8)
                date_header_layout.setSpacing(12)
                date_label = QLabel(group_label)
                date_label.setObjectName("HistoryDateLabel")
                date_header_layout.addWidget(date_label)
                date_divider = QFrame()
                date_divider.setObjectName("HistoryDateDivider")
                date_divider.setFixedHeight(1)
                date_divider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                date_header_layout.addWidget(date_divider, 1, Qt.AlignVCenter)
                cards.addWidget(date_header)
                group = QFrame()
                group.setObjectName("HistoryGroup")
                group_layout = QVBoxLayout(group)
                group_layout.setContentsMargins(0, 0, 0, 0)
                group_layout.setSpacing(0)
                for index, event in enumerate(group_events):
                    text = event.output_text or event.input_text
                    row_frame = QFrame()
                    row_frame.setObjectName("HistoryRow")
                    row_frame.setProperty("last", index == len(group_events) - 1)
                    row = QHBoxLayout(row_frame)
                    row.setContentsMargins(18, 14, 12, 14)
                    row.setSpacing(12)
                    copy = QVBoxLayout()
                    copy.setSpacing(5)
                    transcript = QLabel(compact_preview(text))
                    transcript.setObjectName("HistoryTranscript")
                    transcript.setWordWrap(True)
                    transcript.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
                    transcript.setToolTip(text if len(text) > 260 else "")
                    meta = QLabel(history_meta(event))
                    meta.setObjectName("HistoryMeta")
                    copy.addWidget(transcript)
                    copy.addWidget(meta)
                    row.addLayout(copy, 1)
                    details_button = QPushButton()
                    details_button.setObjectName("HistoryDetailsButton")
                    details_button.setAccessibleName("Open transcript details")
                    details_button.setToolTip("Open details")
                    details_button.setIcon(settings_nav_icon("edit", self.palette.muted, 16))
                    details_button.setIconSize(QSize(16, 16))
                    details_button.setFixedSize(36, 36)
                    details_button.clicked.connect(
                        lambda _checked=False, value=event: show_details(value)
                    )
                    row.addWidget(details_button, 0, Qt.AlignVCenter)
                    copy_button = QPushButton()
                    copy_button.setObjectName("HistoryCopyButton")
                    copy_button.setAccessibleName("Copy transcript")
                    copy_button.setToolTip("Copy transcript")
                    copy_button.setIcon(settings_nav_icon("copy", self.palette.muted, 16))
                    copy_button.setIconSize(QSize(16, 16))
                    copy_button.setFixedSize(36, 36)
                    copy_button.clicked.connect(
                        lambda _checked=False, value=text: copy_to_clipboard(value)
                    )
                    row.addWidget(copy_button, 0, Qt.AlignVCenter)
                    delete_button = QPushButton()
                    delete_button.setObjectName("HistoryDeleteButton")
                    delete_button.setAccessibleName("Delete transcript")
                    delete_button.setToolTip("Delete transcript")
                    delete_button.setIcon(settings_nav_icon("trash", self.palette.muted, 16))
                    delete_button.setIconSize(QSize(16, 16))
                    delete_button.setFixedSize(36, 36)
                    delete_button.clicked.connect(
                        lambda _checked=False, value=event: delete_event(value)
                    )
                    row.addWidget(delete_button, 0, Qt.AlignVCenter)
                    group_layout.addWidget(row_frame)
                cards.addWidget(group)
            if len(visible_matches) < len(matches):
                load_more = QPushButton(
                    f"Show older transcripts ({len(matches) - len(visible_matches)} remaining)"
                )
                load_more.setObjectName("HistoryLoadMoreButton")
                load_more.setAccessibleName("Show older transcripts")
                load_more.setCursor(Qt.PointingHandCursor)
                load_more.clicked.connect(show_more)
                cards.addWidget(load_more, 0, Qt.AlignHCenter)
            cards.addStretch(1)

        def reload_history() -> None:
            state["visible_count"] = page_size
            try:
                state["events"] = store.list()
            except Exception as exc:
                state["events"] = []
                clear_cards()
                add_empty_state(
                    f"History could not be loaded. {friendly_check_error(exc)}",
                    "History unavailable",
                    "warning",
                )
                export_button.setEnabled(False)
                clear_button.setEnabled(False)
                count_label.setText("Unavailable")
                return
            refresh()

        def show_more() -> None:
            state["visible_count"] += page_size
            refresh()

        def reset_and_refresh() -> None:
            state["visible_count"] = page_size
            refresh()

        search_timer = QTimer(page)
        search_timer.setSingleShot(True)
        search_timer.setInterval(150)
        search.textChanged.connect(lambda _text: search_timer.start())
        search_timer.timeout.connect(reset_and_refresh)
        activity_filter.currentIndexChanged.connect(reset_and_refresh)
        clear_button.clicked.connect(clear_history)
        self._refresh_history_page = reload_history
        reload_history()
        return page

    def _open_history_window(self) -> None:
        self._show_named_page("History")
        refresh_history = getattr(self, "_refresh_history_page", None)
        if callable(refresh_history):
            refresh_history()
        self.status.setText("Opened History.")

    def _clear_history_data(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        if QMessageBox.question(self.window, "Winsper", "Clear local history?") != QMessageBox.Yes:
            return

        HistoryStore.for_config(self.config_path).clear()
        self.status.setText("History cleared.")

    def _export_history_data(self) -> None:
        from datetime import datetime

        from PySide6.QtWidgets import QFileDialog, QMessageBox

        store = HistoryStore.for_config(
            self.config_path,
            max_items=self.config.history.max_items,
            enabled=self.config.history.enabled,
            retention_days=self.config.history.retention_days,
        )
        events = store.list()
        if not events:
            self.status.setText("There is no history to export.")
            return
        suggested = Path.home() / "Downloads" / f"Winsper-history-{datetime.now():%Y-%m-%d}.csv"
        destination, _selected_filter = QFileDialog.getSaveFileName(
            self.window,
            "Export Winsper history",
            str(suggested),
            "CSV files (*.csv)",
        )
        if not destination:
            return
        path = Path(destination)
        if path.suffix.casefold() != ".csv":
            path = path.with_suffix(".csv")
        try:
            export_history_csv(events, path)
        except OSError as exc:
            QMessageBox.warning(self.window, "Export failed", f"Winsper could not save the file.\n\n{exc}")
            return
        self.status.setText(f"Exported {len(events)} transcript{'s' if len(events) != 1 else ''}.")
