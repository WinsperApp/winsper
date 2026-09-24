from __future__ import annotations

import multiprocessing as mp
import queue
from dataclasses import dataclass


@dataclass(frozen=True)
class RewritePreview:
    instruction_label: str
    source_label: str
    context_label: str
    original_text: str
    rewritten_text: str
    instruction_text: str = ""
    theme: str = "system"


@dataclass(frozen=True)
class RewritePreviewResult:
    action: str
    text: str = ""
    error: str = ""


def choose_rewrite_action(preview: RewritePreview) -> RewritePreviewResult:
    context = mp.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_run_preview_process,
        args=(preview, result_queue),
        name="WinsperCommandPreview",
    )
    try:
        process.start()
    except Exception as exc:
        return RewritePreviewResult("error", error=str(exc))

    process.join()
    try:
        raw = result_queue.get(timeout=0.4)
    except queue.Empty:
        return RewritePreviewResult("cancel")
    if not isinstance(raw, dict):
        return RewritePreviewResult("cancel")
    return RewritePreviewResult(
        action=str(raw.get("action") or "cancel"),
        text=str(raw.get("text") or ""),
        error=str(raw.get("error") or ""),
    )


def _run_preview_process(preview: RewritePreview, result_queue) -> None:
    try:
        result_queue.put(_run_preview_app(preview))
    except Exception as exc:
        result_queue.put({"action": "error", "error": str(exc)})


def _run_preview_app(preview: RewritePreview) -> dict[str, str]:
    import sys

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QStyleFactory,
        QVBoxLayout,
    )

    from PIL.ImageQt import ImageQt

    from .branding import create_logo_image, qt_window_icon, set_windows_app_user_model_id
    from .settings_widgets import create_settings_button_cursor_policy
    from .theme import get_palette
    from .windows_ui import apply_native_window_style

    set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Winsper")
    app.setFont(QFont("Segoe UI", 10))
    if "Fusion" in QStyleFactory.keys():
        app.setStyle(QStyleFactory.create("Fusion"))

    palette = get_palette(preview.theme)
    _apply_palette(app, palette, QColor, QPalette)

    dialog = QDialog()
    dialog.setObjectName("RewritePreviewDialog")
    dialog.setWindowTitle("Review rewrite · Winsper")
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
    dialog.setMinimumSize(680, 440)
    dialog.resize(780, 520)
    dialog.setStyleSheet(_stylesheet(palette))
    icon = qt_window_icon(QIcon, QPixmap)
    if not icon.isNull():
        dialog.setWindowIcon(icon)
    apply_native_window_style(dialog, palette)

    result = {"action": "cancel", "text": ""}

    root = QVBoxLayout(dialog)
    root.setContentsMargins(14, 14, 14, 14)
    root.setSpacing(0)

    shell = QFrame()
    shell.setObjectName("PreviewShell")
    root.addWidget(shell)
    content = QVBoxLayout(shell)
    content.setContentsMargins(24, 22, 24, 20)
    content.setSpacing(16)

    header = QHBoxLayout()
    header.setSpacing(10)
    logo = QLabel()
    logo.setObjectName("PreviewLogo")
    logo.setPixmap(QPixmap.fromImage(ImageQt(create_logo_image(28))))
    logo.setFixedSize(30, 30)
    logo.setAlignment(Qt.AlignCenter)
    header.addWidget(logo)

    title_block = QVBoxLayout()
    title = QLabel("Review rewrite")
    title.setObjectName("PreviewTitle")
    detail = QLabel(_preview_detail(preview))
    detail.setObjectName("PreviewContext")
    detail.setWordWrap(True)
    title_block.addWidget(title)
    title_block.addWidget(detail)
    title_block.setSpacing(2)
    header.addLayout(title_block, 1)
    content.addLayout(header)

    if preview.instruction_text:
        request = QLabel(f"Request · {preview.instruction_text}")
        request.setObjectName("PreviewRequest")
        request.setWordWrap(True)
        request.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.addWidget(request)

    body = QHBoxLayout()
    body.setSpacing(16)
    original = _text_panel("Original", preview.original_text, editable=False)
    output, output_edit = _editable_panel("Polished version", preview.rewritten_text)
    body.addWidget(original, 1)
    body.addWidget(output, 1)
    content.addLayout(body, 1)

    hint = QLabel("Edit the polished text if needed, then choose how to apply it.")
    hint.setObjectName("PreviewHint")
    content.addWidget(hint)

    actions = QHBoxLayout()
    cancel = QPushButton("Cancel")
    cancel.setObjectName("LinkButton")
    copy = QPushButton("Copy")
    insert = QPushButton("Insert below")
    replace = QPushButton("Replace")
    replace.setObjectName("PrimaryButton")
    replace.setDefault(True)

    def finish(action: str) -> None:
        result["action"] = action
        result["text"] = output_edit.toPlainText().strip()
        dialog.accept()

    cancel.clicked.connect(lambda: finish("cancel"))
    copy.clicked.connect(lambda: finish("copy"))
    insert.clicked.connect(lambda: finish("insert_below"))
    replace.clicked.connect(lambda: finish("replace"))

    actions.addWidget(cancel)
    actions.addStretch(1)
    for button in [copy, insert, replace]:
        actions.addWidget(button)
    content.addLayout(actions)

    cursor_policy = create_settings_button_cursor_policy(dialog)
    dialog._winsper_cursor_policy = cursor_policy
    app.installEventFilter(cursor_policy)
    cursor_policy.apply_tree(dialog)
    dialog.rejected.connect(lambda: result.update({"action": "cancel", "text": ""}))
    output_edit.setFocus()
    try:
        dialog.exec()
    finally:
        app.removeEventFilter(cursor_policy)
    return result


