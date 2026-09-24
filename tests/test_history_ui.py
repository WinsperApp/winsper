import os
import tempfile
from pathlib import Path

from voicepilot.config import AppConfig, save_config
from voicepilot.control import consume_control_command
from voicepilot.corrections import CorrectionStore
from voicepilot.history import HistoryEvent, HistoryStore


def _event(**overrides) -> HistoryEvent:
    values = {
        "id": "event-1",
        "created_at": "2026-07-05T12:00:00+00:00",
        "mode": "ramble",
        "input_text": "hello world",
        "output_text": "Hello world.",
        "profile_name": "general",
        "profile_label": "General",
        "process_name": "notepad.exe",
        "window_title": "Notes",
        "speech_model": "small.en",
        "word_count": 2,
    }
    values.update(overrides)
    return HistoryEvent(**values)


def _settings(path: Path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    window = SettingsWindow(path, initial_page="History")
    window.show()
    app.processEvents()
    return app, window


def test_integrated_history_is_the_single_searchable_history_surface():
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        HistoryStore.for_config(path).append(_event())

        app, window = _settings(path)
        assert window.page_names[window.stack.currentIndex()] == "History"
        assert len(window.window.findChildren(QFrame, "HistoryRow")) == 1
        assert len(window.window.findChildren(QPushButton, "HistoryDetailsButton")) == 1

        search = window.window.findChild(QLineEdit, "HistorySearch")
        assert search is not None
        search.setText("missing")
        QTest.qWait(180)
        app.processEvents()
        detail = window.window.findChild(QLabel, "HistoryEmptyDetail")
        assert detail is not None
        assert "matches your filters" in detail.text()
        window.close()
        app.processEvents()


def test_history_progressively_reveals_older_transcripts():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QFrame, QLabel, QPushButton

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        store = HistoryStore.for_config(path)
        for index in range(30):
            store.append(
                _event(
                    id=f"event-{index}",
                    created_at=f"2026-07-{index + 1:02d}T12:00:00+00:00",
                    output_text=f"Transcript {index}",
                )
            )

        app, window = _settings(path)
        assert len(window.window.findChildren(QFrame, "HistoryRow")) == 25

        load_more = window.window.findChild(QPushButton, "HistoryLoadMoreButton")
        assert load_more is not None
        assert load_more.text() == "Show older transcripts (5 remaining)"
        load_more.click()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()

        assert len(window.window.findChildren(QFrame, "HistoryRow")) == 30
        assert window.window.findChild(QPushButton, "HistoryLoadMoreButton") is None
        count = window.window.findChild(QLabel, "HistoryCount")
        assert count is not None
        assert count.text() == "30 transcripts"
        window.close()
        app.processEvents()


def test_settings_history_action_navigates_without_opening_another_window():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        app, window = _settings(path)
        window._show_named_page("General")

        window._open_history_window()

        assert window.page_names[window.stack.currentIndex()] == "History"
        window.close()
        app.processEvents()


def test_history_details_preserve_original_metadata_and_editing():
    from PySide6.QtCore import Qt
    from voicepilot.history_details import HistoryDetailsDialog

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        event = _event(
            input_text="hello world",
            output_text="Hello world.",
            speech_device="cpu",
            speech_compute_type="int8",
            transcription_ms=350,
        )
        HistoryStore.for_config(path).append(event)
        app, window = _settings(path)

        details = HistoryDetailsDialog(window, event, is_latest=True, on_saved=lambda: None)
        assert details.original is not None
        assert details.original.toPlainText() == "hello world"
        assert "Notepad" in details._summary()
        assert "small.en" in details._technical_details()
        assert details.technical_details.isHidden()
        details.details_toggle.setChecked(True)
        app.processEvents()
        assert not details.technical_details.isHidden()
        assert details.undo_button is not None
        assert details.save_button.objectName() == "PrimaryButton"
        assert details.save_button.minimumWidth() == 132
        assert not details.save_button.isEnabled()
        assert details.output.cursor().shape() == Qt.IBeamCursor
        assert details.output.viewport().cursor().shape() == Qt.IBeamCursor
        details.output.setPlainText("Hello, world.")
        app.processEvents()
        assert details.save_button.isEnabled()
        details.dialog.close()
        window.close()
        app.processEvents()


def test_history_details_restore_neutral_cursor_after_return():
    from PySide6.QtCore import QEvent, QTimer, Qt
    from PySide6.QtWidgets import QLabel
    from voicepilot.history_details import HistoryDetailsDialog

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        event = _event()
        HistoryStore.for_config(path).append(event)
        app, window = _settings(path)
        details = HistoryDetailsDialog(window, event, is_latest=True, on_saved=lambda: None)

        forced: list[tuple[object, object]] = []
        original_set_cursor = window._button_cursor_policy._set_cursor

        def record_set_cursor(widget, cursor, *, force=False):
            if force:
                forced.append((widget, cursor))
            original_set_cursor(widget, cursor, force=force)

        window._button_cursor_policy._set_cursor = record_set_cursor

        # QWidget can already report ArrowCursor while Windows still displays
        # the hand from the modal button. Recovery must force a native refresh,
        # not skip the write because the logical enum appears correct.
        neutral_surface = QLabel("Neutral", window.window)
        window.window.setCursor(Qt.ArrowCursor)
        neutral_surface.setCursor(Qt.ArrowCursor)
        QTimer.singleShot(0, details.dialog.reject)
        details.exec()

        assert window.window.cursor().shape() == Qt.ArrowCursor
        assert neutral_surface.cursor().shape() == Qt.ArrowCursor
        assert (window.window, Qt.ArrowCursor) in forced

        forced.clear()
        app.sendEvent(neutral_surface, QEvent(QEvent.Enter))
        assert (neutral_surface, Qt.ArrowCursor) in forced
        window.close()
        app.processEvents()


def test_nested_history_confirmation_restores_cursor_before_editor_closes(monkeypatch):
    from PySide6.QtCore import Qt
    from voicepilot.history_details import HistoryDetailsDialog

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.correction_memory.enabled = True
        save_config(config, path)
        event = _event()
        HistoryStore.for_config(path).append(event)
        app, window = _settings(path)
        details = HistoryDetailsDialog(window, event, is_latest=True, on_saved=lambda: None)

        forced: list[tuple[object, object]] = []
        original_set_cursor = window._button_cursor_policy._set_cursor

        def record_set_cursor(widget, cursor, *, force=False):
            if force:
                forced.append((widget, cursor))
            original_set_cursor(widget, cursor, force=force)

        window._button_cursor_policy._set_cursor = record_set_cursor
        monkeypatch.setattr(
            "voicepilot.history_details.infer_correction_candidate",
            lambda _before, _after: ("world", "there"),
        )
        monkeypatch.setattr(
            "voicepilot.settings_dialogs._create_settings_confirmation_dialog",
            lambda parent, palette, **kwargs: _auto_reject_confirmation(parent),
        )

        details.dialog.show()
        app.processEvents()
        details.output.setPlainText("Hello there.")
        details._save_output_edit()
        app.processEvents()

        # Inner confirmation returned, but editor is still open. Cursor must
        # already be repaired; waiting for outer editor close is too late.
        assert details.dialog.isVisible()
        assert (window.window, Qt.ArrowCursor) in forced
        details.dialog.close()
        window.close()
        app.processEvents()


def _auto_reject_confirmation(parent):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog

    dialog = QDialog(parent)
    QTimer.singleShot(0, dialog.reject)
    return dialog


def test_history_repaste_uses_truthful_insert_result(monkeypatch):
    from voicepilot.history_details import HistoryDetailsDialog
    from voicepilot.paste import InsertResult

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        event = _event()
        HistoryStore.for_config(path).append(event)
        app, window = _settings(path)
        details = HistoryDetailsDialog(window, event, is_latest=True, on_saved=lambda: None)
        messages: list[str] = []
        details._set_status = messages.append
        monkeypatch.setattr(
            details.inserter,
            "paste_text",
            lambda _text: InsertResult(True, False, "clipboard"),
        )
        monkeypatch.setattr(
            "PySide6.QtCore.QTimer.singleShot",
            lambda _delay, callback: callback(),
        )

        details._repaste()

        assert messages == ["Sent transcript again."]
        window.close()
        app.processEvents()


def test_history_edit_can_learn_correction_and_reload_running_app(monkeypatch):
    from voicepilot.history_details import HistoryDetailsDialog

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        event = _event(
            input_text="Send this to Samya.",
            output_text="Send this to Samya.",
            word_count=4,
        )
        HistoryStore.for_config(path).append(event)
        app, window = _settings(path)
        monkeypatch.setattr(
            "voicepilot.settings_dialogs.confirm_settings_action",
            lambda *args, **kwargs: True,
        )

        details = HistoryDetailsDialog(window, event, is_latest=True, on_saved=lambda: None)
        details.output.setPlainText("Send this to Avery.")
        details._save_output_edit()

        assert HistoryStore.for_config(path).latest().output_text == "Send this to Avery."
        assert CorrectionStore.for_config(path).apply("Send this to Samya.") == "Send this to Avery."
        assert CorrectionStore.for_config(path).list()[-1].profiles == []
        assert consume_control_command(path) == "reload_silent"
        details.dialog.close()
        window.close()
        app.processEvents()


def test_manual_correction_dialog_has_no_profile_scope(monkeypatch):
    from PySide6.QtWidgets import QDialog, QLabel
    from voicepilot.history_details import HistoryDetailsDialog

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        event = _event(profile_name="code", profile_label="Code-aware")
        HistoryStore.for_config(path).append(event)
        app, window = _settings(path)
        details = HistoryDetailsDialog(window, event, is_latest=True, on_saved=lambda: None)
        labels: list[str] = []

        def reject_after_inspection(dialog):
            labels.extend(label.text() for label in dialog.findChildren(QLabel))
            return QDialog.Rejected

        monkeypatch.setattr(QDialog, "exec", reject_after_inspection)
        details._learn_correction()

        assert "Heard" in labels
        assert "Replace with" in labels
        assert "Profile" not in labels
        details.dialog.close()
        window.close()
        app.processEvents()


def test_history_correction_candidate_stays_small_and_specific():
    from voicepilot.history_ui_support import infer_correction_candidate

    assert infer_correction_candidate("Send this to Samya.", "Send this to Avery.") == ("Samya", "Avery")
    assert infer_correction_candidate("No change.", "No change.") is None
    assert infer_correction_candidate("One two three", "Uno two tres") is None


def test_history_empty_state_explains_disabled_storage():
    from PySide6.QtWidgets import QLabel

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.history.enabled = False
        save_config(config, path)

        app, window = _settings(path)
        detail = window.window.findChild(QLabel, "HistoryEmptyDetail")
        assert detail is not None
        assert "history is off" in detail.text()
        window.close()
        app.processEvents()
