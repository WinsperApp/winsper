from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Callable

from .speech_languages import (
    PARAKEET_V3_LANGUAGES,
    model_supports_language,
)

@dataclass(frozen=True)
class SpeechModelPreset:
    model: str
    label: str
    repo_id: str
    revision: str
    tier: str
    best_for: str
    device_hint: str
    compute_hint: str
    notes: str
    engine: str = "faster_whisper"
    languages: tuple[str, ...] = ("en",)


@dataclass(frozen=True)
class InstalledModel:
    preset: SpeechModelPreset
    installed: bool
    cache_path: Path | None
    size_mb: float | None


@dataclass(frozen=True)
class HardwareSummary:
    cpu: str
    ram_gb: float | None
    gpus: tuple[str, ...]
    has_nvidia: bool
    has_intel_arc: bool

    @property
    def label(self) -> str:
        parts = [self.cpu]
        if self.ram_gb is not None:
            parts.append(f"{self.ram_gb:.1f} GB RAM")
        if self.gpus:
            parts.append(", ".join(self.gpus))
        return " | ".join(parts)


@dataclass(frozen=True)
class SpeechModelPolicy:
    """Evidence-shaped defaults for each product speech purpose."""

    dictation: SpeechModelPreset
    polish: SpeechModelPreset
    instruction: SpeechModelPreset
    speed_option: SpeechModelPreset


@dataclass(frozen=True)
class DownloadProgress:
    model: str
    repo_id: str
    status: str
    downloaded_bytes: int = 0
    total_bytes: int = 0
    done: bool = False

    @property
    def percent(self) -> int | None:
        if self.total_bytes <= 0 or (self.downloaded_bytes <= 0 and not self.done):
            return None
        if self.done or self.downloaded_bytes >= self.total_bytes:
            return 100
        return max(1, min(99, int((self.downloaded_bytes / self.total_bytes) * 100)))

    @property
    def remaining_bytes(self) -> int:
        if self.total_bytes <= 0:
            return 0
        return max(0, self.total_bytes - self.downloaded_bytes)


DownloadProgressCallback = Callable[[DownloadProgress], None]


MODEL_REPOS: dict[str, str] = {
    "tiny": "Systran/faster-whisper-tiny",
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base": "Systran/faster-whisper-base",
    "base.en": "Systran/faster-whisper-base.en",
    "small": "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "medium": "Systran/faster-whisper-medium",
    "medium.en": "Systran/faster-whisper-medium.en",
    "large-v3": "Systran/faster-whisper-large-v3",
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
    "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "parakeet-tdt-0.6b-v2-int8": "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
    "parakeet-tdt-0.6b-v3-int8": "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
}

MODEL_REVISIONS: dict[str, str] = {
    "tiny": "d90ca5fe260221311c53c58e660288d3deb8d356",
    "tiny.en": "0d3d19a32d3338f10357c0889762bd8d64bbdeba",
    "base": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
    "base.en": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
    "small": "536b0662742c02347bc0e980a01041f333bce120",
    "small.en": "d1d751a5f8271d482d14ca55d9e2deeebbae577f",
    "medium": "08e178d48790749d25932bbc082711ddcfdfbc4f",
    "medium.en": "a29b04bd15381511a9af671baec01072039215e3",
    "distil-small.en": "ef77d90526ccd62cde3808ee70626a01e5cf83e4",
    "distil-medium.en": "80ddfce281f77766d8943d63109199fc8145dfa5",
    "distil-large-v3": "c3058b475261292e64a0412df1d2681c06260fab",
    "large-v3-turbo": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
    "turbo": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
    "large-v3": "edaa852ec7e145841d8ffdb056a99866b5f0a478",
    "parakeet-tdt-0.6b-v2-int8": "1ab9323565ddb038682214b292f588070a538ce2",
    "parakeet-tdt-0.6b-v3-int8": "2bda32ec70b097a55adaa07d9a7173915b43cc78",
}

QUICK_SETUP_TEST_MODEL = "base.en"
QUICK_SETUP_SAFE_MODELS = frozenset({"tiny.en", "base.en", "small.en", "distil-small.en"})
GPU_CLASS_MODELS = frozenset({"large-v3", "large-v3-turbo", "turbo", "distil-large-v3"})
CPU_HEAVY_MODELS = frozenset({"medium", "medium.en", "distil-medium.en"})

