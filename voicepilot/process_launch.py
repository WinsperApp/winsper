from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_working_directory() -> Path:
    if is_frozen_app():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def app_command(arguments: Iterable[str] = (), *, windowed: bool = False) -> list[str]:
    """Build a Winsper command that works from source and from PyInstaller."""
    executable = Path(sys.executable)
    command: list[str]
    if is_frozen_app():
        command = [str(executable)]
    else:
        if windowed:
            pythonw = executable.with_name("pythonw.exe")
            if pythonw.exists():
                executable = pythonw
        command = [str(executable), "-m", "voicepilot"]
    command.extend(str(argument) for argument in arguments)
    return command
