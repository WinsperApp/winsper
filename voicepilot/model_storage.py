from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

from .model_progress import (
    _emit_progress,
    _file_progress_tqdm_class,
    _progress_tqdm_class,
    _short_filename,
    _silent_tqdm_class,
)
from .speech_model_catalog import (
    DownloadProgress,
    DownloadProgressCallback,
    InstalledModel,
    QUICK_SETUP_SAFE_MODELS,
    QUICK_SETUP_TEST_MODEL,
    SPEECH_MODEL_PRESETS,
    SpeechModelPreset,
    find_speech_model,
)
from .storage import remove_download_parts, remove_stale_download_parts

WINSPER_MODEL_STORAGE_ENV = "WINSPER_MODEL_STORAGE"


def configure_model_storage(path: str | Path | None) -> None:
    """Select Winsper's shared model root for this process and its workers."""
    value = str(path or "").strip()
    if value:
        os.environ[WINSPER_MODEL_STORAGE_ENV] = str(Path(value).expanduser().resolve())
    else:
        os.environ.pop(WINSPER_MODEL_STORAGE_ENV, None)


def configured_model_storage_root() -> Path | None:
    value = os.environ.get(WINSPER_MODEL_STORAGE_ENV, "").strip()
    return Path(value).expanduser() if value else None


def model_storage_display_root() -> Path:
    """Return the folder shown in Settings for the current storage policy."""
    configured = configured_model_storage_root()
    if configured is not None:
        return configured
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return (Path(base) / "Winsper" if base else Path.home() / ".winsper") / "models"


def copy_models_to_storage(
    destination: Path,
    *,
    speech_source: Path | None = None,
    polish_source: Path | None = None,
) -> int:
    """Copy Winsper-owned models into a new shared root without deleting sources.

    Source deletion is intentionally avoided: a loaded native model may still
    hold files open on Windows. Copy-first keeps the running app healthy and
    makes changing the location reversible.
    """
    target = destination.expanduser().resolve()
    return copy_models_between_locations(
        speech_source=(speech_source or huggingface_cache_root()).resolve(),
        speech_destination=target / "speech",
        polish_source=polish_source.resolve() if polish_source is not None else None,
        polish_destination=target / "polish",
    )


def copy_models_between_locations(
    *,
    speech_source: Path,
    speech_destination: Path,
    polish_source: Path | None,
    polish_destination: Path,
) -> int:
    """Copy known speech and Polish models between two storage policies."""
    speech_root = speech_source.expanduser().resolve()
    speech_target = speech_destination.expanduser().resolve()
    polish_root = polish_source.expanduser().resolve() if polish_source is not None else None
    polish_target = polish_destination.expanduser().resolve()
    for source_root, destination_root in (
        (speech_root, speech_target),
        (polish_root, polish_target),
    ):
        if source_root is None or source_root == destination_root:
            continue
        if destination_root.is_relative_to(source_root) or source_root.is_relative_to(destination_root):
            raise ValueError("Choose a folder outside the current model folders.")

    copied = 0
    for preset in SPEECH_MODEL_PRESETS:
        source = speech_root / cache_dir_name(preset.repo_id)
        if not source.is_dir():
            continue
        speech_target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, speech_target / source.name, dirs_exist_ok=True)
        copied += 1

    if polish_root is not None:
        source_models = polish_root / "models"
        if source_models.is_dir():
            shutil.copytree(source_models, polish_target / "models", dirs_exist_ok=True)
            copied += sum(1 for child in source_models.iterdir() if child.is_dir())
    return copied


def list_installed_models(cache_root: Path | None = None, include_sizes: bool = True) -> list[InstalledModel]:
    return [
        installed_status(preset, cache_root, include_size=include_sizes)
        for preset in SPEECH_MODEL_PRESETS
    ]


def installed_status(preset: SpeechModelPreset, cache_root: Path | None = None, include_size: bool = True) -> InstalledModel:
    path = find_cached_model_path(preset.repo_id, cache_root)
    if path is not None and not model_path_is_complete(path, preset.engine):
        path = None
    return InstalledModel(
        preset=preset,
        installed=path is not None,
        cache_path=path,
        size_mb=directory_size_mb(path) if include_size and path is not None else None,
    )


