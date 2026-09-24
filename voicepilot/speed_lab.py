from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import (
    PARAKEET_V3_LANGUAGES,
    detect_hardware,
    engine_for_model,
    engine_runtime_available,
)
from .speech_languages import fast_dictation_supported
from .speech_runtime import nvidia_acceleration_ready
from .storage import atomic_write_json


PARAKEET_ENGLISH_MODEL = "parakeet-tdt-0.6b-v2-int8"
PARAKEET_MULTILINGUAL_MODEL = "parakeet-tdt-0.6b-v3-int8"


@dataclass(frozen=True)
class BenchmarkResult:
    model: str
    device: str
    compute_type: str
    recorded_seconds: float
    transcribed_seconds: float
    load_seconds: float
    transcription_seconds: float
    warm_transcription_seconds: float
    realtime_factor: float
    transcript_preview: str
    expected_text: str
    accuracy_score: float | None
    word_error_rate: float | None
    created_at: str
    warm_sample_count: int = 0
    warm_p50_seconds: float = 0.0
    warm_p95_seconds: float = 0.0
    warm_max_seconds: float = 0.0


class SpeedLabStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_config(cls, config_path: Path) -> "SpeedLabStore":
        return cls(speed_lab_path_for_config(config_path))

    def list(self) -> list[BenchmarkResult]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_results = payload.get("results") if isinstance(payload, dict) else payload
        if not isinstance(raw_results, list):
            return []
        results: list[BenchmarkResult] = []
        for item in raw_results:
            if isinstance(item, dict):
                result = result_from_dict(item)
                if result is not None:
                    results.append(result)
        return results

    def latest_by_model(self) -> dict[str, BenchmarkResult]:
        latest: dict[str, BenchmarkResult] = {}
        for result in self.list():
            key = result_key(result.model, result.device, result.compute_type)
            if key not in latest or result.created_at > latest[key].created_at:
                latest[key] = result
        return latest

    def append(self, result: BenchmarkResult) -> None:
        results = self.list()
        results.append(result)
        results = trim_results(results)
        payload = {"version": 1, "results": [asdict(item) for item in results]}
        atomic_write_json(self.path, payload)

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def speed_lab_path_for_config(config_path: Path) -> Path:
    return config_path.parent / "speed_benchmarks.json"


def speed_lab_clip_path_for_config(config_path: Path) -> Path:
    return config_path.parent / "speed_lab_clip.wav"


def create_benchmark_result(
    model: str,
    device: str,
    compute_type: str,
    recorded_seconds: float,
    transcribed_seconds: float,
    load_seconds: float,
    transcription_seconds: float,
    transcript: str,
    expected_text: str = "",
    warm_transcription_seconds: float = 0.0,
    warm_sample_count: int = 0,
    warm_p50_seconds: float = 0.0,
    warm_p95_seconds: float = 0.0,
    warm_max_seconds: float = 0.0,
) -> BenchmarkResult:
    score = score_transcript(transcript, expected_text)
    return BenchmarkResult(
        model=model,
        device=device,
        compute_type=compute_type,
        recorded_seconds=recorded_seconds,
        transcribed_seconds=transcribed_seconds,
        load_seconds=load_seconds,
        transcription_seconds=transcription_seconds,
        warm_transcription_seconds=warm_transcription_seconds,
        realtime_factor=transcription_seconds / max(transcribed_seconds, 0.001),
        transcript_preview=transcript.strip()[:220],
        expected_text=expected_text.strip(),
        accuracy_score=score.accuracy_score if score is not None else None,
        word_error_rate=score.word_error_rate if score is not None else None,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        warm_sample_count=max(0, warm_sample_count),
        warm_p50_seconds=max(0.0, warm_p50_seconds),
        warm_p95_seconds=max(0.0, warm_p95_seconds),
        warm_max_seconds=max(0.0, warm_max_seconds),
    )


