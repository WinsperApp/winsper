from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ai_catalog import (
    LEGACY_POLISH_MODEL_ARTIFACTS,
    LLAMA_CPP_VERSION,
    PolishModel,
    RuntimeAsset,
    RuntimeBundle,
    local_ai_root,
    polish_model_path,
    runtime_candidates,
)
from .ai_hardware import AIHardware
from .ai_ollama_reuse import (
    embedded_model_for_ollama_reference as embedded_model_for_ollama_reference,
    has_gguf_magic as _has_gguf_magic,
    ollama_model_candidate as ollama_model_candidate,
    ollama_model_reference,
    reusable_ollama_model as reusable_ollama_model,
    sha256 as _sha256,
)
from .storage import atomic_write_json, remove_stale_download_parts


@dataclass(frozen=True)
class RuntimeProgress:
    bundle_id: str
    status: str
    downloaded_bytes: int = 0
    total_bytes: int = 0

    @property
    def percent(self) -> int | None:
        if self.total_bytes <= 0:
            return None
        return min(100, int(self.downloaded_bytes * 100 / self.total_bytes))


@dataclass(frozen=True)
class RuntimeInstallation:
    bundle: RuntimeBundle
    directory: Path
    executable: Path
    device: str = ""
    device_name: str = ""


@dataclass(frozen=True)
class RuntimeProbe:
    ready: bool
    version: str
    devices: tuple[tuple[str, str], ...]
    error: str = ""


ProgressCallback = Callable[[RuntimeProgress], None]
DOWNLOAD_SPACE_RESERVE_BYTES = 256 * 1024 * 1024
_runtime_probe_cache: dict[tuple[str, int, int], RuntimeProbe] = {}
_runtime_probe_cache_lock = threading.Lock()


def runtime_directory(bundle: RuntimeBundle, root: Path | None = None) -> Path:
    return (root or local_ai_root()) / "runtime" / LLAMA_CPP_VERSION / bundle.id


def runtime_executable(bundle: RuntimeBundle, root: Path | None = None) -> Path:
    return runtime_directory(bundle, root) / "llama-server.exe"


def runtime_is_installed(bundle: RuntimeBundle, root: Path | None = None) -> bool:
    directory = runtime_directory(bundle, root)
    executable = directory / "llama-server.exe"
    marker = directory / "installation.json"
    if not executable.is_file() or not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("bundle_id") == bundle.id
        and payload.get("runtime_version") == LLAMA_CPP_VERSION
        and payload.get("assets") == [asset.sha256 for asset in bundle.assets]
    )


def install_runtime(
    bundle: RuntimeBundle,
    *,
    root: Path | None = None,
    progress_callback: ProgressCallback | None = None,
    pause_event: threading.Event | None = None,
    cancel_event: threading.Event | None = None,
) -> RuntimeInstallation:
    base = (root or local_ai_root()).resolve()
    downloads = base / "downloads"
    destination = runtime_directory(bundle, base)
    downloads.mkdir(parents=True, exist_ok=True)
    remove_stale_download_parts(downloads, suffixes=(".part",))
    destination.parent.mkdir(parents=True, exist_ok=True)
    archives: list[Path] = []
    total_bytes = sum(asset.size_bytes for asset in bundle.assets)
    completed_before = 0
    try:
        for asset in bundle.assets:
            archive = downloads / asset.filename
            _download_asset(
                bundle.id,
                asset,
                archive,
                completed_before=completed_before,
                total_bytes=total_bytes,
                progress_callback=progress_callback,
                pause_event=pause_event,
                cancel_event=cancel_event,
            )
            archives.append(archive)
            completed_before += asset.size_bytes
    except BaseException:
        if cancel_event is not None and cancel_event.is_set():
            for asset in bundle.assets:
                archive = downloads / asset.filename
                archive.unlink(missing_ok=True)
                archive.with_suffix(archive.suffix + ".part").unlink(missing_ok=True)
        raise

    staging = destination.parent / f".{bundle.id}.{uuid.uuid4().hex}.installing"
    backup = destination.parent / f".{bundle.id}.{uuid.uuid4().hex}.backup"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        for archive in archives:
            _safe_extract_zip(archive, staging)
        executable = staging / "llama-server.exe"
        if not executable.is_file():
            raise RuntimeError(f"{bundle.id} archive does not contain llama-server.exe")
        for extra_executable in staging.glob("*.exe"):
            if extra_executable.name.casefold() != "llama-server.exe":
                extra_executable.unlink()
        atomic_write_json(
            staging / "installation.json",
            {
                "bundle_id": bundle.id,
                "runtime_version": LLAMA_CPP_VERSION,
                "assets": [asset.sha256 for asset in bundle.assets],
            },
        )
        if destination.exists():
            destination.replace(backup)
        staging.replace(destination)
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    for archive in archives:
        archive.unlink(missing_ok=True)
    _clear_runtime_probe_cache(destination / "llama-server.exe")
    _emit(progress_callback, RuntimeProgress(bundle.id, "Installed", total_bytes, total_bytes))
    return RuntimeInstallation(bundle, destination, destination / "llama-server.exe")


