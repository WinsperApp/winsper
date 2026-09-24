from __future__ import annotations

from pathlib import Path


def run_onboarding_wizard(config_path: Path, auto_close_seconds: float | None = None) -> bool:
    try:
        from .onboarding_qt import run_onboarding_wizard as run_qt_onboarding_wizard
    except ImportError as exc:
        print(f"Winsper setup wizard is unavailable: {exc}")
        print("Install requirements or open config.yaml manually; continuing with defaults.")
        return True

    try:
        return run_qt_onboarding_wizard(config_path, auto_close_seconds)
    except ImportError as exc:
        print(f"Winsper setup wizard is unavailable: {exc}")
        print("Install requirements or open config.yaml manually; continuing with defaults.")
        return True
