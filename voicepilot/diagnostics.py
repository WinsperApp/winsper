from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from .app_context import AppContextDetector
from .ai_catalog import LLAMA_CPP_VERSION, recommended_polish_model, runtime_candidates
from .ai_hardware import detect_ai_hardware
from .ai_runtime import installed_runtime_candidates, runtime_is_installed
from .autostart import is_start_with_windows_enabled, startup_script_path
from .config import AppConfig
from .corrections import CorrectionStore, corrections_path_for_config
from .history import history_path_for_config
from .models import (
    cuda_runtime_available,
    detect_hardware,
    engine_for_model,
    huggingface_cache_root,
    list_installed_models,
    recommended_model_for_hardware,
)
from .ollama import format_ollama_health
from .rewrite_backends import check_rewrite_backend_health
from .runtime_log import read_recent_runtime_log, runtime_log_path_for_config
from .system_audio import list_audio_devices
from .speed_lab import SpeedLabStore, result_summary, speed_lab_path_for_config
from .theme import resolve_theme
from .usage import format_minutes, usage_path_for_config, usage_summary


@dataclass(frozen=True)
class DiagnosticSection:
    title: str
    rows: tuple[tuple[str, str], ...]


def collect_diagnostics(config: AppConfig, config_path: Path, check_ollama: bool = True) -> list[DiagnosticSection]:
    hardware = detect_hardware()
    ai_hardware = detect_ai_hardware()
    ai_runtime_options = runtime_candidates(ai_hardware)
    ai_runtime_installed = installed_runtime_candidates(ai_hardware)
    ai_model = recommended_polish_model(ai_hardware)
    cuda_ready = hardware.has_nvidia and cuda_runtime_available()
    recommended = recommended_model_for_hardware(hardware)
    installed = list_installed_models(include_sizes=False)
    installed_names = [status.preset.model for status in installed if status.installed]
    context = AppContextDetector(config).detect()
    audio_devices = list_audio_devices()
    correction_store = CorrectionStore.for_config(
        config_path,
        max_rules=config.correction_memory.max_rules,
        enabled=config.correction_memory.enabled,
    )
    correction_count = len(correction_store.list())
    speed_store = SpeedLabStore.for_config(config_path)
    speed_latest = speed_store.latest_by_model()
    usage = usage_summary(config_path)

    rewrite_health = "Not checked"
    if check_ollama:
        try:
            health = check_rewrite_backend_health(config.rewrite)
            rewrite_health = (
                format_ollama_health(health)
                if config.rewrite.provider.lower() == "ollama"
                else f"{health.message}: {health.detail}".rstrip(": ")
            )
        except RuntimeError as exc:
            rewrite_health = str(exc)

    return [
        DiagnosticSection(
            "System",
            (
                ("Config path", str(config_path.resolve())),
                ("Config exists", "Yes" if config_path.exists() else "No"),
                ("Python", sys.executable),
                ("Python version", platform.python_version()),
                ("OS", platform.platform()),
                ("Theme", f"{config.hud.theme} (resolved {resolve_theme(config.hud.theme)})"),
            ),
        ),
        DiagnosticSection(
            "Hardware",
            (
                ("CPU", hardware.cpu or "Unknown"),
                ("RAM", f"{hardware.ram_gb:.1f} GB" if hardware.ram_gb is not None else "Unknown"),
                ("GPU", ", ".join(hardware.gpus) if hardware.gpus else "None detected"),
                (
                    "NVIDIA CUDA runtime",
                    "Ready" if cuda_ready else ("GPU detected, runtime missing" if hardware.has_nvidia else "Not detected"),
                ),
                ("Intel Arc hint", "Detected" if hardware.has_intel_arc else "Not detected"),
                ("Recommended STT", recommended.model),
            ),
        ),
        DiagnosticSection(
            "Speech",
            (
                ("Engine", config.speech.engine),
                ("Model", config.dictation.ramble_model),
                ("Model engine", engine_for_model(config.dictation.ramble_model, config.speech.engine)),
                ("Device / compute", f"{config.speech.device} / {config.speech.compute_type}"),
                ("Language", config.speech.language),
                ("Beam size", str(config.speech.beam_size)),
                ("VAD", "On" if config.speech.vad_filter else "Off"),
                ("Preload on startup", "On" if config.speech.preload_on_startup else "Off"),
                ("Installed models", ", ".join(installed_names) if installed_names else "None detected"),
                ("HF cache", str(huggingface_cache_root())),
                ("Correction memory", "On" if config.correction_memory.enabled else "Off"),
                ("Correction rules", str(correction_count)),
                ("Corrections path", str(corrections_path_for_config(config_path).resolve())),
                ("Performance data path", str(speed_lab_path_for_config(config_path).resolve())),
                ("Performance results", str(len(speed_store.list()))),
                ("Performance base.en", result_summary(speed_latest.get("base.en|cpu|int8"))),
                ("Performance small.en", result_summary(speed_latest.get("small.en|cpu|int8"))),
                ("Performance medium.en", result_summary(speed_latest.get("medium.en|cpu|int8"))),
                ("Performance Parakeet", result_summary(speed_latest.get("parakeet-tdt-0.6b-v2-int8|cpu|int8"))),
            ),
        ),
        DiagnosticSection(
            "Audio",
            (
                ("Input device", str(config.audio.input_device) if config.audio.input_device is not None else "Windows default"),
                ("Sample rate", str(config.audio.sample_rate)),
                ("Channels", str(config.audio.channels)),
                ("Input devices", "\n".join(audio_devices) if audio_devices else "No input devices found"),
            ),
        ),
        DiagnosticSection(
            "Hotkeys",
            (
                ("Dictate", config.hotkeys.dictate),
                ("Polish", config.hotkeys.polish),
                ("Cancel", config.hotkeys.cancel),
                ("Tap to toggle", "On" if config.hotkeys.tap_to_toggle_dictation else "Off"),
            ),
        ),
        DiagnosticSection(
            "Polish AI",
            (
                ("Provider", config.rewrite.provider),
                ("Hardware architecture", ai_hardware.architecture),
                ("Detected AI GPUs", ", ".join(gpu.name for gpu in ai_hardware.gpus) or "None"),
                ("Detected VRAM", f"{ai_hardware.best_vram_gb:.1f} GB" if ai_hardware.best_vram_gb is not None else "Unknown"),
                ("llama.cpp target", LLAMA_CPP_VERSION),
                ("Runtime priority", " -> ".join(bundle.id for bundle in ai_runtime_options) or "Unsupported architecture"),
                (
                    "Runtime installed",
                    ", ".join(item.bundle.id for item in ai_runtime_installed)
                    or ", ".join(f"{bundle.id}: {'yes' if runtime_is_installed(bundle) else 'no'}" for bundle in ai_runtime_options)
                    or "None",
                ),
                ("Temporary model recommendation", ai_model.label),
                ("Ollama URL", config.rewrite.ollama_url),
                ("llama-server URL", config.rewrite.llama_server_url or "Managed locally"),
                ("Backend status", rewrite_health),
                ("Model", config.rewrite.model),
                ("Polish enabled", "On" if config.dictation.polish_enabled else "Off"),
                ("Polish fallback", "On" if config.dictation.polish_fallback_to_ramble else "Off"),
                ("Polish voice commands", "Built in"),
                ("Spoken layout", "On" if config.spoken_formatting.enabled else "Off"),
                ("Spoken Enter", "On" if config.spoken_actions.enabled else "Off"),
                ("Spoken Enter phrase", config.spoken_actions.enter_phrase),
            ),
        ),
        DiagnosticSection(
            "App Context",
            (
                ("Profiles enabled", "On" if config.profiles.enabled else "Off"),
                ("Browser awareness", "On" if config.browser_context.enabled else "Off"),
                ("Browser processes", ", ".join(config.browser_context.browser_processes)),
                ("Foreground process", context.process_name or "Unknown"),
                ("Foreground title", context.window_title or "Unknown"),
                ("Browser domain", context.browser_domain or "Not detected"),
                ("Browser site", context.browser_label or "Not detected"),
                ("Site behavior", context.site_style.label if context.site_style else "None"),
                ("Matched profile", f"{context.profile_name} ({context.profile.label})"),
            ),
        ),
        DiagnosticSection(
            "Interface",
            (
                ("HUD", "On" if config.hud.enabled else "Off"),
                ("Tray", "On" if config.tray.enabled else "Off"),
                ("Start with Windows setting", "On" if config.startup.start_with_windows else "Off"),
                ("Start with Windows installed", "On" if is_start_with_windows_enabled(config_path) else "Off"),
                ("Startup script", str(startup_script_path())),
                ("History", "On" if config.history.enabled else "Off"),
                ("History max items", str(config.history.max_items)),
                ("History path", str(history_path_for_config(config_path).resolve())),
                ("Usage today", f"{usage.today_words} words, about {format_minutes(usage.today_minutes_saved)} saved"),
                ("Usage total", f"{usage.total_words} words, about {format_minutes(usage.total_minutes_saved)} saved"),
                ("Usage path", str(usage_path_for_config(config_path).resolve())),
                ("HUD opacity", str(config.hud.opacity)),
                ("Auto-hide seconds", str(config.hud.auto_hide_seconds)),
                ("Onboarding complete", "Yes" if config.onboarding.completed else "No"),
                ("Onboarding completed at", config.onboarding.completed_at or "Never"),
            ),
        ),
        DiagnosticSection(
            "Recent Runtime Log",
            (
                ("Log path", str(runtime_log_path_for_config(config_path).resolve())),
                ("Recent lines", read_recent_runtime_log(config_path)),
            ),
        ),
    ]


def format_diagnostics_report(sections: list[DiagnosticSection]) -> str:
    lines = ["Winsper Diagnostics", ""]
    for section in sections:
        lines.append(f"[{section.title}]")
        for key, value in section.rows:
            if "\n" in value:
                lines.append(f"{key}:")
                for item in value.splitlines():
                    lines.append(f"  {item}")
            else:
                lines.append(f"{key}: {value}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
