from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .ollama import DEFAULT_OLLAMA_MODELS


ONBOARDING_VERSION = 2

# Rounded cache-size estimates for informed approval before network access.
# Exact bytes replace these estimates as soon as the downloader has a plan.
SPEECH_DOWNLOAD_ESTIMATES_MB: dict[str, int] = {
    "tiny": 75,
    "tiny.en": 75,
    "base": 150,
    "base.en": 150,
    "small": 500,
    "small.en": 500,
    "medium": 1_500,
    "medium.en": 1_500,
    "large-v3": 3_100,
    "large-v3-turbo": 1_700,
    "turbo": 1_700,
    "distil-small.en": 350,
    "distil-medium.en": 900,
    "distil-large-v3": 1_600,
    "parakeet-tdt-0.6b-v2-int8": 650,
    "parakeet-tdt-0.6b-v3-int8": 650,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_approximate_size(size_mb: int) -> str:
    if size_mb >= 1_000:
        return f"about {size_mb / 1_000:.1f} GB"
    return f"about {size_mb} MB"


def speech_download_description(model: str, *, cache_root: Path | None = None) -> tuple[str, bool]:
    """Return honest pre-download size copy and a conservative disk check."""
    size_mb = SPEECH_DOWNLOAD_ESTIMATES_MB.get(model, 0)
    size_copy = format_approximate_size(size_mb) if size_mb else "a one-time download"
    try:
        free_mb = shutil.disk_usage(cache_root or Path.home()).free / (1024 * 1024)
    except OSError:
        return size_copy, True
    enough_space = not size_mb or free_mb >= max(size_mb * 1.25, size_mb + 250)
    return size_copy, enough_space


def friendly_setup_error(exc: BaseException) -> str:
    text = str(exc).strip()
    lowered = text.lower()
    if not text:
        return "Try again."
    if "microphone" in lowered or "audio" in lowered or "input device" in lowered:
        return "Check Windows microphone permission, then try again or choose another microphone."
    if "disk" in lowered or "space" in lowered:
        return "Free some disk space, then try again."
    if any(word in lowered for word in ("network", "internet", "download", "timed out", "timeout")):
        return "Check your internet connection, then try the download again."
    if "model" in lowered or "runtime" in lowered:
        return "Local support could not be prepared. Try again; Dictation remains available."
    if "cuda" in lowered or "cublas" in lowered or "cudnn" in lowered:
        return "Graphics acceleration is unavailable. Winsper will use the processor instead."
    if "hotkey" in lowered or "keyboard" in lowered:
        return "Try a different hotkey after setup."
    if any(
        marker in lowered
        for marker in (
            "onboardingtestsmixin",
            "traceback (most recent call last)",
            "voicepilot/onboarding_",
            "voicepilot\\onboarding_",
        )
    ):
        return "Something interrupted the test. Try again."
    return text[:160]


def ollama_combo_values(installed: tuple[str, ...] | list[str], current: str = "") -> list[str]:
    values: list[str] = []
    for model in [*installed, current, *DEFAULT_OLLAMA_MODELS]:
        model = (model or "").strip()
        if model and model not in values:
            values.append(model)
    return values or [DEFAULT_OLLAMA_MODELS[0]]


def model_matches(requested: str, candidate: str) -> bool:
    requested = (requested or "").strip()
    candidate = (candidate or "").strip()
    if not requested or not candidate:
        return False
    return candidate == requested or (":" not in requested and candidate.split(":", 1)[0] == requested)