def result_from_dict(data: dict[str, Any]) -> BenchmarkResult | None:
    try:
        return BenchmarkResult(
            model=str(data.get("model") or ""),
            device=str(data.get("device") or "cpu"),
            compute_type=str(data.get("compute_type") or "int8"),
            recorded_seconds=float(data.get("recorded_seconds") or 0),
            transcribed_seconds=float(data.get("transcribed_seconds") or 0),
            load_seconds=float(data.get("load_seconds") or 0),
            transcription_seconds=float(data.get("transcription_seconds") or 0),
            warm_transcription_seconds=float(data.get("warm_transcription_seconds") or 0),
            realtime_factor=float(data.get("realtime_factor") or 0),
            transcript_preview=str(data.get("transcript_preview") or ""),
            expected_text=str(data.get("expected_text") or ""),
            accuracy_score=optional_float(data.get("accuracy_score")),
            word_error_rate=optional_float(data.get("word_error_rate")),
            created_at=str(data.get("created_at") or ""),
            warm_sample_count=max(0, int(data.get("warm_sample_count") or 0)),
            warm_p50_seconds=max(0.0, float(data.get("warm_p50_seconds") or 0)),
            warm_p95_seconds=max(0.0, float(data.get("warm_p95_seconds") or 0)),
            warm_max_seconds=max(0.0, float(data.get("warm_max_seconds") or 0)),
        )
    except (TypeError, ValueError):
        return None


def result_key(model: str, device: str, compute_type: str) -> str:
    return f"{model}|{device}|{compute_type}"


def trim_results(results: list[BenchmarkResult], max_results: int = 80) -> list[BenchmarkResult]:
    if len(results) <= max_results:
        return results
    return results[-max_results:]


def benchmark_models_for_hardware(config: AppConfig) -> list[str]:
    hardware = detect_hardware()
    english = config.speech.language == "en"
    suffix = ".en" if english else ""
    models = [f"tiny{suffix}", f"base{suffix}", f"small{suffix}", f"medium{suffix}"]
    if engine_runtime_available("sherpa_onnx"):
        if english:
            models.append(PARAKEET_ENGLISH_MODEL)
        elif config.speech.language in PARAKEET_V3_LANGUAGES:
            models.append(PARAKEET_MULTILINGUAL_MODEL)
    if hardware.has_nvidia:
        models.append("large-v3-turbo")
    for model in [config.dictation.ramble_model, config.speech.model]:
        if model and model not in models:
            models.append(model)
    return models


def apply_speed_profile(
    config: AppConfig,
    profile: str,
    latest: dict[str, BenchmarkResult] | None = None,
    *,
    acceleration_ready: bool | None = None,
) -> str:
    profile = profile.strip().lower()
    profile = {
        "fast": "instant",
        "accuracy": "precise",
        "accurate": "precise",
        "gpu": "gpu_boost",
        "gpu boost": "gpu_boost",
        "gpu-boost": "gpu_boost",
    }.get(profile, profile)
    compatibility_detail = ""
    if profile == "instant" and not fast_dictation_supported(config.speech.language):
        profile = "balanced"
        compatibility_detail = " Fast is unavailable for this language, so Balanced was applied."
    latest = latest or {}
    cpu_device = "cpu"
    cpu_compute = "int8"
    hardware = None
    gpu_ready = False
    if profile in {"precise", "gpu_boost"}:
        if acceleration_ready is None:
            hardware = detect_hardware()
            gpu_ready = hardware.has_nvidia and nvidia_acceleration_ready()
        else:
            # Settings only needs to compare the current configuration with
            # each quality preset. Re-probing hardware while opening the page
            # can block the UI for seconds, so that read-only comparison uses
            # the device state already persisted in the configuration.
            gpu_ready = acceleration_ready
    detail = compatibility_detail
    english = config.speech.language == "en"
    suffix = ".en" if english else ""
    tiny = f"tiny{suffix}"
    base = f"base{suffix}"
    small = f"small{suffix}"
    medium = f"medium{suffix}"
    parakeet = (
        PARAKEET_ENGLISH_MODEL
        if english
        else (
            PARAKEET_MULTILINGUAL_MODEL
            if config.speech.language in PARAKEET_V3_LANGUAGES
            else ""
        )
    )

    if profile == "instant":
        model = fastest_available([tiny, base, small], latest) or base
        preload = True
    elif profile == "precise":
        if gpu_ready:
            model = "large-v3-turbo"
            config.speech.device = "cuda"
            config.speech.compute_type = "float16"
            preload = False
        elif parakeet and engine_runtime_available("sherpa_onnx"):
            model = parakeet
            preload = False
        else:
            model = medium
            preload = False
            detail = " Install Parakeet support to unlock the experimental precise engine."
            if hardware is not None and hardware.has_nvidia and not gpu_ready:
                detail = " CUDA runtime is unavailable, so CPU precise was applied." + detail
    elif profile == "gpu_boost":
        if gpu_ready:
            model = "large-v3-turbo"
            config.speech.device = "cuda"
            config.speech.compute_type = "float16"
            preload = False
        else:
            model = balanced_model(latest, multilingual=not english)
            preload = True
            detail = (
                " CUDA runtime is unavailable, so Balanced was applied."
                if hardware is not None and hardware.has_nvidia
                else " No NVIDIA GPU detected, so Balanced was applied."
            )
    else:
        profile = "balanced"
        model = balanced_model(latest, multilingual=not english)
        preload = True

    if profile not in {"precise", "gpu_boost"} or not gpu_ready:
        config.speech.device = cpu_device
        config.speech.compute_type = cpu_compute
    config.speech.engine = engine_for_model(model, "faster_whisper")
    config.speech.model = model
    config.dictation.ramble_model = model
    config.dictation.polish_model = model
    config.dictation.rewrite_instruction_model = model
    config.speech.preload_on_startup = preload
    return f"Applied {profile} profile: Speech {model}.{detail}"