def model_is_installed(model: PolishModel, root: Path | None = None) -> bool:
    path = polish_model_path(model, root)
    marker = path.parent / "installation.json"
    if not path.is_file() or not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("model_id") != model.id:
        return False
    if payload.get("source") == "ollama":
        reference = ollama_model_reference(model.id)
        source_size = payload.get("source_size")
        digest = str(payload.get("sha256") or "")
        try:
            actual_size = path.stat().st_size
            accepted = {(model.size_bytes, model.sha256), LEGACY_POLISH_MODEL_ARTIFACTS.get(model.id)}
            return bool(
                reference
                and payload.get("ollama_reference") == reference
                and source_size == actual_size
                and (actual_size, digest) in accepted
                and _has_gguf_magic(path)
            )
        except OSError:
            return False
    try:
        return path.stat().st_size == model.size_bytes and payload.get("sha256") == model.sha256
    except OSError:
        return False


def install_polish_model(
    model: PolishModel,
    *,
    root: Path | None = None,
    progress_callback: ProgressCallback | None = None,
    pause_event: threading.Event | None = None,
    cancel_event: threading.Event | None = None,
    reuse_ollama: bool = True,
    ollama_root: Path | None = None,
) -> Path:
    if reuse_ollama:
        reusable = reusable_ollama_model(model, ollama_root=ollama_root)
        if reusable is not None:
            source, digest, reference = reusable
            try:
                return _adopt_ollama_model(
                    model,
                    source,
                    digest,
                    reference,
                    root=root,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                )
            except OSError:
                # Cross-volume links or locked files must not block the pinned,
                # managed download path.
                pass
    if not model.url or not model.sha256:
        raise RuntimeError(f"{model.label} is benchmark-only and has no pinned release artifact yet.")
    path = polish_model_path(model, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    remove_stale_download_parts(path.parent, suffixes=(".part",))
    asset = RuntimeAsset(model.filename, model.url, model.sha256, model.size_bytes)
    _download_asset(
        model.id,
        asset,
        path,
        completed_before=0,
        total_bytes=model.size_bytes,
        progress_callback=progress_callback,
        pause_event=pause_event,
        cancel_event=cancel_event,
    )
    atomic_write_json(
        path.parent / "installation.json",
        {
            "model_id": model.id,
            "sha256": model.sha256,
            "license": model.license,
            "min_runtime": model.min_runtime,
        },
    )
    return path


def _adopt_ollama_model(
    model: PolishModel,
    source: Path,
    digest: str,
    reference: str,
    *,
    root: Path | None,
    progress_callback: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> Path:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Download cancelled.")
    path = polish_model_path(model, root)
    destination = path.parent
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{model.id}.{uuid.uuid4().hex}.installing"
    backup = destination.parent / f".{model.id}.{uuid.uuid4().hex}.backup"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        _emit(
            progress_callback,
            RuntimeProgress(model.id, "Reusing an existing local model", 0, source.stat().st_size),
        )
        os.link(source, staging / model.filename)
        atomic_write_json(
            staging / "installation.json",
            {
                "model_id": model.id,
                "sha256": digest,
                "source": "ollama",
                "ollama_reference": reference,
                "source_size": source.stat().st_size,
                "license": model.license,
                "min_runtime": model.min_runtime,
            },
        )
        if destination.exists():
            destination.replace(backup)
        staging.replace(destination)
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    _emit(
        progress_callback,
        RuntimeProgress(
            model.id,
            "Existing local model ready",
            source.stat().st_size,
            source.stat().st_size,
        ),
    )
    return path


def uninstall_polish_model(model: PolishModel, *, root: Path | None = None) -> None:
    base = (root or local_ai_root()).resolve()
    target = polish_model_path(model, base).parent.resolve()
    if target == base or base not in target.parents:
        raise RuntimeError(f"Refusing to remove model outside local AI root: {target}")
    if target.exists():
        shutil.rmtree(target)


def uninstall_runtime(bundle: RuntimeBundle, *, root: Path | None = None) -> None:
    base = (root or local_ai_root()).resolve()
    target = runtime_directory(bundle, base).resolve()
    if target == base or base not in target.parents:
        raise RuntimeError(f"Refusing to remove runtime outside local AI root: {target}")
    _clear_runtime_probe_cache(target / "llama-server.exe")
    if target.exists():
        shutil.rmtree(target)
    downloads = (base / "downloads").resolve()
    if downloads != base and base in downloads.parents:
        for asset in bundle.assets:
            (downloads / asset.filename).unlink(missing_ok=True)


def installed_runtime_candidates(
    hardware: AIHardware,
    *,
    root: Path | None = None,
) -> list[RuntimeInstallation]:
    result: list[RuntimeInstallation] = []
    for bundle in runtime_candidates(hardware):
        if not runtime_is_installed(bundle, root):
            continue
        executable = runtime_executable(bundle, root)
        probe = probe_runtime(executable)
        if not runtime_probe_supports_bundle(bundle, probe):
            continue
        device, device_name = select_runtime_device_entry(bundle, probe, hardware)
        result.append(
            RuntimeInstallation(
                bundle=bundle,
                directory=executable.parent,
                executable=executable,
                device=device,
                device_name=device_name,
            )
        )
    return result


def runtime_probe_supports_bundle(bundle: RuntimeBundle, probe: RuntimeProbe) -> bool:
    if not probe.ready:
        return False
    if bundle.backend == "cpu":
        return True
    prefix = "cuda" if bundle.backend == "cuda" else "vulkan"
    return any(device.casefold().startswith(prefix) for device, _name in probe.devices)


def probe_runtime(executable: Path, timeout_seconds: float = 10) -> RuntimeProbe:
    try:
        resolved = executable.resolve(strict=True)
        stat = resolved.stat()
    except OSError as exc:
        return RuntimeProbe(False, "", (), str(exc))
    key = (os.path.normcase(str(resolved)), stat.st_size, stat.st_mtime_ns)
    with _runtime_probe_cache_lock:
        cached = _runtime_probe_cache.get(key)
        if cached is not None:
            return cached
        stale_keys = [candidate for candidate in _runtime_probe_cache if candidate[0] == key[0]]
        for stale_key in stale_keys:
            _runtime_probe_cache.pop(stale_key, None)
    try:
        version = _run_runtime(resolved, ["--version"], timeout_seconds)
        devices_output = _run_runtime(resolved, ["--list-devices"], timeout_seconds)
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        return RuntimeProbe(False, "", (), str(exc))
    devices: list[tuple[str, str]] = []
    for raw_line in devices_output.splitlines():
        line = raw_line.strip()
        if ":" not in line or line.casefold().startswith("available devices"):
            continue
        device, name = line.split(":", 1)
        if device.strip():
            devices.append((device.strip(), name.strip().split(" (", 1)[0]))
    probe = RuntimeProbe(True, version.strip(), tuple(devices))
    with _runtime_probe_cache_lock:
        _runtime_probe_cache[key] = probe
    return probe


def select_runtime_device(bundle: RuntimeBundle, probe: RuntimeProbe, hardware: AIHardware) -> str:
    return select_runtime_device_entry(bundle, probe, hardware)[0]


def select_runtime_device_entry(
    bundle: RuntimeBundle,
    probe: RuntimeProbe,
    hardware: AIHardware,
) -> tuple[str, str]:
    if bundle.backend == "cpu":
        return "", ""
    if bundle.backend == "cuda":
        return next(
            ((device, name) for device, name in probe.devices if device.casefold().startswith("cuda")),
            ("CUDA0", ""),
        )
    preferred_names = [gpu.name.casefold() for gpu in hardware.gpus]
    for preferred in preferred_names:
        for device, name in probe.devices:
            normalized = name.casefold()
            if preferred in normalized or normalized in preferred:
                return device, name
    return probe.devices[0] if probe.devices else ("", "")


def _clear_runtime_probe_cache(executable: Path) -> None:
    key = os.path.normcase(str(executable.resolve()))
    with _runtime_probe_cache_lock:
        stale_keys = [candidate for candidate in _runtime_probe_cache if candidate[0] == key]
        for stale_key in stale_keys:
            _runtime_probe_cache.pop(stale_key, None)


def _run_runtime(executable: Path, arguments: list[str], timeout_seconds: float) -> str:
    completed = subprocess.run(
        [str(executable), *arguments],
        cwd=str(executable.parent),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    if completed.returncode:
        raise RuntimeError(output[-500:] or f"{executable.name} exited with {completed.returncode}")
    return output


def _download_asset(
    item_id: str,
    asset: RuntimeAsset,
    destination: Path,
    *,
    completed_before: int,
    total_bytes: int,
    progress_callback: ProgressCallback | None,
    pause_event: threading.Event | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    partial = destination.with_suffix(destination.suffix + ".part")

    def discard_partial() -> None:
        partial.unlink(missing_ok=True)

    _wait_for_download_control(pause_event, cancel_event, discard_partial)
    if destination.is_file() and destination.stat().st_size == asset.size_bytes:
        if _sha256(destination) == asset.sha256:
            _emit(
                progress_callback,
                RuntimeProgress(item_id, f"Verified {asset.filename}", completed_before + asset.size_bytes, total_bytes),
            )
            return
        destination.unlink()
    downloaded = partial.stat().st_size if partial.exists() else 0
    if downloaded > asset.size_bytes:
        partial.unlink()
        downloaded = 0
    _ensure_download_space(destination, asset.size_bytes - downloaded)
    headers = {"User-Agent": "Winsper/0.2"}
    if downloaded:
        headers["Range"] = f"bytes={downloaded}-"
    request = urllib.request.Request(asset.url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=30)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not download {asset.filename}: {exc}") from exc
    with response:
        if downloaded and getattr(response, "status", 200) != 206:
            downloaded = 0
            partial.unlink(missing_ok=True)
        mode = "ab" if downloaded else "wb"
        with partial.open(mode) as handle:
            while True:
                _wait_for_download_control(pause_event, cancel_event, discard_partial)
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                _emit(
                    progress_callback,
                    RuntimeProgress(
                        item_id,
                        # RuntimeProgress uses bundle_id for compatibility; model IDs are accepted too.
                        f"Downloading {asset.filename}",
                        completed_before + downloaded,
                        total_bytes,
                    ),
                )
            handle.flush()
            os.fsync(handle.fileno())
    if partial.stat().st_size != asset.size_bytes:
        raise RuntimeError(f"Incomplete runtime download for {asset.filename}: {partial.stat().st_size} of {asset.size_bytes} bytes")
    _wait_for_download_control(pause_event, cancel_event, discard_partial)
    digest = _sha256(partial)
    _wait_for_download_control(pause_event, cancel_event, discard_partial)
    if digest != asset.sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 verification failed for {asset.filename}")
    os.replace(partial, destination)


def _wait_for_download_control(
    pause_event: threading.Event | None,
    cancel_event: threading.Event | None,
    cancel_cleanup: Callable[[], None] | None = None,
) -> None:
    """Pause between streamed chunks while keeping Cancel responsive."""

    def raise_cancelled() -> None:
        if cancel_cleanup is not None:
            cancel_cleanup()
        raise RuntimeError("Runtime download cancelled.")

    if cancel_event is not None and cancel_event.is_set():
        raise_cancelled()
    while pause_event is not None and pause_event.is_set():
        if cancel_event is not None and cancel_event.wait(0.05):
            raise_cancelled()
        time.sleep(0.01)
    if cancel_event is not None and cancel_event.is_set():
        raise_cancelled()


def _ensure_download_space(destination: Path, remaining_bytes: int) -> None:
    """Fail before transfer when the target drive cannot finish safely."""
    required = max(0, remaining_bytes) + DOWNLOAD_SPACE_RESERVE_BYTES
    try:
        free = shutil.disk_usage(destination.parent).free
    except OSError:
        return
    if free < required:
        needed_gb = required / (1024**3)
        free_gb = free / (1024**3)
        raise RuntimeError(f"Not enough free disk space for this download: {needed_gb:.1f} GB needed, {free_gb:.1f} GB available.")


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (destination / member.filename).resolve()
            if target != destination and destination not in target.parents:
                raise RuntimeError(f"Unsafe path in {archive.name}: {member.filename}")
        package.extractall(destination)


def _emit(callback: ProgressCallback | None, progress: RuntimeProgress) -> None:
    if callback is not None:
        callback(progress)
