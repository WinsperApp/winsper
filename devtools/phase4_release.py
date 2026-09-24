"""Release-gate calculations used by the repository E2E lab."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class Phase4Gate:
    name: str
    value: float | None
    target: str
    samples: int
    minimum_samples: int
    status: str


def evaluate_phase4_release(results: Iterable[object]) -> dict[str, Any]:
    policy_results = [
        result
        for result in results
        if getattr(result, "suite", "") == "asr"
        and getattr(result, "status", "") != "skip"
        and _metric(result, "corpus_kind") == "human"
        and _release_profile(result) is not None
    ]
    profiles = {
        profile: _evaluate_gates(
            [result for result in policy_results if _release_profile(result) == profile]
        )
        for profile in ("cpu", "nvidia")
    }
    combined = _evaluate_gates(policy_results)
    return {
        "ready": all(profile["ready"] for profile in profiles.values()),
        "gates": combined["gates"],
        "profiles": profiles,
    }


def _evaluate_gates(executed: list[object]) -> dict[str, Any]:
    english_wer = [
        float(value)
        for result in executed
        if _metric(result, "language") == "en"
        and isinstance((value := _metric(result, "production_wer")), (int, float))
    ]
    protected = [
        float(value)
        for result in executed
        if isinstance((value := _metric(result, "protected_accuracy")), (int, float))
        and _metric(result, "protected_terms")
    ]
    fixed_translation = [
        not bool(_metric(result, "translation_violation"))
        for result in executed
        if _metric(result, "translation_violation") is not None
    ]
    mixed_scripts = [
        bool(_metric(result, "script_preserved"))
        for result in executed
        if _metric(result, "script_preserved") is not None
    ]
    instruction_intent = [
        getattr(result, "status", "") == "pass"
        for result in executed
        if _metric(result, "purpose") == "polish_instruction"
    ]
    first_word = [
        bool(_metric(result, "first_word_ok"))
        for result in executed
        if getattr(result, "gate", "") == "first-word-capture"
        and _metric(result, "first_word_ok") is not None
    ]

    gates = (
        _maximum_gate("english_wer", english_wer, 0.07, 50),
        _minimum_gate("protected_names", protected, 0.95, 20),
        _minimum_gate("fixed_language_no_translation", fixed_translation, 1.0, 20),
        _minimum_gate("mixed_script_preservation", mixed_scripts, 0.90, 20),
        _minimum_gate("short_instruction_intent", instruction_intent, 0.95, 50),
        _minimum_gate("first_word_capture", first_word, 0.99, 50),
    )
    return {
        "ready": all(gate.status == "pass" for gate in gates),
        "gates": {gate.name: asdict(gate) for gate in gates},
    }


def _release_profile(result: object) -> str | None:
    """Map only evidence-backed default-policy runs into release gates."""
    model = str(getattr(result, "model", "")).strip().casefold()
    language = str(_metric(result, "language") or "").strip().casefold()
    device = str(_metric(result, "speech_device") or "").strip().casefold()
    compute_type = str(_metric(result, "speech_compute_type") or "").strip().casefold()
    if model == "large-v3-turbo" and device == "cuda" and compute_type == "float16":
        return "nvidia"
    if model == "small.en" and language == "en" and device == "cpu" and compute_type == "int8":
        return "cpu"
    if model == "small" and language != "en" and device == "cpu" and compute_type == "int8":
        return "cpu"
    return None


def _metric(result: object, key: str):
    metrics = getattr(result, "metrics", {})
    return metrics.get(key) if isinstance(metrics, dict) else None


def _maximum_gate(name: str, values: list[float], maximum: float, minimum_samples: int) -> Phase4Gate:
    value = statistics.fmean(values) if values else None
    status = "insufficient" if len(values) < minimum_samples else "pass" if value is not None and value <= maximum else "fail"
    return Phase4Gate(name, value, f"<= {maximum:.2%}", len(values), minimum_samples, status)


def _minimum_gate(name: str, values: list[float] | list[bool], minimum: float, minimum_samples: int) -> Phase4Gate:
    numeric = [float(value) for value in values]
    value = statistics.fmean(numeric) if numeric else None
    status = "insufficient" if len(numeric) < minimum_samples else "pass" if value is not None and value >= minimum else "fail"
    return Phase4Gate(name, value, f">= {minimum:.2%}", len(numeric), minimum_samples, status)
