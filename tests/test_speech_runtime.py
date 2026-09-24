from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from unittest.mock import patch

from voicepilot.ai_hardware import AIGpu
from voicepilot.speech_model_catalog import HardwareSummary, recommended_model_policy
from voicepilot.speech_runtime import (
    RuntimeAsset,
    acceleration_status,
    install_nvidia_runtime,
    nvidia_acceleration_ready,
    runtime_is_installed,
    runtime_root,
)


def _wheel(path: Path) -> RuntimeAsset:
    with zipfile.ZipFile(path, "w") as archive:
        for name in ("cudart64_12.dll", "cublas64_12.dll", "cudnn64_8.dll"):
            archive.writestr(f"nvidia/runtime/bin/{name}", "fixture")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return RuntimeAsset(path.name, path.as_uri(), digest, path.stat().st_size)


def test_managed_nvidia_runtime_installs_verified_wheel(tmp_path, monkeypatch):
    import voicepilot.speech_runtime as runtime

    asset = _wheel(tmp_path / "runtime.whl")
    monkeypatch.setattr(runtime, "CUDA12_ASSETS", (asset,))
    gpu = AIGpu("NVIDIA Test", "nvidia", 8, "CUDA0")
    with patch("voicepilot.speech_runtime.nvidia_gpu", return_value=gpu):
        destination = install_nvidia_runtime(root=tmp_path)

    assert runtime_is_installed(tmp_path)
    assert destination == runtime_root(tmp_path)
    assert (destination / "installation.json").is_file()


def test_runtime_replace_retries_transient_windows_lock(tmp_path, monkeypatch):
    import voicepilot.speech_runtime as runtime

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    calls = 0
    original_replace = Path.replace

    def briefly_locked(path, target):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("scanner still holds the directory")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", briefly_locked)
    monkeypatch.setattr(runtime.time, "sleep", lambda _seconds: None)

    runtime._replace_with_retry(source, destination)

    assert calls == 3
    assert destination.is_dir()


def test_acceleration_status_is_human_readable(tmp_path, monkeypatch):
    import voicepilot.speech_runtime as runtime

    gpu = AIGpu("NVIDIA RTX Test", "nvidia", 6, "CUDA0")
    monkeypatch.setattr(runtime, "nvidia_gpu", lambda: gpu)
    monkeypatch.setattr(runtime, "system_runtime_available", lambda: False)
    status = acceleration_status(tmp_path)

    assert status.gpu == gpu
    assert not status.installed
    assert "NVIDIA RTX Test" in status.detail
    assert "acceleration available" in status.detail


def test_system_runtime_detection_reads_windows_path(tmp_path, monkeypatch):
    import voicepilot.speech_runtime as runtime

    bin_dir = tmp_path / "cuda" / "bin"
    bin_dir.mkdir(parents=True)
    for name in runtime.REQUIRED_DLLS:
        (bin_dir / name).write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(runtime.os, "name", "nt")
    monkeypatch.setenv("PATH", str(bin_dir))

    assert runtime.system_runtime_available()


def test_acceleration_verification_belongs_to_current_gpu(tmp_path, monkeypatch):
    import json

    import voicepilot.speech_runtime as runtime

    gpu = AIGpu("NVIDIA RTX Test", "nvidia", 8, "CUDA0")
    monkeypatch.setattr(runtime, "nvidia_gpu", lambda: gpu)
    monkeypatch.setattr(runtime, "runtime_is_installed", lambda _root=None: True)
    monkeypatch.setattr(runtime, "system_runtime_available", lambda: False)
    marker = runtime_root(tmp_path) / "verification.json"
    marker.parent.mkdir(parents=True)

    marker.write_text(
        json.dumps({"id": runtime.CUDA12_RUNTIME_ID, "gpu": "  NVIDIA   RTX TEST  ", "model": "large-v3-turbo"}),
        encoding="utf-8",
    )
    assert acceleration_status(tmp_path).verified

    marker.write_text(
        json.dumps({"id": runtime.CUDA12_RUNTIME_ID, "gpu": "NVIDIA Other", "model": "large-v3-turbo"}),
        encoding="utf-8",
    )
    assert not acceleration_status(tmp_path).verified

    marker.write_text(
        json.dumps({"id": "old-runtime", "gpu": gpu.name, "model": "large-v3-turbo"}),
        encoding="utf-8",
    )
    assert not acceleration_status(tmp_path).verified


def test_automatic_nvidia_acceleration_requires_verified_six_gb_gpu(monkeypatch):
    import voicepilot.speech_runtime as runtime

    def status(memory_gb, verified=True):
        gpu = AIGpu("NVIDIA Test", "nvidia", memory_gb, "CUDA0")
        return runtime.AccelerationStatus(gpu, True, False, verified, "")

    monkeypatch.setattr(runtime, "acceleration_status", lambda _root=None: status(6))
    assert nvidia_acceleration_ready()

    monkeypatch.setattr(runtime, "acceleration_status", lambda _root=None: status(5.9))
    assert not nvidia_acceleration_ready()

    monkeypatch.setattr(runtime, "acceleration_status", lambda _root=None: status(None))
    assert not nvidia_acceleration_ready()

    monkeypatch.setattr(runtime, "acceleration_status", lambda _root=None: status(8, verified=False))
    assert not nvidia_acceleration_ready()


def test_automatic_nvidia_acceleration_tolerates_nominal_six_gb_reporting(monkeypatch):
    import voicepilot.speech_runtime as runtime

    def status(memory_gb):
        gpu = AIGpu("NVIDIA RTX 4050", "nvidia", memory_gb, "CUDA0")
        return runtime.AccelerationStatus(gpu, True, False, True, "")

    monkeypatch.setattr(runtime, "acceleration_status", lambda _root=None: status(6141 / 1024))
    assert nvidia_acceleration_ready()

    monkeypatch.setattr(runtime, "acceleration_status", lambda _root=None: status(5.98))
    assert not nvidia_acceleration_ready()


def test_recommended_model_uses_cuda_only_after_verified_eligibility():
    nvidia = HardwareSummary("CPU", 16, ("NVIDIA Test",), True, False)
    with patch("voicepilot.speech_runtime.nvidia_acceleration_ready", return_value=False):
        assert recommended_model_policy("en", nvidia).dictation.model == "small.en"
    with patch("voicepilot.speech_runtime.nvidia_acceleration_ready", return_value=True):
        assert recommended_model_policy("en", nvidia).dictation.model == "large-v3-turbo"


def test_managed_runtime_activation_is_idempotent(tmp_path, monkeypatch):
    import voicepilot.speech_runtime as runtime

    bin_dir = runtime_root(tmp_path) / "nvidia" / "bin"
    bin_dir.mkdir(parents=True)
    for name in runtime.REQUIRED_DLLS:
        (bin_dir / name).write_text("fixture", encoding="utf-8")
    handles = []
    monkeypatch.setattr(runtime.os, "name", "nt")
    monkeypatch.setattr(runtime, "runtime_is_installed", lambda _root=None: True)
    monkeypatch.setattr(runtime, "_activated_runtime_directories", set())
    monkeypatch.setattr(runtime, "_dll_handles", [])
    monkeypatch.setattr(runtime.os, "add_dll_directory", lambda value: handles.append(value) or object(), raising=False)
    monkeypatch.setenv("PATH", "")

    assert runtime.activate_managed_runtime(tmp_path)
    assert runtime.activate_managed_runtime(tmp_path)

    assert handles == [str(bin_dir)]
    assert runtime.os.environ["PATH"].split(runtime.os.pathsep).count(str(bin_dir)) == 1
