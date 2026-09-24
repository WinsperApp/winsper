import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from voicepilot.config import AppConfig, load_config, save_config
from voicepilot.theme import DARK, LIGHT


def test_general_page_status_control_and_theme_persist():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from voicepilot.runtime_state import RuntimeState
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with patch.object(SettingsWindow, "_refresh_home_status"):
            window = SettingsWindow(path)

        paused = RuntimeState("paused", "", True, 1, "2026-01-01T00:00:00+00:00")
        with (
            patch.object(window, "_listener_is_running", return_value=True),
            patch("voicepilot.settings_home.read_runtime_state", return_value=paused),
        ):
            window._refresh_home_status()
        assert window.home_state_title.text() == "Winsper is paused"
        assert window.home_pause_button.text() == "Resume"
        assert window.home_pause_button.property("action") == "resume"

        appearance = window.widgets["hud.theme"]
        appearance.setCurrentIndex(appearance.findData("dark"))
        with (
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window._save(silent=True)
        assert load_config(path).hud.theme == "dark"
        window.close()
    app.processEvents()


def test_main_polish_page_uses_shared_official_app_marks(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QFrame, QLabel
    from voicepilot.app_icons import app_icon_path
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    with patch.object(SettingsWindow, "_refresh_home_status"):
        window = SettingsWindow(path)
    window._show_named_page("Polish")
    page = window.stack.currentWidget()

    assert page.findChild(QFrame, "PolishAppAwareness") is not None
    marks = page.findChildren(QLabel, "PolishAppMark")
    assert [mark.accessibleName() for mark in marks] == [
        "Outlook",
        "Slack",
        "ChatGPT",
        "VS Code",
        "Windows Terminal",
    ]
    assert all(not mark.pixmap().isNull() for mark in marks)
    assert all(app_icon_path(app_id) is not None for app_id in ("outlook", "slack", "chatgpt", "vscode", "terminal"))

    window.close()
    app.processEvents()


def test_launch_at_login_reflects_existing_windows_registration(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    with (
        patch.object(SettingsWindow, "_refresh_home_status"),
        patch("voicepilot.settings_home.is_start_with_windows_enabled", return_value=True),
    ):
        window = SettingsWindow(path)

    assert window.widgets["startup.start_with_windows"].isChecked()
    window.close()
    app.processEvents()


def test_personalize_has_one_clear_owner_for_each_tool():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QTabWidget
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        window.show()
        window._show_named_page("Personalize")
        app.processEvents()

        page = window.stack.currentWidget()
        tabs = page.findChild(QTabWidget, "PersonalizeTabs")
        all_text = " ".join(label.text() for label in page.findChildren(QLabel))

        assert tabs is not None
        assert [tabs.tabText(index).replace("&&", "&") for index in range(tabs.count())] == [
            "Words & corrections",
            "Text shortcuts",
        ]
        separators = page.findChildren(QFrame, "PersonalizeTabSeparator")
        assert len(separators) == 2
        for separator in separators:
            bar = separator.parentWidget()
            first = bar.tabRect(0)
            assert separator.size().width() == 1
            assert separator.size().height() == 18
            assert separator.x() == first.right() - 12
            assert separator.y() == max(0, (bar.height() - separator.height()) // 2)
            assert separator.testAttribute(Qt.WA_TransparentForMouseEvents)
            assert not separator.focusPolicy() & Qt.TabFocus
            assert separator.isVisible()
        assert "Writing voice" not in all_text
        assert "Spoken formatting" not in all_text
        assert "Voice actions" not in all_text
        assert "App formatting" not in all_text
        assert "Keyboard shortcuts" not in all_text
        window.close()
    app.processEvents()


def test_personalize_ships_only_generic_removable_starter_content():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QLineEdit, QTextEdit
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        window._show_named_page("Personalize")
        page = window.stack.currentWidget()
        placeholders = {field.placeholderText() for field in [*page.findChildren(QLineEdit), *page.findChildren(QTextEdit)]}
        labels = {label.text() for label in page.findChildren(QLabel)}

        assert "Add a name or term, e.g. Winsper" in placeholders
        assert "e.g. Win spur" in placeholders
        assert "e.g. Winsper" in placeholders
        assert "Name, e.g. Support reply" in placeholders
        assert "Voice trigger, e.g. insert support reply" in placeholders
        assert {"Winsper", "win spur  →  Winsper"} <= labels
        assert "Active" not in labels
        assert all(button.text() != "Active" for button in page.findChildren(QAbstractButton))
        assert window.config.vocabulary == ["Winsper"]
        assert [(rule.heard, rule.replacement) for rule in window.corrections] == [("win spur", "Winsper")]
        assert [snippet.trigger for snippet in window.snippets] == [
            "today's date",
            "current time",
            "date and time",
        ]
        window.close()
    app.processEvents()


def test_personalize_keeps_owned_tools_and_about_omits_support_utilities():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QFrame, QPushButton, QTabWidget
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)

        window._show_named_page("Personalize")
        personalize = window.stack.currentWidget()
        tabs = personalize.findChild(QTabWidget, "PersonalizeTabs")
        assert tabs is not None
        assert tabs.count() == 2
        assert personalize.findChildren(QFrame, "PersonalizeComposer")

        window._show_named_page("About")
        about = window.stack.currentWidget()
        assert about.findChild(QFrame, "AboutTools") is None
        button_text = {button.text() for button in about.findChildren(QPushButton)}
        assert {
            "Run setup again",
            "Copy diagnostics",
            "Open data folder",
        }.isdisjoint(button_text)

        window.close()
    app.processEvents()


def test_toggle_respects_reduced_motion():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import ToggleSwitch

    app = QApplication.instance() or QApplication([])
    with patch("voicepilot.settings_qt.motion_enabled", return_value=False):
        toggle = ToggleSwitch.create(False)
    toggle.show()
    QTest.mouseClick(toggle, Qt.LeftButton)
    assert toggle.isChecked()
    assert toggle._thumb_progress == 1.0
    assert not toggle._anim_timer.isActive()
    toggle.close()
    app.processEvents()


def test_history_retention_uses_human_labels_and_persists_days():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with patch.object(SettingsWindow, "_refresh_home_status"):
            window = SettingsWindow(path)
        window._ensure_page_loaded(window.page_names.index("Privacy"))
        retention = window.widgets["history.retention_days"]
        assert retention.currentText() == "Forever"

        retention.setCurrentText("90 days")
        window._save(silent=True)

        assert load_config(path).history.retention_days == 90
        window.close()
    app.processEvents()


def test_privacy_page_is_quiet_truthful_and_disables_retention_with_history():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with patch.object(SettingsWindow, "_refresh_home_status"):
            window = SettingsWindow(path)
        privacy_index = window.page_names.index("Privacy")
        window._ensure_page_loaded(privacy_index)
        page = window.stack.widget(privacy_index)

        assert page.findChild(QFrame, "PrivacyTrustPanel") is not None
        page_text = " ".join(label.text() for label in page.findChildren(QLabel))
        assert "Private by design" in page_text
        assert "No tracking or automatic diagnostic uploads." not in page_text
        assert "model downloads, license verification, and update checks" not in page_text

        button_text = {button.text() for button in page.findChildren(QPushButton)}
        assert button_text.isdisjoint(
            {
                "Open Data Folder",
                "Export History",
                "Export Privacy Report",
                "Clear History",
                "Clear Corrections",
                "Clear Performance Data",
            }
        )

        history_toggle = window.widgets["history.enabled"]
        retention = window.widgets["history.retention_days"]
        assert retention.isEnabled()
        history_toggle.setChecked(False)
        app.processEvents()
        assert not retention.isEnabled()
        history_toggle.setChecked(True)
        app.processEvents()
        assert retention.isEnabled()
        window.close()
    app.processEvents()


def test_polish_page_keeps_blue_for_recommendations_not_helper_copy(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    with patch.object(SettingsWindow, "_refresh_home_status"):
        window = SettingsWindow(path)
    window._show_named_page("Polish")
    page = window.stack.currentWidget()
    labels = {label.text() for label in page.findChildren(QLabel)}

    assert "Winsper chooses automatically" not in labels
    assert "Fast local cleanup for lower-memory PCs" not in labels
    assert "Largest local model · Slower and task-dependent" not in labels
    quality_summary = page.findChild(QLabel, "QualitySummary")
    assert quality_summary is not None
    assert quality_summary.text() == ("Recommended — strong everyday Polish without the longest wait. - Qwen 3 4B")
    assert quality_summary.property("recommended") is False
    advanced = page.findChild(QPushButton, "QualityAdvancedButton")
    assert advanced is not None
    assert advanced.text() == "Advanced"

    window.close()
    app.processEvents()


def test_fast_polish_quality_has_no_blue_helper_line(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QLabel
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "config.yaml"
    config = AppConfig()
    config.rewrite.provider = "embedded"
    config.rewrite.llama_model_id = "qwen2.5-1.5b-q4km"
    save_config(config, path)
    with patch.object(SettingsWindow, "_refresh_home_status"):
        window = SettingsWindow(path)
    window._show_named_page("Polish")
    quality_summary = window.stack.currentWidget().findChild(QLabel, "QualitySummary")

    assert quality_summary is not None
    assert quality_summary.text() == ("Fastest response with a lighter local model. - Qwen 2.5 1.5B")
    assert quality_summary.property("recommended") is False
    assert not quality_summary.isHidden()

    window.close()
    app.processEvents()


def test_dictation_and_polish_advanced_buttons_share_the_same_card_position(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)
    with patch.object(SettingsWindow, "_refresh_home_status"):
        window = SettingsWindow(path)
    window.show()

    placements = []
    for page_name in ("Dictation", "Polish"):
        window._show_named_page(page_name)
        app.processEvents()
        page = window.stack.currentWidget()
        advanced = page.findChild(QPushButton, "QualityAdvancedButton")
        assert advanced is not None
        panel = advanced.parentWidget()
        origin = advanced.mapTo(panel, QPoint(0, 0))
        right_gap = panel.contentsRect().right() - (origin.x() + advanced.width() - 1)
        placements.append((origin.y(), right_gap))

    assert placements[0] == placements[1]
    assert placements[0][1] == 20

    window.close()
    app.processEvents()


def test_about_page_keeps_only_product_update_support_and_legal_actions():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with patch.object(SettingsWindow, "_refresh_home_status"):
            window = SettingsWindow(path)
        window._show_named_page("About")
        page = window.stack.currentWidget()

        assert page.findChild(QFrame, "AboutIdentity") is not None
        assert page.findChild(QFrame, "AboutCombinedCard") is None
        assert page.findChild(QFrame, "AboutHeader") is not None
        assert page.findChild(QFrame, "AboutUpdate") is None
        assert page.findChild(QFrame, "AboutSupportHub") is not None
        assert page.findChild(QLabel, "AboutPlanBadge") is None
        assert page.findChild(QLabel, "LocalBadge") is None
        labels = {label.text() for label in page.findChildren(QLabel)}
        buttons = {button.text() for button in page.findChildren(QPushButton)}
        primary_buttons = {button.text() for button in page.findChildren(QPushButton, "PrimaryButton")}
        assert all("Early Access" not in label for label in labels)
        assert "Need help with Winsper?" in labels
        assert "Support by email" not in labels
        assert all("✓" not in label for label in labels)
        assert {"Check for updates", "Get help", "Privacy", "Terms"} <= buttons
        assert {"Check for updates", "Get help"} <= primary_buttons
        assert all("24/7" not in label for label in labels)
        assert {
            "Send feedback",
            "Website",
            "Run setup again",
            "Copy diagnostics",
            "Open data folder",
        }.isdisjoint(buttons)
        window.close()
    app.processEvents()


def test_local_badges_are_consistent_on_processing_surfaces():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QLabel
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with (
            patch.object(SettingsWindow, "_refresh_home_status"),
            patch("voicepilot.settings_dictation_page.list_audio_devices", return_value=[]),
        ):
            window = SettingsWindow(path)
            for page_name in ("Dictation", "Polish"):
                window._show_named_page(page_name)
                badge = window.stack.currentWidget().findChild(QLabel, "LocalBadge")
                assert badge is not None
                assert badge.text() == "Local"
                assert badge.toolTip()
            window.close()
    app.processEvents()


def test_home_stats_respect_reduced_motion_and_consumer_navigation():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QFrame, QLabel
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        summary = SimpleNamespace(today_words=875, today_minutes_saved=12.0, today_actions=31)
        with (
            patch("voicepilot.usage.usage_summary", return_value=summary),
            patch("voicepilot.settings_home.motion_enabled", return_value=False),
            patch.object(SettingsWindow, "_refresh_home_status"),
        ):
            window = SettingsWindow(path)
        assert window._stat_words.text() == "875"
        assert window._stat_time.text() == "12 min"
        assert window._stat_sessions.text() == "31"
        assert [button.text().replace("&&", "&") for button in window.nav_buttons.values()] == [
            "General",
            "Dictation",
            "Polish",
            "Personalize",
            "History",
            "Privacy",
            "About",
        ]
        assert window.window.findChild(QFrame, "NavDivider") is None
        home_copy = {label.text() for label in window.stack.currentWidget().findChildren(QLabel)}
        assert "Smart silence detection" not in home_copy
        assert "Words spoken" in home_copy
        window.close()
    app.processEvents()


def test_history_page_is_quiet_and_uses_honest_privacy_copy():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLabel, QPushButton
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        with patch.object(SettingsWindow, "_refresh_home_status"):
            window = SettingsWindow(path)
        window._show_named_page("History")
        page = window.stack.currentWidget()

        button_texts = {button.text() for button in page.findChildren(QPushButton)}
        label_texts = {label.text() for label in page.findChildren(QLabel)}
        privacy_badge = page.findChild(QFrame, "HistoryPrivacyBadge")
        activity_filter = next(combo for combo in page.findChildren(QComboBox) if combo.accessibleName() == "Filter history")

        assert "Refresh" not in button_texts
        assert "On-device" not in label_texts
        assert "Encrypted on this device" in label_texts
        assert "Clear all" in button_texts
        assert not any("actions" in text.casefold() for text in label_texts)
        assert privacy_badge is not None
        assert privacy_badge.toolTip() == ""
        assert [activity_filter.itemData(index) for index in range(activity_filter.count())] == [
            "all",
            "dictation",
            "polish",
        ]
        window.close()
    app.processEvents()


def test_history_page_groups_entries_and_supports_copy_and_delete(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from datetime import datetime, timezone

    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton
    from voicepilot.history import HistoryEvent, HistoryStore
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        save_config(config, path)
        text = "Please send the launch update before Friday."
        HistoryStore.for_config(
            path,
            max_items=config.history.max_items,
            enabled=True,
            retention_days=config.history.retention_days,
        ).append(
            HistoryEvent(
                id="history-ui",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                mode="ramble",
                input_text=text,
                output_text=text,
                profile_name="general",
                profile_label="General",
                process_name="olk.exe",
                window_title="Outlook",
                speech_model="small.en",
            )
        )
        with patch.object(SettingsWindow, "_refresh_home_status"):
            window = SettingsWindow(path)
        window._show_named_page("History")
        page = window.stack.currentWidget()

        assert page.findChild(QFrame, "HistoryListSurface") is not None
        assert page.findChild(QFrame, "HistoryDateHeader") is not None
        assert page.findChild(QFrame, "HistoryDateDivider") is not None
        assert page.findChild(QFrame, "HistoryGroup") is not None
        assert page.findChild(QFrame, "HistoryRow") is not None
        assert page.findChild(QLabel, "HistoryDateLabel").text().startswith("Today")
        assert page.findChild(QLabel, "HistoryTranscript").text() == text
        metadata = page.findChild(QLabel, "HistoryMeta").text()
        assert "Dictation" in metadata
        assert "Outlook" in metadata
        assert "olk.exe" not in metadata
        confirmation = {}
        monkeypatch.setattr(
            "voicepilot.settings_history_page.confirm_settings_action",
            lambda *args, **kwargs: confirmation.update(kwargs) or False,
        )
        page.findChild(QPushButton, "HistoryClearButton").click()
        assert confirmation["confirm_label"] == "OK"
        copy_button = page.findChild(QPushButton, "HistoryCopyButton")
        assert copy_button.accessibleName() == "Copy transcript"
        copy_button.click()
        assert QApplication.clipboard().text() == text
        delete_button = page.findChild(QPushButton, "HistoryDeleteButton")
        assert delete_button.accessibleName() == "Delete transcript"
        monkeypatch.setattr(
            "voicepilot.settings_history_page.confirm_settings_action",
            lambda *args, **kwargs: True,
        )
        delete_button.click()
        app.processEvents()
        assert HistoryStore.for_config(path).list() == []
        assert window.status.text() == "Transcript deleted."
        window.close()
    app.processEvents()


def test_page_transition_survives_rapid_navigation():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        window.show()
        for page in ("Dictation", "Polish", "Personalize", "History", "Privacy", "About"):
            window._show_named_page(page)
        assert window.page_names[window.stack.currentIndex()] == "About"
        assert window.stack.currentWidget().graphicsEffect() is None
        assert window.stack.currentWidget().isVisible()
        window.close()
    app.processEvents()


def test_home_quick_settings_survive_lazy_page_creation():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QScrollArea, QTableWidget, QTextEdit
    from voicepilot.settings_qt import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        save_config(AppConfig(), path)
        window = SettingsWindow(path)
        assert all(label.text() != "Ready to dictate" for label in window.window.findChildren(QLabel))
        window._show_named_page("Polish")
        window.widgets["dictation.polish_enabled"].setChecked(False)
        window.widgets["paste.restore_clipboard"].setChecked(False)

        with (
            patch("voicepilot.settings_persistence.set_start_with_windows"),
            patch("voicepilot.settings_persistence.request_control_command"),
        ):
            window._save(silent=True)

        saved = load_config(path)
        assert saved.dictation.polish_enabled is False
        assert saved.paste.restore_clipboard is False
        assert window.widget_registry.canonical("dictation.polish_enabled").isChecked() is False
        assert len(window.nav_buttons) == 7
        assert all(not button.icon().isNull() for button in window.nav_buttons.values())
        window._show_named_page("Controls")
        recorder = window.widgets["hotkeys.dictate"]
        QTest.mouseClick(recorder, Qt.LeftButton)
        QTest.keyClick(recorder, Qt.Key_K, Qt.ControlModifier | Qt.ShiftModifier)
        assert recorder.value() == "ctrl+shift+k"
        window._show_named_page("Dictionary")
        assert not window.stack.currentWidget().findChildren(QTableWidget)
        dictionary_page = window.stack.currentWidget()
        term_input = dictionary_page.findChild(QLineEdit, "DictionaryTermInput")
        term_input.setText("Kubernetes")
        term_save = next(
            button for button in dictionary_page.findChildren(QPushButton) if button.property("role") == "dictionary-term-save"
        )
        QTest.mouseClick(term_save, Qt.LeftButton)
        assert window.widgets["vocabulary"].count() == 2
        assert window.widgets["vocabulary"].item(1).text() == "Kubernetes"
        term_remove = [
            button for button in dictionary_page.findChildren(QPushButton) if button.property("role") == "dictionary-term-remove"
        ][-1]
        QTest.mouseClick(term_remove, Qt.LeftButton)
        assert window.widgets["vocabulary"].count() == 1
        assert window._save_retry.text() == "Undo"
        QTest.mouseClick(window._save_retry, Qt.LeftButton)
        assert window.widgets["vocabulary"].count() == 2
        assert window.widgets["vocabulary"].item(1).text() == "Kubernetes"
        heard = dictionary_page.findChild(QLineEdit, "CorrectionHeardInput")
        replacement = dictionary_page.findChild(QLineEdit, "CorrectionReplacementInput")
        heard.setText("cube or netties")
        replacement.setText("Kubernetes")
        correction_save = next(
            button for button in dictionary_page.findChildren(QPushButton) if button.property("role") == "correction-save"
        )
        QTest.mouseClick(correction_save, Qt.LeftButton)
        assert window.corrections[-1].replacement == "Kubernetes"
        correction_remove = [
            button for button in dictionary_page.findChildren(QPushButton) if button.property("role") == "correction-remove"
        ][-1]
        QTest.mouseClick(correction_remove, Qt.LeftButton)
        assert len(window.corrections) == 1
        assert window._save_retry.text() == "Undo"
        QTest.mouseClick(window._save_retry, Qt.LeftButton)
        assert window.corrections[-1].replacement == "Kubernetes"

        window._show_named_page("Text Shortcuts")
        shortcuts_page = window.stack.currentWidget()
        shortcut_inputs = [
            field for field in shortcuts_page.findChildren(QLineEdit) if field.placeholderText().startswith(("Name,", "Voice trigger,"))
        ]
        assert len(shortcut_inputs) == 2
        shortcut_inputs[0].setText("Email signature")
        shortcut_inputs[1].setText("insert my signature")
        shortcut_text = shortcuts_page.findChild(QTextEdit, "TextShortcutContentInput")
        assert shortcut_text is not None
        shortcut_text.setPlainText("Regards, Avery")
        shortcut_save = next(button for button in shortcuts_page.findChildren(QPushButton) if button.text() == "Add shortcut")
        QTest.mouseClick(shortcut_save, Qt.LeftButton)
        assert len(window.snippets) == 4
        shortcut_remove = [button for button in shortcuts_page.findChildren(QPushButton) if button.property("role") == "shortcut-remove"][
            -1
        ]
        QTest.mouseClick(shortcut_remove, Qt.LeftButton)
        assert len(window.snippets) == 3
        assert window._save_retry.text() == "Undo"
        QTest.mouseClick(window._save_retry, Qt.LeftButton)
        assert window.snippets[-1].trigger == "insert my signature"
        brand_logo = window.window.findChild(QLabel, "BrandLogo")
        brand_name = window.window.findChild(QLabel, "BrandName")
        assert brand_logo is not None
        assert brand_name is not None
        assert brand_logo.pixmap() is not None
        assert not brand_logo.pixmap().isNull()
        assert window.window.findChild(QLabel, "BrandSubtitle") is None
        window.show()
        app.processEvents()
        assert brand_logo.mapTo(window.window, QPoint(0, 0)).x() == 37
        assert brand_logo.height() == 30
        assert brand_name.height() == brand_logo.height()
        assert brand_name.mapTo(window.window, QPoint(0, 0)).y() == brand_logo.mapTo(window.window, QPoint(0, 0)).y()
        assert window.window.minimumWidth() == 820
        assert window.window.minimumHeight() == 500
        assert window.window.findChild(QScrollArea, "NavScroll") is not None
        window._update_theme_preview("light")
        assert brand_logo.pixmap() is not None and not brand_logo.pixmap().isNull()
        assert all(toggle._accent == LIGHT.accent for toggle in window.theme_toggles)
        window._update_theme_preview("dark")
        assert brand_logo.pixmap() is not None and not brand_logo.pixmap().isNull()
        assert all(toggle._accent == DARK.accent for toggle in window.theme_toggles)
        assert window.widgets["dictation.polish_enabled"].accessibleName()

        window.window.resize(820, 500)
        for page_name in ["Dictation", "Polish", "Personalize", "History", "Privacy", "About"]:
            window._show_named_page(page_name)
            app.processEvents()
            page = window.stack.currentWidget()
            assert isinstance(page, QScrollArea)
            assert page.horizontalScrollBar().maximum() == 0

        window._show_toast("First")
        QTest.qWait(1000)
        window._show_toast("Second", "bad")
        QTest.qWait(800)
        assert window._save_indicator.isVisible()
        assert window._save_text.text() == "Second"
        assert window._save_indicator.property("tone") == "bad"
        indicator_pos = window._save_indicator.mapTo(window.window, QPoint(0, 0))
        indicator_center = indicator_pos.x() + (window._save_indicator.width() // 2)
        assert abs(indicator_center - (window.window.width() // 2)) <= 1
        assert indicator_pos.y() + window._save_indicator.height() == window.window.height() - 28
        window._show_toast(
            "Save failed",
            "bad",
            persistent=True,
            action_label="Retry",
            action_callback=lambda: None,
        )
        assert window._save_retry.isVisible()
        assert window._save_retry.text() == "Retry"
        assert not window._toast_hide_timer.isActive()
        window.close()
    app.processEvents()
