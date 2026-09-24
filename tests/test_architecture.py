from __future__ import annotations

import dataclasses
import enum
import subprocess
import sys
from pathlib import Path

from voicepilot.action_state import ActionEvent, ActionPhase, CancelOutcome, PauseOutcome
from voicepilot.audio import AudioCaptureDiagnostics, AudioStartMetrics
from voicepilot.config_migrations import ConfigMigration
from voicepilot.paste import DeliveryStatus, InsertResult
from voicepilot.selection import SelectionResult, SelectionStatus


def test_phase6_architecture_gate():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_architecture.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_runtime_boundaries_use_typed_results_and_states():
    for result_type in (
        ActionEvent,
        AudioCaptureDiagnostics,
        AudioStartMetrics,
        ConfigMigration,
        InsertResult,
        SelectionResult,
    ):
        assert dataclasses.is_dataclass(result_type)
    for state_type in (ActionPhase, CancelOutcome, DeliveryStatus, PauseOutcome, SelectionStatus):
        assert issubclass(state_type, enum.Enum)


def test_hud_parent_facade_does_not_import_qt_rendering_stack():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import voicepilot.hud_qt; "
                "print(any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules))"
            ),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "False"


def test_refactor_facades_preserve_public_exports_and_unicode_copy():
    from voicepilot import hud_qt, models
    from voicepilot.models import find_speech_model

    assert hud_qt.__all__ == ["QtStatusHUD", "hud_accessible_text", "run_hud_process"]
    assert models.__all__ == [
        "PARAKEET_V3_LANGUAGES",
        "SPEECH_LANGUAGE_NAMES",
        "model_supports_language",
        "speech_language_options",
    ]
    assert find_speech_model("parakeet-tdt-0.6b-v2-int8").label == "Parakeet v2 · English"

    root = Path(__file__).resolve().parents[1]
    extracted = (
        "settings_model_pages.py",
        "speech_model_catalog.py",
        "polish_prompts.py",
        "polish_validation.py",
    )
    for filename in extracted:
        text = (root / "voicepilot" / filename).read_text(encoding="utf-8")
        assert not any(marker in text for marker in ("Â·", "â€”", "à¤", "ā€"))