def fastest_available(models: list[str], latest: dict[str, BenchmarkResult]) -> str | None:
    ranked: list[BenchmarkResult] = []
    for result in latest.values():
        if result.model in models and result.device == "cpu" and result.compute_type == "int8":
            ranked.append(result)
    if not ranked:
        return None
    ranked.sort(key=lambda item: item.realtime_factor)
    return ranked[0].model


def balanced_model(latest: dict[str, BenchmarkResult], *, multilingual: bool = False) -> str:
    suffix = "" if multilingual else ".en"
    small_name = f"small{suffix}"
    base_name = f"base{suffix}"
    small = latest.get(result_key(small_name, "cpu", "int8"))
    base = latest.get(result_key(base_name, "cpu", "int8"))
    if small and small.realtime_factor <= 1.25:
        return small_name
    if small and base and small.realtime_factor <= base.realtime_factor * 1.8:
        return small_name
    return small_name if not latest else base_name


def result_summary(result: BenchmarkResult | None) -> str:
    if result is None:
        return "Not measured"
    accuracy = "" if result.accuracy_score is None else f", {result.accuracy_score:.0%} accuracy"
    return f"{result.realtime_factor:.2f}x realtime, {result.transcription_seconds:.2f}s transcription{accuracy}"


@dataclass(frozen=True)
class TranscriptScore:
    accuracy_score: float
    word_error_rate: float
    similarity: float


def score_transcript(transcript: str, expected_text: str) -> TranscriptScore | None:
    expected_words = normalized_words(expected_text)
    if not expected_words:
        return None
    actual_words = normalized_words(transcript)
    edits = levenshtein_distance(expected_words, actual_words)
    wer = edits / max(len(expected_words), 1)
    similarity = SequenceMatcher(None, normalize_for_score(expected_text), normalize_for_score(transcript)).ratio()
    accuracy = max(0.0, min(1.0, 1.0 - wer))
    return TranscriptScore(accuracy_score=accuracy, word_error_rate=wer, similarity=similarity)


def normalized_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def normalize_for_score(text: str) -> str:
    return " ".join(normalized_words(text))


def levenshtein_distance(expected: list[str], actual: list[str]) -> int:
    previous = list(range(len(actual) + 1))
    for row_index, expected_word in enumerate(expected, start=1):
        current = [row_index]
        for col_index, actual_word in enumerate(actual, start=1):
            cost = 0 if expected_word == actual_word else 1
            current.append(
                min(
                    previous[col_index] + 1,
                    current[col_index - 1] + 1,
                    previous[col_index - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
