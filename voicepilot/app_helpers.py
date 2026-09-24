from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from .audio import MicrophoneUnavailable
from .ai_catalog import polish_model
from .ai_runtime import model_is_installed
from .app_context import ForegroundContext
from .isolated_transcribe import SpeechResourceError, is_native_allocation_error
from .isolated_audio import AudioWorkerInterrupted
from .llama_server import LlamaServerModelMissing, LlamaServerUnavailable
from .model_storage import installed_status
from .models import (
    DownloadProgress,
    SpeechModelNotInstalled,
    find_speech_model,
    format_download_progress,
)
from .ollama import OllamaModelMissing
from .runtime_log import write_runtime_log
from .voice_commands import VoiceCommand

logger = logging.getLogger(__name__)


def startup_microphone_ready(recorder, config_path: Path) -> bool:
    """A missing or stalled input must not prevent Settings and hotkeys from opening."""
    try:
        return bool(recorder.warm_up())
    except (MicrophoneUnavailable, AudioWorkerInterrupted) as exc:
        log_runtime_error("microphone warm-up", exc, config_path)
        return False


def polish_setup_issue(config, speech_configs) -> tuple[str, str] | None:
    """Return a user-facing setup problem without starting network or model work."""
    checked_models: set[str] = set()
    for speech_config in speech_configs:
        model_name = str(getattr(speech_config, "model", "") or "").strip()
        if not model_name or model_name in checked_models:
            continue
        checked_models.add(model_name)
        preset = find_speech_model(model_name)
        if preset is not None and not installed_status(preset, include_size=False).installed:
            return (
                "Speech model required",
                f"Download {model_name} in Settings > Dictation > Advanced",
            )

    rewrite = config.rewrite
    provider = rewrite.provider.strip().lower()
    if provider == "ollama":
        if rewrite.model.strip():
            return None
    elif provider == "embedded":
        # A separately managed llama-server owns its model lifecycle.
        if rewrite.llama_server_url.strip():
            return None
        custom_path = os.path.expandvars(rewrite.llama_model_path.strip())
        if custom_path:
            if Path(custom_path).expanduser().is_file():
                return None
        elif rewrite.llama_model_id.strip():
            try:
                selected = polish_model(rewrite.llama_model_id.strip())
            except KeyError:
                selected = None
            if selected is not None and model_is_installed(selected):
                return None

    return (
        "Polish model required",
        "Download or select an AI model in Settings > Polish > Advanced",
    )


def _resolved_speech_status(base_status: str, requested_model: str, actual_model: str) -> str:
    """Explain language compatibility fallback without changing model selection."""
    if not requested_model or requested_model == actual_model:
        return base_status
    requested = find_speech_model(requested_model)
    requested_label = requested.label if requested is not None else requested_model
    return f"{base_status} · {requested_label} does not support the selected language"


def history_instruction(raw_instruction: str, command: VoiceCommand) -> str:
    if command.kind != "edit":
        return raw_instruction
    return f"{command.label}: {raw_instruction}\nCanonical: {command.instruction}"


def is_prompt_context(context: ForegroundContext) -> bool:
    label = f"{context.profile_name} {context.profile.label} {context.browser_label} {context.browser_domain} {context.hud_label}".lower()
    return any(token in label for token in ["prompt", "chatgpt", "claude", "gemini", "perplexity", "copilot"])


def local_ai_message(exc: RuntimeError) -> str:
    text = str(exc)
    if isinstance(exc, LlamaServerModelMissing):
        return text
    if isinstance(exc, LlamaServerUnavailable):
        return "Embedded Polish runtime is unavailable"
    if isinstance(exc, OllamaModelMissing):
        return text
    if "timed out" in text.lower():
        return "Ollama timed out"
    return "Start Ollama first"


def polish_fallback_message(exc: RuntimeError) -> str:
    if isinstance(exc, LlamaServerModelMissing):
        return "Embedded model missing; inserting Dictate transcript"
    if isinstance(exc, LlamaServerUnavailable):
        return "Embedded Polish unavailable; inserting Dictate transcript"
    if isinstance(exc, OllamaModelMissing):
        return "Model missing; inserting Dictate transcript"
    if "timed out" in str(exc).lower():
        return "Ollama timed out; inserting Dictate transcript"
    return "Start Ollama; inserting Dictate transcript"


def speech_progress_title(progress: DownloadProgress) -> str:
    status = progress.status.strip() or "Preparing speech"
    if progress.done:
        return "Model ready"
    if status.lower().startswith("downloading"):
        return f"Downloading {progress.model}"
    return status


def speech_progress_detail(progress: DownloadProgress) -> str:
    if progress.done:
        return progress.model
    if progress.total_bytes > 0:
        return format_download_progress(progress)
    return progress.model


def debug_logging_enabled() -> bool:
    value = os.environ.get("WINSPER_DEBUG", os.environ.get("VOICEPILOT_DEBUG", ""))
    return value.strip().lower() in {"1", "true", "yes", "on"}


def log_runtime_error(label: str, exc: BaseException, config_path: Path | None = None) -> None:
    if config_path is not None:
        write_runtime_log(config_path, label, str(exc), exc)
    if debug_logging_enabled():
        logger.error("Winsper %s error:", label, exc_info=exc)
        return
    logger.error("Winsper %s error: %s", label, exc)


def friendly_error_message(exc: BaseException) -> str:
    if isinstance(exc, SpeechModelNotInstalled):
        return (
            f"{exc.model} is not installed. "
            "Download it from Settings > Dictation > Advanced."
        )
    if isinstance(exc, LlamaServerModelMissing):
        return "Embedded Polish model is missing. Open Settings > Polish > Advanced."
    if isinstance(exc, LlamaServerUnavailable):
        return "Embedded Polish runtime is unavailable. Dictate still works."
    if isinstance(exc, SpeechResourceError) or is_native_allocation_error(exc):
        return "Not enough memory is available. Close large apps, free space on the Windows drive, then try again."
    text = str(exc).strip()
    lowered = text.lower()
    if not text:
        return "Nothing was inserted. Try again."
    if "ollama" in lowered:
        return "Local AI is unavailable. Dictate still works."
    missing_model = re.search(
        r"speech model\s+([^\s:]+)\s+is not installed",
        text,
        flags=re.IGNORECASE,
    )
    if missing_model is not None:
        return (
            f"{missing_model.group(1)} is not installed. "
            "Download it from Settings > Dictation > Advanced."
        )
    if "model" in lowered and ("missing" in lowered or "not found" in lowered):
        return "Speech model is missing. Open Settings > Dictation > Advanced."
    if "cuda" in lowered or "cublas" in lowered or "cudnn" in lowered:
        return "CUDA is unavailable. Winsper can use CPU/int8 instead."
    if "microphone" in lowered or "audio" in lowered or "input device" in lowered:
        return "Check the microphone in Settings."
    if "clipboard" in lowered or "paste" in lowered:
        return "Could not paste into the focused app."
    return text[:140]