def _apply_palette(app, palette, QColor, QPalette) -> None:
    qt_palette = QPalette()
    colors = {
        QPalette.Window: palette.bg,
        QPalette.WindowText: palette.text,
        QPalette.Base: palette.field,
        QPalette.AlternateBase: palette.surface_2,
        QPalette.Text: palette.text,
        QPalette.Button: palette.surface_2,
        QPalette.ButtonText: palette.text,
        QPalette.Highlight: palette.accent_2,
        QPalette.HighlightedText: palette.on_accent,
        QPalette.PlaceholderText: palette.subtle,
    }
    for role, value in colors.items():
        qt_palette.setColor(role, QColor(value))
    app.setPalette(qt_palette)


def _text_panel(title: str, text: str, editable: bool):
    from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QVBoxLayout

    panel = QFrame()
    panel.setObjectName("PreviewColumn")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    label = QLabel(title)
    label.setObjectName("PreviewPanelTitle")
    edit = QPlainTextEdit()
    edit.setPlainText(text)
    edit.setReadOnly(not editable)
    edit.setObjectName("PreviewText")
    edit.setProperty("editable", editable)
    layout.addWidget(label)
    layout.addWidget(edit, 1)
    panel._voicepilot_edit = edit
    return panel


def _editable_panel(title: str, text: str):
    panel = _text_panel(title, text, editable=True)
    return panel, panel._voicepilot_edit


def _preview_detail(preview: RewritePreview) -> str:
    parts = [part for part in [preview.instruction_label, preview.context_label, preview.source_label] if part]
    if not parts:
        return "Choose Replace, Insert Below, Copy, or Cancel."
    return " · ".join(parts)


def _stylesheet(palette) -> str:
    from .settings_style import settings_stylesheet

    return settings_stylesheet(palette) + f"""
    QDialog#RewritePreviewDialog {{ background: {palette.bg}; color: {palette.text}; }}
    QFrame#PreviewShell {{
        background: {palette.surface}; border: 1px solid {palette.border_soft}; border-radius: 18px;
    }}
    QLabel#PreviewLogo {{ background: transparent; border: none; padding: 0; }}
    QLabel#PreviewTitle {{ color: {palette.text}; font-size: 22px; font-weight: 600; }}
    QLabel#PreviewContext {{ color: {palette.muted}; font-size: 12px; font-weight: 400; }}
    QLabel#PreviewRequest {{
        color: {palette.text}; background: {palette.surface_2}; border: 1px solid {palette.border_soft};
        border-radius: 10px; padding: 9px 12px; font-size: 12px;
    }}
    QFrame#PreviewColumn {{ background: transparent; border: none; }}
    QLabel#PreviewPanelTitle {{ color: {palette.text}; font-size: 13px; font-weight: 600; }}
    QPlainTextEdit#PreviewText {{
        background: {palette.surface_2}; color: {palette.text}; border: 1px solid {palette.border_soft};
        border-radius: 12px; padding: 12px; font-size: 14px;
        selection-background-color: {palette.accent}; selection-color: {palette.on_accent};
    }}
    QPlainTextEdit#PreviewText[editable="true"] {{ background: {palette.field}; border-color: {palette.border}; }}
    QPlainTextEdit#PreviewText:focus {{ border-color: {palette.accent}; }}
    QLabel#PreviewHint {{ color: {palette.muted}; font-size: 12px; }}
    """
