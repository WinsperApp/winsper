"""App-managed CUDA 12/cuDNN 8 runtime for Faster-Whisper on Windows."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ai_catalog import local_ai_root
from .ai_hardware import AIGpu, detect_ai_hardware
from .storage import atomic_write_json


def _replace_with_retry(source: Path, destination: Path, *, attempts: int = 5) -> None:
    """Atomically replace a directory despite brief Windows scanner locks."""
    for attempt in range(attempts):
        try:
            source.replace(destination)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


@dataclass(frozen=True)
class RuntimeAsset:
    filename: str
    url: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class RuntimeProgress:
    status: str
    downloaded_bytes: int = 0
    total_bytes: int = 0

    @property
    def percent(self) -> int | None:
        return min(100, int(self.downloaded_bytes * 100 / self.total_bytes)) if self.total_bytes else None


@dataclass(frozen=True)
class AccelerationStatus:
    gpu: AIGpu | None
    installed: bool
    system_runtime: bool
    verified: bool
    detail: str


CUDA12_RUNTIME_ID = "cuda12-cudnn8-win-x64-v1"
CUDA12_ASSETS: tuple[RuntimeAsset, ...] = (
    RuntimeAsset(
        "nvidia_cuda_runtime_cu12-12.4.127-py3-none-win_amd64.whl",
        "https://files.pythonhosted.org/packages/a8/8b/450e93fab75d85a69b50ea2d5fdd4ff44541e0138db16f9cd90123ef4de4/"
        "nvidia_cuda_runtime_cu12-12.4.127-py3-none-win_amd64.whl",
        "09c2e35f48359752dfa822c09918211844a3d93c100a715d79b59591130c5e1e",
        878_808,
    ),
    RuntimeAsset(
        "nvidia_cublas_cu12-12.4.5.8-py3-none-win_amd64.whl",
        "https://files.pythonhosted.org/packages/e2/2a/4f27ca96232e8b5269074a72e03b4e0d43aa68c9b965058b1684d07c6ff8/"
        "nvidia_cublas_cu12-12.4.5.8-py3-none-win_amd64.whl",
        "5a796786da89203a0657eda402bcdcec6180254a8ac22d72213abc42069522dc",
        396_895_858,
    ),
    RuntimeAsset(
        "nvidia_cudnn_cu12-8.9.6.50-py3-none-win_amd64.whl",
        "https://files.pythonhosted.org/packages/c1/a3/e023850b3966beafe2e466de126526e5da1220003baa0705475fc4446c99/"
        "nvidia_cudnn_cu12-8.9.6.50-py3-none-win_amd64.whl",
        "acfc4447a9345e8ba525e3b0641ee64bdfd35189ab9904241814ff991792f77a",
        719_348_966,
    ),
)
REQUIRED_DLLS = ("cudart64_12.dll", "cublas64_12.dll", "cudnn64_8.dll")
NVIDIA_TURBO_MIN_VRAM_GB = 6.0
NVIDIA_VRAM_REPORTING_TOLERANCE_GB = 0.01
_dll_handles: list[object] = []
_activated_runtime_directories: set[str] = set()
_dll_directory_lock = threading.Lock()

ProgressCallback = Callable[[RuntimeProgress], None]


def runtime_root(root: Path | None = None) -> Path:
    return (root or local_ai_root().parent) / "speech-runtime" / CUDA12_RUNTIME_ID


def runtime_size_bytes() -> int:
    return sum(asset.size_bytes for asset in CUDA12_ASSETS)


def nvidia_gpu() -> AIGpu | None:
    return next((gpu for gpu in detect_ai_hardware().gpus if gpu.vendor == "nvidia"), None)


def runtime_is_installed(root: Path | None = None) -> bool:
    directory = runtime_root(root)
    marker = directory / "installation.json"
    if not marker.is_file() or not all(_find_dll(directory, name) for name in REQUIRED_DLLS):
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload == {"id": CUDA12_RUNTIME_ID, "assets": [asset.sha256 for asset in CUDA12_ASSETS]}


def system_runtime_available() -> bool:
    if os.name != "nt":
        return False
    # Presence is intentionally not treated as success. A later real CUDA
    # decode decides that. This only avoids re-downloading a runtime the user
    # already installed system-wide.
    directories = [Path(value) for value in os.environ.get("PATH", "").split(os.pathsep) if value]
    return all(any((directory / name).is_file() for directory in directories) for name in REQUIRED_DLLS)


def _verification_path(root: Path | None = None) -> Path:
    directory = runtime_root(root)
    if runtime_is_installed(root):
        return directory / "verification.json"
    return directory.parent / "system-cuda12-verification.json"


def _verification_matches_gpu(root: Path | None, gpu: AIGpu | None) -> bool:
    if gpu is None:
        return False
    try:
        payload = json.loads(_verification_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("id") == CUDA12_RUNTIME_ID
        and _normalized_gpu_name(payload.get("gpu")) == _normalized_gpu_name(gpu.name)
    )


def acceleration_status(root: Path | None = None) -> AccelerationStatus:
    gpu = nvidia_gpu()
    installed = runtime_is_installed(root)
    system_ready = system_runtime_available()
    verified = (installed or system_ready) and _verification_matches_gpu(root, gpu)
    if gpu is None:
        return AccelerationStatus(None, installed, system_ready, verified, "No NVIDIA GPU detected. CPU mode remains available.")
    vram = f" · {gpu.memory_gb:.0f} GB VRAM" if gpu.memory_gb is not None else ""
    suffix = (
        "GPU acceleration enabled"
        if verified
        else ("CUDA runtime detected; verification needed" if system_ready else ("runtime installed; verification needed" if installed else "NVIDIA acceleration available"))
    )
    return AccelerationStatus(gpu, installed, system_ready, verified, f"{gpu.name}{vram} · {suffix}")


def nvidia_acceleration_ready(
    root: Path | None = None,
    *,
    min_vram_gb: float = NVIDIA_TURBO_MIN_VRAM_GB,
) -> bool:
    """Return whether automatic CUDA selection is safe for a large model."""
    status = acceleration_status(root)
    return bool(
        status.verified
        and status.gpu is not None
        and status.gpu.memory_gb is not None
        and status.gpu.memory_gb >= min_vram_gb - NVIDIA_VRAM_REPORTING_TOLERANCE_GB
    )


def install_nvidia_runtime(*, root: Path | None = None, progress_callback: ProgressCallback | None = None) -> Path:
    if os.name != "nt":
        raise RuntimeError("NVIDIA speech acceleration setup is available on Windows only.")
    if nvidia_gpu() is None:
        raise RuntimeError("No NVIDIA GPU detected. Winsper can continue in CPU mode.")
    destination = runtime_root(root)
    base = destination.parent
    downloads = base / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    total = runtime_size_bytes()
    completed = 0
    archives: list[Path] = []
    for asset in CUDA12_ASSETS:
        archive = downloads / asset.filename
        _download(asset, archive, completed, total, progress_callback)
        archives.append(archive)
        completed += asset.size_bytes

    staging = base / f".{CUDA12_RUNTIME_ID}.{uuid.uuid4().hex}.installing"
    backup = base / f".{CUDA12_RUNTIME_ID}.{uuid.uuid4().hex}.backup"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        for archive in archives:
            _safe_extract(archive, staging)
        missing = [name for name in REQUIRED_DLLS if not _find_dll(staging, name)]
        if missing:
            raise RuntimeError(f"Downloaded NVIDIA runtime is incomplete: {', '.join(missing)}")
        atomic_write_json(staging / "installation.json", {"id": CUDA12_RUNTIME_ID, "assets": [asset.sha256 for asset in CUDA12_ASSETS]})
        if destination.exists():
            _replace_with_retry(destination, backup)
        _replace_with_retry(staging, destination)
        shutil.rmtree(backup, ignore_errors=True)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not destination.exists():
            _replace_with_retry(backup, destination)
        raise
    _emit(progress_callback, RuntimeProgress("NVIDIA runtime installed", total, total))
    return destination


def activate_managed_runtime(root: Path | None = None) -> bool:
    """Make app-local CUDA DLLs visible before CTranslate2 loads."""
    directory = runtime_root(root)
    if os.name != "nt" or not runtime_is_installed(root):
        return False
    directories = sorted({_find_dll(directory, name).parent for name in REQUIRED_DLLS if _find_dll(directory, name)})
    values = [str(path) for path in directories]
    with _dll_directory_lock:
        path_values = [value for value in os.environ.get("PATH", "").split(os.pathsep) if value]
        known_path_values = {_normalized_path(value) for value in path_values}
        missing_values = [value for value in values if _normalized_path(value) not in known_path_values]
        if missing_values:
            os.environ["PATH"] = os.pathsep.join([*missing_values, *path_values])
        for value in values:
            key = _normalized_path(value)
            if key in _activated_runtime_directories:
                continue
            _dll_handles.append(os.add_dll_directory(value))
            _activated_runtime_directories.add(key)
    return True


def verify_nvidia_runtime(model: str, *, root: Path | None = None) -> AccelerationStatus:
    """Real CUDA model load + short decode. Never accepts CPU fallback as success."""
    activate_managed_runtime(root)
    gpu = nvidia_gpu()
    if gpu is None:
        return acceleration_status(root)
    try:
        import numpy as np
        from faster_whisper import WhisperModel
        from .models import find_speech_model, installed_status

        preset = find_speech_model(model)
        installed = installed_status(preset, include_size=False) if preset is not None else None
        if installed is None or not installed.installed or installed.cache_path is None:
            raise RuntimeError("Download the selected Whisper model before verifying GPU acceleration.")
        instance = WhisperModel(str(installed.cache_path), device="cuda", compute_type="float16")
        segments, _info = instance.transcribe(np.zeros(16_000, dtype="float32"), beam_size=1)
        list(segments)
    except Exception as exc:
        return AccelerationStatus(gpu, runtime_is_installed(root), system_runtime_available(), False, f"GPU verification failed: {exc}")
    marker = _verification_path(root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(marker, {"id": CUDA12_RUNTIME_ID, "gpu": gpu.name, "model": model})
    return acceleration_status(root)


def _download(asset: RuntimeAsset, target: Path, completed: int, total: int, callback: ProgressCallback | None) -> None:
    if target.is_file() and target.stat().st_size == asset.size_bytes and _sha256(target) == asset.sha256:
        _emit(callback, RuntimeProgress(f"Verified {asset.filename}", completed + asset.size_bytes, total))
        return
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(asset.url, timeout=30) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                _emit(callback, RuntimeProgress(f"Downloading {asset.filename}", completed + output.tell(), total))
        if partial.stat().st_size != asset.size_bytes or _sha256(partial) != asset.sha256:
            raise RuntimeError(f"Integrity check failed for {asset.filename}.")
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _safe_extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        root = destination.resolve()
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError("NVIDIA runtime archive contains an unsafe path.")
        bundle.extractall(destination)


def _find_dll(directory: Path, filename: str) -> Path | None:
    return next((path for path in directory.rglob(filename) if path.is_file()), None)


def _normalized_gpu_name(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _normalized_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _emit(callback: ProgressCallback | None, value: RuntimeProgress) -> None:
    if callback is not None:
        callback(value)
