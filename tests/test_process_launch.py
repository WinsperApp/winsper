from __future__ import annotations

from pathlib import Path

from voicepilot import model_storage
from voicepilot import process_launch
from voicepilot.__main__ import build_parser


def test_app_command_uses_module_from_source(monkeypatch, tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.touch()
    monkeypatch.setattr(process_launch.sys, "executable", str(python))
    monkeypatch.delattr(process_launch.sys, "frozen", raising=False)

    assert process_launch.app_command(["--settings"]) == [str(python), "-m", "voicepilot", "--settings"]


def test_app_command_uses_frozen_executable_without_python_module_flags(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "Winsper.exe"
    executable.touch()
    monkeypatch.setattr(process_launch.sys, "executable", str(executable))
    monkeypatch.setattr(process_launch.sys, "frozen", True, raising=False)

    assert process_launch.app_command(["--settings"]) == [str(executable), "--settings"]
    assert process_launch.app_working_directory() == tmp_path


def test_windowed_source_command_prefers_pythonw(monkeypatch, tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.touch()
    pythonw.touch()
    monkeypatch.setattr(process_launch.sys, "executable", str(python))
    monkeypatch.delattr(process_launch.sys, "frozen", raising=False)

    assert process_launch.app_command(["--skip-setup"], windowed=True) == [
        str(pythonw),
        "-m",
        "voicepilot",
        "--skip-setup",
    ]


def test_frozen_model_cache_is_owned_by_winsper(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert model_storage.model_storage_display_root() == tmp_path / "Winsper" / "models"
    assert model_storage.huggingface_cache_root() == tmp_path / "Winsper" / "models" / "huggingface" / "hub"


def test_model_cache_environment_override_wins(monkeypatch, tmp_path: Path) -> None:
    explicit = tmp_path / "managed-cache"
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(explicit))

    assert model_storage.huggingface_cache_root() == explicit


def test_packaged_benchmark_arguments_are_accepted_by_main_parser() -> None:
    args = build_parser().parse_args(
        [
            "--benchmark",
            "--models",
            "small,large-v3-turbo",
            "--device",
            "cuda",
            "--compute-type",
            "float16",
            "--seconds",
            "5",
            "--save-clip",
        ]
    )

    assert args.benchmark is True
    assert args.models == "small,large-v3-turbo"
    assert args.save_clip is True