SPEECH_MODEL_PRESETS: tuple[SpeechModelPreset, ...] = (
    SpeechModelPreset(
        model="tiny",
        label="Whisper Tiny Multilingual",
        repo_id=MODEL_REPOS["tiny"],
        revision=MODEL_REVISIONS["tiny"],
        tier="Fastest multilingual",
        best_for="quick multilingual commands",
        device_hint="cpu",
        compute_hint="int8",
        notes="Smallest multilingual fallback; accuracy is limited.",
        languages=("multilingual",),
    ),
    SpeechModelPreset(
        model="tiny.en",
        label="Whisper Tiny · English",
        repo_id=MODEL_REPOS["tiny.en"],
        revision=MODEL_REVISIONS["tiny.en"],
        tier="Fastest",
        best_for="instant commands, rough notes",
        device_hint="cpu",
        compute_hint="int8",
        notes="Very fast, least accurate.",
    ),
    SpeechModelPreset(
        model="base",
        label="Whisper Base Multilingual",
        repo_id=MODEL_REPOS["base"],
        revision=MODEL_REVISIONS["base"],
        tier="Fast multilingual",
        best_for="short multilingual dictation",
        device_hint="cpu",
        compute_hint="int8",
        notes="Lightweight multilingual model for CPU systems.",
        languages=("multilingual",),
    ),
    SpeechModelPreset(
        model="base.en",
        label="Whisper Base · English",
        repo_id=MODEL_REPOS["base.en"],
        revision=MODEL_REVISIONS["base.en"],
        tier="Fast CPU",
        best_for="short dictation on CPU",
        device_hint="cpu",
        compute_hint="int8",
        notes="Good fallback when small.en feels slow.",
    ),
    SpeechModelPreset(
        model="small",
        label="Whisper Small Multilingual",
        repo_id=MODEL_REPOS["small"],
        revision=MODEL_REVISIONS["small"],
        tier="Balanced multilingual",
        best_for="daily multilingual dictation",
        device_hint="cpu",
        compute_hint="int8",
        notes="Best general multilingual option for CPU systems.",
        languages=("multilingual",),
    ),
    SpeechModelPreset(
        model="small.en",
        label="Whisper Small · English",
        repo_id=MODEL_REPOS["small.en"],
        revision=MODEL_REVISIONS["small.en"],
        tier="Balanced CPU",
        best_for="daily dictation",
        device_hint="cpu",
        compute_hint="int8",
        notes="Best default for this app on CPU-only systems.",
    ),
    SpeechModelPreset(
        model="medium",
        label="Whisper Medium Multilingual",
        repo_id=MODEL_REPOS["medium"],
        revision=MODEL_REVISIONS["medium"],
        tier="Accurate multilingual",
        best_for="multilingual accuracy over speed",
        device_hint="cpu",
        compute_hint="int8",
        notes="More accurate, but noticeably heavier on CPU.",
        languages=("multilingual",),
    ),
    SpeechModelPreset(
        model="medium.en",
        label="Whisper Medium · English",
        repo_id=MODEL_REPOS["medium.en"],
        revision=MODEL_REVISIONS["medium.en"],
        tier="Accurate CPU",
        best_for="accuracy over speed",
        device_hint="cpu",
        compute_hint="int8",
        notes="More accurate but can feel slower without a GPU.",
    ),
    SpeechModelPreset(
        model="distil-small.en",
        label="Distil Small English",
        repo_id=MODEL_REPOS["distil-small.en"],
        revision=MODEL_REVISIONS["distil-small.en"],
        tier="Fast distilled",
        best_for="fast English dictation",
        device_hint="cpu",
        compute_hint="int8",
        notes="Distilled model, useful when available locally.",
    ),
    SpeechModelPreset(
        model="distil-medium.en",
        label="Distil Medium English",
        repo_id=MODEL_REPOS["distil-medium.en"],
        revision=MODEL_REVISIONS["distil-medium.en"],
        tier="Balanced distilled",
        best_for="quality with less weight than full medium",
        device_hint="cpu",
        compute_hint="int8",
        notes="A middle option between small.en and medium.en.",
    ),
    SpeechModelPreset(
        model="distil-large-v3",
        label="Distil Large v3",
        repo_id=MODEL_REPOS["distil-large-v3"],
        revision=MODEL_REVISIONS["distil-large-v3"],
        tier="GPU quality",
        best_for="high accuracy on CUDA",
        device_hint="cuda",
        compute_hint="float16",
        notes="GPU-oriented quality option; heavy on CPU.",
        languages=("en",),
    ),
    SpeechModelPreset(
        model="large-v3-turbo",
        label="Large v3 Turbo",
        repo_id=MODEL_REPOS["large-v3-turbo"],
        revision=MODEL_REVISIONS["large-v3-turbo"],
        tier="GPU turbo",
        best_for="premium speed/quality on CUDA",
        device_hint="cuda",
        compute_hint="float16",
        notes="Best saved for NVIDIA GPU setups.",
        languages=("multilingual",),
    ),
    SpeechModelPreset(
        model="large-v3",
        label="Large v3",
        repo_id=MODEL_REPOS["large-v3"],
        revision=MODEL_REVISIONS["large-v3"],
        tier="Max quality",
        best_for="best accuracy on GPU",
        device_hint="cuda",
        compute_hint="float16",
        notes="Highest quality, biggest download/runtime cost.",
        languages=("multilingual",),
    ),
    SpeechModelPreset(
        model="parakeet-tdt-0.6b-v2-int8",
        label="Parakeet v2 · English",
        repo_id=MODEL_REPOS["parakeet-tdt-0.6b-v2-int8"],
        revision=MODEL_REVISIONS["parakeet-tdt-0.6b-v2-int8"],
        tier="Recommended",
        best_for="fast, accurate English dictation",
        device_hint="cpu",
        compute_hint="int8",
        notes="Best default for English on most modern PCs.",
        engine="sherpa_onnx",
    ),
    SpeechModelPreset(
        model="parakeet-tdt-0.6b-v3-int8",
        label="Parakeet v3 · Multilingual",
        repo_id=MODEL_REPOS["parakeet-tdt-0.6b-v3-int8"],
        revision=MODEL_REVISIONS["parakeet-tdt-0.6b-v3-int8"],
        tier="Multilingual",
        best_for="fast dictation across supported languages",
        device_hint="cpu",
        compute_hint="int8",
        notes="Best Parakeet choice when you dictate in more than one language.",
        engine="sherpa_onnx",
        languages=PARAKEET_V3_LANGUAGES,
    ),
)


