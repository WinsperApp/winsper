from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .corrections import corrections_path_for_config
from .history import history_path_for_config
from .models import huggingface_cache_root
from .autostart import startup_script_path
from .runtime_log import runtime_log_path_for_config
from .speed_lab import speed_lab_path_for_config
from .usage import usage_path_for_config


@dataclass(frozen=True)
class DataLocation:
    name: str
    path: Path
    description: str
    size_bytes: int | None

    @property
    def exists(self) -> bool:
        return self.path.exists()


def collect_data_locations(config: AppConfig, config_path: Path, include_model_cache_size: bool = False) -> list[DataLocation]:
    del config
    locations = [
        DataLocation(
            "Config",
            config_path,
            "Hotkeys, models, modes, snippets, profiles, and UI preferences.",
            path_size_bytes(config_path),
        ),
        DataLocation(
            "History",
            history_path_for_config(config_path),
            "Encrypted dictations, snippets, Polish outputs, and rewrites.",
            path_size_bytes(history_path_for_config(config_path)),
        ),
        DataLocation(
            "Corrections",
            corrections_path_for_config(config_path),
            "Local correction memory replacement rules.",
            path_size_bytes(corrections_path_for_config(config_path)),
        ),
        DataLocation(
            "Performance Data",
            speed_lab_path_for_config(config_path),
            "Local measurements used to choose speech performance presets.",
            path_size_bytes(speed_lab_path_for_config(config_path)),
        ),
        DataLocation(
            "Usage Stats",
            usage_path_for_config(config_path),
            "Local words dictated and estimated time saved.",
            path_size_bytes(usage_path_for_config(config_path)),
        ),
        DataLocation(
            "Runtime Log",
            runtime_log_path_for_config(config_path),
            "Recent local errors used for troubleshooting.",
            path_size_bytes(runtime_log_path_for_config(config_path)),
        ),
        DataLocation(
            "Startup Script",
            startup_script_path(),
            "Optional Start with Windows launcher script.",
            path_size_bytes(startup_script_path()),
        ),
    ]
    model_cache = huggingface_cache_root()
    locations.append(
        DataLocation(
            "Model Cache",
            model_cache,
            "Downloaded local speech model files from Hugging Face.",
            directory_size_bytes(model_cache) if include_model_cache_size else None,
        )
    )
    return locations


def privacy_report(config: AppConfig, config_path: Path, include_model_cache_size: bool = False) -> str:
    locations = collect_data_locations(config, config_path, include_model_cache_size=include_model_cache_size)
    lines = [
        "Winsper Privacy Report",
        "",
        "Local processing:",
        "- Audio is captured only for the current hotkey action and held in memory while it is processed.",
        "- Winsper does not write normal dictation audio to a temporary WAV file.",
        "- Speech-to-text uses local faster-whisper models, with optional local Parakeet models when installed.",
        "- Polish uses Winsper's embedded local AI by default; Ollama is optional when explicitly configured.",
        "- Browser awareness uses the active domain for routing; full browser URLs are not stored in history.",
        "- Winsper does not use a cloud API by default.",
        "",
        "Clipboard and history:",
        "- Winsper temporarily uses the Windows clipboard to read selected text and insert results.",
        "- When clipboard restoration is enabled, Winsper restores the prior clipboard after insertion when safe.",
        "- Successful dictations and Polish results are stored locally only when History is enabled, encrypted for the current Windows user.",
        "",
        "Network activity:",
        "- Polish models and runtimes use HTTPS and release-owned SHA-256 hashes; speech downloads use exact pinned repository revisions.",
        "- A custom remote model endpoint is used only when you explicitly configure it, and sends its inputs to that endpoint.",
        "- Update checks request the configured HTTPS release feed; installers require SHA-256 and a trusted Winsper signature.",
        "",
        "Diagnostics and crash reporting:",
        "- Diagnostics contain app/config status, model/runtime state, device names, and recent redacted errors.",
        "- Diagnostics do not intentionally include dictated or selected text and are not uploaded automatically.",
        "- Winsper has no automatic crash-report upload. A report leaves the PC only when the user chooses to share it.",
        "",
        "Local data:",
    ]
    for item in locations:
        size = "Not calculated" if item.size_bytes is None else format_bytes(item.size_bytes)
        lines.append(f"- {item.name}: {item.path} ({'exists' if item.exists else 'missing'}, {size})")
    return "\n".join(lines) + "\n"


def path_size_bytes(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return directory_size_bytes(path)
    except OSError:
        return 0
    return 0


def directory_size_bytes(path: Path, max_files: int = 100_000) -> int:
    if not path.exists():
        return 0
    total = 0
    count = 0
    for file_path in path.rglob("*"):
        if count >= max_files:
            break
        try:
            if file_path.is_file():
                total += file_path.stat().st_size
                count += 1
        except OSError:
            continue
    return total


def format_bytes(size: int | float | None) -> str:
    if size is None:
        return "Not calculated"
    value = float(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
