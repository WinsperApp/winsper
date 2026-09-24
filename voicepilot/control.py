from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .storage import atomic_write_text

VALID_COMMANDS = {"stop", "restart", "reload", "reload_silent", "pause", "resume"}


def control_command_path(config_path: Path) -> Path:
    return config_path.parent / "voicepilot.control"


def request_control_command(config_path: Path, command: str) -> Path:
    command = command.strip().lower()
    if command not in VALID_COMMANDS:
        raise ValueError(f"Unsupported Winsper control command: {command}")
    path = control_command_path(config_path)
    atomic_write_text(path, f"{command}\n{datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
    return path


def consume_control_command(config_path: Path) -> str | None:
    path = control_command_path(config_path)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        path.unlink(missing_ok=True)
    except OSError:
        return None
    lines = text.splitlines()
    command = lines[0].strip().lower() if lines else ""
    if len(lines) > 1:
        try:
            created_at = datetime.fromisoformat(lines[1].strip())
            if (datetime.now(timezone.utc) - created_at).total_seconds() > 300:
                return None
        except ValueError:
            pass
    return command if command in VALID_COMMANDS else None
