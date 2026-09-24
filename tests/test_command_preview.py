from voicepilot.command_preview import RewritePreview, _preview_detail, _run_preview_app, _stylesheet
from voicepilot.settings_style import settings_stylesheet
from voicepilot.theme import DARK, LIGHT


def test_preview_uses_settings_design_system_in_both_themes():
    for palette in (DARK, LIGHT):
        stylesheet = _stylesheet(palette)

        assert stylesheet.startswith(settings_stylesheet(palette))
        assert "QFrame#PreviewShell" in stylesheet
        assert "QPlainTextEdit#PreviewText" in stylesheet
        assert 'font-family: "Segoe UI Variable"' not in stylesheet


def test_preview_context_and_request_are_specific_not_generic():
    preview = RewritePreview(
        instruction_label="Bullets",
        source_label="selected text",
        context_label="Notepad",
        original_text="Original",
        rewritten_text="- Original",
        instruction_text="Turn these into bullet points",
    )

    assert _preview_detail(preview) == "Bullets · Notepad · selected text"
    assert preview.instruction_text == "Turn these into bullet points"


def test_preview_reuses_settings_cursor_roles(monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit, QPushButton

    app = QApplication.instance() or QApplication([])
    captured = {}

    def inspect_dialog(dialog):
        captured["buttons"] = {button.text(): button.cursor().shape() for button in dialog.findChildren(QPushButton)}
        captured["editors"] = [editor.viewport().cursor().shape() for editor in dialog.findChildren(QPlainTextEdit)]
        return 0

    monkeypatch.setattr(QDialog, "exec", inspect_dialog)
    _run_preview_app(
        RewritePreview(
            instruction_label="Bullets",
            source_label="selected text",
            context_label="Notepad",
            original_text="Original",
            rewritten_text="• Original",
            instruction_text="Turn these into bullet points",
            theme="dark",
        )
    )
    app.processEvents()

    assert set(captured["buttons"]) == {"Cancel", "Copy", "Insert below", "Replace"}
    assert all(cursor == Qt.PointingHandCursor for cursor in captured["buttons"].values())
    assert all(cursor == Qt.IBeamCursor for cursor in captured["editors"])