def speech_model_values() -> list[str]:
    return [preset.model for preset in SPEECH_MODEL_PRESETS]


def speech_models_for_language(language: str) -> list[SpeechModelPreset]:
    return [
        preset
        for preset in SPEECH_MODEL_PRESETS
        if model_supports_language(preset, language)
    ]


def speech_engine_values() -> list[str]:
    return ["faster_whisper", "sherpa_onnx"]


def find_speech_model(model: str) -> SpeechModelPreset | None:
    normalized = model.strip()
    for preset in SPEECH_MODEL_PRESETS:
        if preset.model == normalized:
            return preset
    repo_id = MODEL_REPOS.get(normalized)
    if repo_id:
        return SpeechModelPreset(
            model=normalized,
            label=normalized,
            repo_id=repo_id,
            revision=MODEL_REVISIONS[normalized],
            tier="Available",
            best_for="manual selection",
            device_hint="cpu",
            compute_hint="int8",
            notes="Supported by faster-whisper.",
        )
    return None


def engine_for_model(model: str, fallback_engine: str = "faster_whisper") -> str:
    preset = find_speech_model(model)
    return preset.engine if preset is not None else fallback_engine


def is_gpu_class_model(model: str) -> bool:
    return (model or "").strip() in GPU_CLASS_MODELS


def is_cpu_heavy_model(model: str) -> bool:
    return (model or "").strip() in CPU_HEAVY_MODELS


def engine_runtime_available(engine: str) -> bool:
    if engine == "faster_whisper":
        return find_spec("faster_whisper") is not None
    if engine == "sherpa_onnx":
        return find_spec("sherpa_onnx") is not None
    return False


def recommended_model_for_hardware(hardware: HardwareSummary | None = None) -> SpeechModelPreset:
    return recommended_model_policy("en", hardware).dictation


def recommended_model_for_language(
    language: str,
    hardware: HardwareSummary | None = None,
) -> SpeechModelPreset:
    return recommended_model_policy(language, hardware).dictation


def recommended_model_policy(
    language: str,
    hardware: HardwareSummary | None = None,
) -> SpeechModelPolicy:
    from .hardware_detection import detect_hardware
    from .speech_runtime import nvidia_acceleration_ready

    hardware = hardware or detect_hardware()
    code = language.strip().casefold()
    gpu_ready = hardware.has_nvidia and nvidia_acceleration_ready()
    english = code == "en"
    daily = _required_preset("large-v3-turbo" if gpu_ready else "small.en" if english else "small")
    instruction = _required_preset("large-v3-turbo" if gpu_ready else "small.en" if english else "small")
    if english:
        speed = find_speech_model("parakeet-tdt-0.6b-v2-int8") or _required_preset("small.en")
    elif code in PARAKEET_V3_LANGUAGES:
        speed = find_speech_model("parakeet-tdt-0.6b-v3-int8") or daily
    else:
        speed = daily
    return SpeechModelPolicy(
        dictation=daily,
        polish=daily,
        instruction=instruction,
        speed_option=speed,
    )


def _required_preset(model: str) -> SpeechModelPreset:
    preset = find_speech_model(model)
    if preset is None:
        raise KeyError(model)
    return preset