def model_path_is_complete(path: Path, engine: str) -> bool:
    if engine == "sherpa_onnx":
        return all((path / name).exists() for name in ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"))
    return (path / "model.bin").exists() and (path / "config.json").exists()


def quick_setup_model_for(selected_model: str, cache_root: Path | None = None) -> str:
    model = (selected_model or "").strip()
    if not model or model in QUICK_SETUP_SAFE_MODELS:
        return model
    preset = find_speech_model(model)
    if preset is None:
        return model
    if installed_status(preset, cache_root=cache_root, include_size=False).installed:
        return model
    return QUICK_SETUP_TEST_MODEL


def huggingface_cache_root() -> Path:
    """Return the speech-model cache owned by this Winsper installation.

    Explicit Hugging Face environment overrides remain available for developers
    and managed deployments. Source checkouts retain Hugging Face's conventional
    cache so existing development models are not copied or downloaded again.
    """
    configured = configured_model_storage_root()
    if configured is not None:
        return configured / "speech"
    return default_huggingface_cache_root()


def default_huggingface_cache_root() -> Path:
    """Return one stable speech cache for source and packaged Winsper."""
    explicit = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if explicit:
        return Path(explicit)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    app_data = Path(base) / "Winsper" if base else Path.home() / ".winsper"
    return app_data / "models" / "huggingface" / "hub"


def find_cached_repo(repo_id: str, cache_root: Path | None = None) -> Path | None:
    slug = cache_dir_name(repo_id).lower()
    roots = [cache_root] if cache_root is not None else speech_cache_roots()
    for root in roots:
        exact = root / cache_dir_name(repo_id)
        if exact.exists():
            return exact
        if not root.exists():
            continue
        for child in root.iterdir():
            if child.is_dir() and child.name.lower() == slug:
                return child
    return None


def speech_cache_roots() -> tuple[Path, ...]:
    """Return active cache plus source-run legacy cache for seamless upgrades."""
    active = huggingface_cache_root().resolve()
    if configured_model_storage_root() is not None or os.environ.get("HUGGINGFACE_HUB_CACHE") or os.environ.get("HF_HOME"):
        return (active,)
    legacy = (Path.home() / ".cache" / "huggingface" / "hub").resolve()
    return (active,) if legacy == active else (active, legacy)


def find_cached_model_path(repo_id: str, cache_root: Path | None = None) -> Path | None:
    repo_cache = find_cached_repo(repo_id, cache_root)
    if repo_cache is None:
        return None
    if any((repo_cache / name).exists() for name in ("tokens.txt", "encoder.int8.onnx")):
        return repo_cache
    snapshots = repo_cache / "snapshots"
    if not snapshots.exists():
        return repo_cache
    candidates = [path for path in snapshots.iterdir() if path.is_dir()]
    if not candidates:
        return repo_cache
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


class SpeechModelNotInstalled(RuntimeError):
    """Raised when runtime use is requested before model setup completes."""

    def __init__(self, model: str):
        self.model = model
        super().__init__(
            f"Speech model {model} is not installed. "
            "Download it from Settings > Dictation > Advanced."
        )


def resolve_model_path(preset: SpeechModelPreset) -> Path:
    """Return a complete local model without starting network work.

    Model downloads are an explicit Settings action. Dictation and Polish must
    never begin a large transfer from a hotkey-triggered runtime path.
    """
    cached = find_cached_model_path(preset.repo_id)
    if cached is not None and model_path_is_complete(cached, preset.engine):
        return cached
    raise SpeechModelNotInstalled(preset.model)


def cache_dir_name(repo_id: str) -> str:
    return "models--" + repo_id.replace("/", "--")


def directory_size_mb(path: Path | None) -> float | None:
    if path is None or not path.exists():
        return None
    total = 0
    for file_path in path.rglob("*"):
        try:
            if file_path.is_file():
                total += file_path.stat().st_size
        except OSError:
            continue
    return total / (1024 * 1024)


class ModelDownloadCancelled(RuntimeError):
    """Raised after a model download is intentionally cancelled."""


def download_model(
    model: str,
    progress_callback: DownloadProgressCallback | None = None,
    *,
    pause_event: threading.Event | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    preset = find_speech_model(model)
    cache_root = huggingface_cache_root()
    repo_cache = cache_root / cache_dir_name(preset.repo_id) if preset is not None else None
    was_installed = bool(
        preset is not None
        and installed_status(preset, cache_root=cache_root, include_size=False).installed
    )
    try:
        return _download_model(
            model,
            progress_callback,
            pause_event=pause_event,
            cancel_event=cancel_event,
        )
    except ModelDownloadCancelled:
        if repo_cache is not None:
            if was_installed:
                remove_download_parts(repo_cache, suffixes=(".incomplete",))
            elif repo_cache.exists():
                shutil.rmtree(repo_cache, ignore_errors=True)
        raise


def _download_model(
    model: str,
    progress_callback: DownloadProgressCallback | None = None,
    *,
    pause_event: threading.Event | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    preset = find_speech_model(model)
    if preset is None:
        raise RuntimeError(f"Unknown speech model: {model}")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    cache_root = huggingface_cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    remove_stale_download_parts(cache_root, suffixes=(".incomplete",))
    # hf-xet performs the transfer in native code and does not reliably call
    # Winsper's progress hook while a large file is in flight. Use the regular
    # streamed HTTP path so Pause and Cancel are cooperative and immediate.
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    try:
        from huggingface_hub import constants as huggingface_constants
        from huggingface_hub import hf_hub_download, snapshot_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required to download models. Re-run scripts/setup.ps1.") from exc
    huggingface_constants.HF_HUB_DISABLE_XET = True
    # Hugging Face defaults to 10 MiB chunks. A slow connection could then
    # delay a Pause or Cancel click for several seconds. Smaller chunks keep
    # controls responsive without materially affecting this one-time setup.
    huggingface_constants.DOWNLOAD_CHUNK_SIZE = 256 * 1024

    _emit_progress(
        progress_callback,
        DownloadProgress(model=preset.model, repo_id=preset.repo_id, status="Checking model files"),
    )
    _wait_for_download_control(pause_event, cancel_event)

    try:
        plan = snapshot_download(
            repo_id=preset.repo_id,
            revision=preset.revision,
            cache_dir=str(cache_root),
            dry_run=True,
            tqdm_class=_silent_tqdm_class(),
        )
    except TypeError:
        downloaded = snapshot_download(
            repo_id=preset.repo_id,
            revision=preset.revision,
            cache_dir=str(cache_root),
            tqdm_class=_progress_tqdm_class(preset, progress_callback),
        )
        return _complete_download(preset, Path(downloaded), progress_callback)

    pending = [info for info in plan if getattr(info, "will_download", True)]
    if not pending:
        downloaded = snapshot_download(
            repo_id=preset.repo_id,
            revision=preset.revision,
            cache_dir=str(cache_root),
            local_files_only=True,
            tqdm_class=_silent_tqdm_class(),
        )
        return _complete_download(preset, Path(downloaded), progress_callback)

    total_bytes = sum(max(0, int(getattr(info, "file_size", 0) or 0)) for info in pending)
    completed_bytes = 0
    _emit_progress(
        progress_callback,
        DownloadProgress(
            model=preset.model,
            repo_id=preset.repo_id,
            status=f"Downloading {len(pending)} files",
            downloaded_bytes=0,
            total_bytes=total_bytes,
        ),
    )
    revision = preset.revision
    for index, info in enumerate(pending, start=1):
        _wait_for_download_control(pause_event, cancel_event)
        filename = getattr(info, "filename", "")
        file_size = max(0, int(getattr(info, "file_size", 0) or 0))
        label = _short_filename(filename)
        _emit_progress(
            progress_callback,
            DownloadProgress(
                model=preset.model,
                repo_id=preset.repo_id,
                status=f"Downloading file {index}/{len(pending)}: {label}",
                downloaded_bytes=completed_bytes,
                total_bytes=total_bytes,
            ),
        )
        hf_hub_download(
            repo_id=preset.repo_id,
            cache_dir=str(cache_root),
            filename=filename,
            revision=revision,
            tqdm_class=_file_progress_tqdm_class(
                preset=preset,
                callback=progress_callback,
                completed_before=completed_bytes,
                total_bytes=total_bytes,
                file_size=file_size,
                status=f"Downloading file {index}/{len(pending)}: {label}",
                control_check=lambda: _wait_for_download_control(
                    pause_event,
                    cancel_event,
                ),
            ),
        )
        _wait_for_download_control(pause_event, cancel_event)
        completed_bytes = min(total_bytes, completed_bytes + file_size) if total_bytes > 0 else completed_bytes
        _emit_progress(
            progress_callback,
            DownloadProgress(
                model=preset.model,
                repo_id=preset.repo_id,
                status=f"Downloaded file {index}/{len(pending)}: {label}",
                downloaded_bytes=completed_bytes,
                total_bytes=total_bytes,
            ),
        )

    _wait_for_download_control(pause_event, cancel_event)
    downloaded = snapshot_download(
        repo_id=preset.repo_id,
        cache_dir=str(cache_root),
        revision=revision,
        local_files_only=True,
        tqdm_class=_silent_tqdm_class(),
    )
    return _complete_download(preset, Path(downloaded), progress_callback)


def _wait_for_download_control(
    pause_event: threading.Event | None,
    cancel_event: threading.Event | None,
) -> None:
    """Cooperatively pause a streamed transfer and wake promptly on cancel."""
    if cancel_event is not None and cancel_event.is_set():
        raise ModelDownloadCancelled("Model download cancelled.")
    while pause_event is not None and pause_event.is_set():
        if cancel_event is not None and cancel_event.wait(0.05):
            raise ModelDownloadCancelled("Model download cancelled.")
        time.sleep(0.01)
    if cancel_event is not None and cancel_event.is_set():
        raise ModelDownloadCancelled("Model download cancelled.")


def _complete_download(
    preset: SpeechModelPreset,
    downloaded: Path,
    progress_callback: DownloadProgressCallback | None = None,
) -> Path:
    size = directory_size_mb(Path(downloaded))
    total = int(size * 1024 * 1024) if size is not None else 1
    _emit_progress(
        progress_callback,
        DownloadProgress(
            model=preset.model,
            repo_id=preset.repo_id,
            status="Download complete",
            downloaded_bytes=total,
            total_bytes=total,
            done=True,
        ),
    )
    return downloaded
