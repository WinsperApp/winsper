"""Local support actions exposed through Polish voice commands."""

from __future__ import annotations

import subprocess
import threading

from .app_helpers import friendly_error_message, log_runtime_error
from .diagnostics import collect_diagnostics, format_diagnostics_report
from .voice_commands import VoiceCommand


class PipelineSupportActionsMixin:
    def _execute_voice_action(self, command: VoiceCommand) -> None:
        if command.action == "undo_last":
            self.undo_last_insertion()
            return
        if command.action == "copy_last":
            self._copy_last_output()
            return
        if command.action == "open_history":
            self._launch_voicepilot_window("--history", "History")
            return
        if command.action == "open_settings":
            self._launch_voicepilot_window("--settings", "Settings")
            return
        self.hud.show("Unknown command", command.label, "warning")

    def _copy_last_output(self) -> None:
        if not self.last.text:
            self.hud.show("Nothing to copy", "Dictate or polish first", "warning")
            return
        try:
            import pyperclip
        except ImportError as exc:
            log_runtime_error("copy last output", exc, self.config_path)
            self.hud.show("Copy failed", str(exc), "error")
            return
        pyperclip.copy(self.last.text)
        self.hud.show("Copied", f"{len(self.last.text.split())} words", "success")

    def copy_diagnostics(self) -> None:
        self.hud.show("Preparing diagnostics", "Copying report to clipboard", "process")
        worker = threading.Thread(
            target=self._copy_diagnostics_worker,
            name="WinsperCopyDiagnostics",
            daemon=True,
        )
        worker.start()

    def _copy_diagnostics_worker(self) -> None:
        try:
            import pyperclip

            report = format_diagnostics_report(collect_diagnostics(self.config, self.config_path))
            pyperclip.copy(report)
        except Exception as exc:
            log_runtime_error("copy diagnostics", exc, self.config_path)
            self.hud.show("Diagnostics failed", friendly_error_message(exc), "error")
            return
        self.hud.show("Diagnostics copied", "Paste into support chat", "success")

    def _launch_voicepilot_window(self, flag: str, label: str) -> None:
        from .process_launch import app_command, app_working_directory

        try:
            subprocess.Popen(
                app_command(["--config", str(self.config_path), flag]),
                cwd=str(app_working_directory()),
                close_fds=True,
            )
        except Exception as exc:
            log_runtime_error(f"{label.lower()} launch", exc, self.config_path)
            self.hud.show(f"{label} failed", str(exc), "error")
            return
        self.hud.show(f"{label} opened", "Voice command", "success")
