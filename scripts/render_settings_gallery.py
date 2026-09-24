"""Render Winsper's consumer Settings destinations with real Qt widgets."""

# ruff: noqa: E402 -- repo root must be on sys.path before local imports.

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QPushButton, QScrollArea, QTabWidget

from voicepilot.config import AppConfig, save_config
from voicepilot.settings_qt import SettingsWindow


PAGES = ("General", "Dictation", "Polish", "Personalize", "History", "Privacy", "Advanced", "About")


def _register_windows_fonts() -> None:
    """Offscreen Qt does not discover DirectWrite fonts by itself."""
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "segoeuil.ttf", "consola.ttf"):
        path = fonts / filename
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


def _wait(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def render_gallery(output_dir: Path) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    _register_windows_fonts()
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="winsper-settings-") as temporary:
        for theme in ("light", "dark"):
            config_path = Path(temporary) / f"{theme}.yaml"
            config = AppConfig()
            config.hud.theme = theme
            save_config(config, config_path)
            with patch.object(SettingsWindow, "_refresh_home_status"):
                window = SettingsWindow(config_path)
            window._set_home_control(
                "Winsper is active",
                "Dictation and Polish shortcuts are available.",
                "active",
                "pause",
                True,
            )
            window.window.resize(1180, 780)
            window.show()
            app.processEvents()
            for page in PAGES:
                window._show_named_page(page)
                app.processEvents()
                _wait(650 if page == "General" else 80)
                destination = output_dir / f"{theme}-{page.lower().replace(' ', '-').replace('&', 'and')}.png"
                if not window.window.grab().save(str(destination), "PNG"):
                    raise RuntimeError(f"Could not save {destination}")
                rendered.append(destination)
                if page == "General":
                    appearance = window.stack.currentWidget().findChild(QComboBox, "AppearanceCombo")
                    appearance.showPopup()
                    app.processEvents()
                    popup_destination = output_dir / f"{theme}-general-appearance-popup.png"
                    if not appearance.view().window().grab().save(str(popup_destination), "PNG"):
                        raise RuntimeError(f"Could not save {popup_destination}")
                    rendered.append(popup_destination)
                    appearance.hidePopup()
                elif page == "Dictation":
                    combos = window.stack.currentWidget().findChildren(QComboBox, "SettingsCombo")
                    for combo, label in zip(combos[:2], ("microphone", "language"), strict=False):
                        combo.showPopup()
                        app.processEvents()
                        popup_destination = output_dir / f"{theme}-dictation-{label}-popup.png"
                        if not combo.view().window().grab().save(str(popup_destination), "PNG"):
                            raise RuntimeError(f"Could not save {popup_destination}")
                        rendered.append(popup_destination)
                        combo.hidePopup()
                elif page == "Personalize":
                    personalize = window.stack.currentWidget()
                    top_tabs = personalize.findChild(QTabWidget, "PersonalizeTabs")
                    inner_tabs = personalize.findChild(QTabWidget, "PersonalizeInnerTabs")
                    if top_tabs is None or inner_tabs is None:
                        raise RuntimeError("Personalize preview tabs were not built")
                    inner_tabs.setCurrentIndex(1)
                    app.processEvents()
                    corrections_destination = output_dir / f"{theme}-personalize-corrections.png"
                    if not window.window.grab().save(str(corrections_destination), "PNG"):
                        raise RuntimeError(f"Could not save {corrections_destination}")
                    rendered.append(corrections_destination)
                    top_tabs.setCurrentIndex(1)
                    app.processEvents()
                    shortcuts_destination = output_dir / f"{theme}-personalize-shortcuts.png"
                    if not window.window.grab().save(str(shortcuts_destination), "PNG"):
                        raise RuntimeError(f"Could not save {shortcuts_destination}")
                    rendered.append(shortcuts_destination)
            window._open_advanced_polish_ai()
            app.processEvents()
            polish_dialog = window._advanced_dialog
            polish_dialog.resize(1040, 720)
            app.processEvents()
            polish_destination = output_dir / f"{theme}-polish-advanced.png"
            if not polish_dialog.grab().save(str(polish_destination), "PNG"):
                raise RuntimeError(f"Could not save {polish_destination}")
            rendered.append(polish_destination)
            polish_scroll = polish_dialog.findChild(QScrollArea, "Page")
            winsper_panel = polish_dialog.findChild(QFrame, "ProviderIntro")
            polish_scroll.ensureWidgetVisible(winsper_panel, 0, 12)
            app.processEvents()
            winsper_destination = output_dir / f"{theme}-polish-winsper-ai-details.png"
            if not polish_dialog.grab().save(str(winsper_destination), "PNG"):
                raise RuntimeError(f"Could not save {winsper_destination}")
            rendered.append(winsper_destination)

            ollama_button = next(
                button for button in polish_dialog.findChildren(QPushButton, "ProviderOption") if button.text() == "Ollama"
            )
            ollama_button.click()
            app.processEvents()
            ollama_panel = polish_dialog.findChild(QFrame, "ProviderIntro")
            polish_scroll.ensureWidgetVisible(ollama_panel, 0, 12)
            app.processEvents()
            ollama_destination = output_dir / f"{theme}-polish-ollama-details.png"
            if not polish_dialog.grab().save(str(ollama_destination), "PNG"):
                raise RuntimeError(f"Could not save {ollama_destination}")
            rendered.append(ollama_destination)
            polish_dialog.close()
            window.close()
            app.processEvents()

            with (
                patch.object(SettingsWindow, "_refresh_home_status"),
                patch(
                    "voicepilot.settings_dictation_page.installed_status",
                    return_value=type("InstallState", (), {"installed": False})(),
                ),
                patch(
                    "voicepilot.settings_speech_models_page.installed_status",
                    return_value=type("InstallState", (), {"installed": False})(),
                ),
                patch(
                    "voicepilot.settings_dictation_page.engine_runtime_available",
                    return_value=True,
                ),
                patch(
                    "voicepilot.settings_speech_models_page.engine_runtime_available",
                    return_value=True,
                ),
            ):
                setup_window = SettingsWindow(config_path)
                setup_window.window.resize(1180, 780)
                setup_window.show()
                setup_window._show_named_page("Dictation")
                app.processEvents()
                fast = next(
                    button
                    for button in setup_window.stack.currentWidget().findChildren(
                        QPushButton,
                        "QualityOption",
                    )
                    if button.text() == "Fast"
                )
                fast.click()
                app.processEvents()
                setup_destination = output_dir / f"{theme}-dictation-advanced-download.png"
                if not setup_window._advanced_dialog.grab().save(str(setup_destination), "PNG"):
                    raise RuntimeError(f"Could not save {setup_destination}")
                rendered.append(setup_destination)
                setup_window.close()
                app.processEvents()
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/settings"))
    args = parser.parse_args()
    for path in render_gallery(args.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
