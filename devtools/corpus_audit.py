"""Validate the real-human speech corpus before release certification."""

from __future__ import annotations

import argparse
import json
import wave
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


MINIMUM_COVERAGE = {
    "total": 130,
    "english_wer": 50,
    "protected_names": 20,
    "fixed_language": 20,
    "mixed_script": 20,
    "short_instruction": 50,
    "first_word": 50,
    "silence_or_noise": 10,
}
REQUIRED_SPEAKERS = ("speaker-a", "speaker-b", "speaker-c")
SOLO_TESTER_LANGUAGES = ("en", "hi", "mix-hi-en")
SUPPORTED_SAMPLE_RATES = (16_000, 48_000)


def load_asr_cases(path: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError("E2E cases file must contain a cases list.")
    return [
        item
        for item in raw_cases
        if isinstance(item, dict)
        and item.get("active", True) is not False
        and item.get("suite") == "asr"
        and item.get("kind") == "asr"
    ]


def coverage_for(cases: list[dict[str, Any]]) -> dict[str, int]:
    voiced = [case for case in cases if str(case.get("expected") or "").strip()]
    return {
        "total": len(cases),
        "english_wer": sum(str(case.get("language") or "") == "en" for case in voiced),
        "protected_names": sum(bool(case.get("protected")) for case in voiced),
        "fixed_language": sum(bool(case.get("english_translation") or case.get("expected_script")) for case in voiced),
        "mixed_script": sum(bool(case.get("required_scripts")) for case in voiced),
        "short_instruction": sum(case.get("purpose") == "polish_instruction" for case in voiced),
        "first_word": sum(case.get("gate") == "first-word-capture" for case in voiced),
        "silence_or_noise": len(cases) - len(voiced),
    }


def speaker_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    return dict(
        Counter(
            str(case.get("speaker") or "speaker-a")
            for case in cases
            if str(case.get("expected") or "").strip()
        )
    )


def filter_languages(cases: list[dict[str, Any]], languages: set[str]) -> list[dict[str, Any]]:
    return [
        case
        for case in cases
        if str(case.get("language") or "").strip().casefold() in languages
    ]


def audit_manifest(cases: list[dict[str, Any]], *, require_speaker_diversity: bool = True) -> list[str]:
    issues: list[str] = []
    ids = [str(case.get("id") or "") for case in cases]
    audio = [str(case.get("audio") or "") for case in cases]
    for label, values in (("case ID", ids), ("audio path", audio)):
        missing = sum(not value for value in values)
        duplicates = sorted(value for value, count in Counter(values).items() if value and count > 1)
        if missing:
            issues.append(f"{missing} ASR cases have no {label}.")
        if duplicates:
            issues.append(f"Duplicate {label}s: {', '.join(duplicates)}")

    coverage = coverage_for(cases)
    for metric, minimum in MINIMUM_COVERAGE.items():
        if coverage[metric] < minimum:
            issues.append(f"{metric}: {coverage[metric]}/{minimum}")
    if require_speaker_diversity:
        speakers = speaker_counts(cases)
        for speaker in REQUIRED_SPEAKERS:
            if speakers.get(speaker, 0) < 30:
                issues.append(f"{speaker}: {speakers.get(speaker, 0)}/30 voiced clips")
    return issues


def audit_audio(cases: list[dict[str, Any]], cases_path: Path) -> dict[str, Any]:
    missing: list[str] = []
    invalid: list[str] = []
    for case in cases:
        audio_path = cases_path.parent / str(case.get("audio") or "")
        if not audio_path.exists():
            missing.append(str(case.get("id") or audio_path.name))
            continue
        try:
            with wave.open(str(audio_path), "rb") as wav:
                if (
                    wav.getnchannels() != 1
                    or wav.getframerate() not in SUPPORTED_SAMPLE_RATES
                    or wav.getsampwidth() != 2
                ):
                    invalid.append(
                        f"{case.get('id')}: expected mono 16/48 kHz 16-bit PCM, got "
                        f"{wav.getnchannels()}ch/{wav.getframerate()}Hz/{wav.getsampwidth() * 8}-bit"
                    )
                elif wav.getnframes() <= 0:
                    invalid.append(f"{case.get('id')}: empty WAV")
        except (EOFError, wave.Error) as exc:
            invalid.append(f"{case.get('id')}: {exc}")
    return {"recorded": len(cases) - len(missing), "missing": missing, "invalid": invalid}


def build_report(cases_path: Path, *, solo_tester: bool = False) -> dict[str, Any]:
    cases = load_asr_cases(cases_path)
    if solo_tester:
        cases = filter_languages(cases, set(SOLO_TESTER_LANGUAGES))
    assignments = speaker_counts(cases)
    voiced_count = sum(assignments.values())
    return {
        "evidence_scope": (
            "single-tester functional English/Hindi/Hinglish evidence; not broad speaker/accent certification"
            if solo_tester
            else "multi-speaker corpus"
        ),
        "cases": len(cases),
        "coverage": coverage_for(cases),
        "minimum_coverage": MINIMUM_COVERAGE,
        "speakers": {"solo-tester": voiced_count} if solo_tester else assignments,
        "assignment_buckets": assignments,
        "manifest_issues": audit_manifest(cases, require_speaker_diversity=not solo_tester),
        "audio": audit_audio(cases, cases_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Winsper's real-human release corpus.")
    parser.add_argument("--cases", type=Path, default=Path("e2e/cases.yaml"))
    parser.add_argument("--json", type=Path)
    parser.add_argument("--require-audio", action="store_true")
    parser.add_argument(
        "--solo-tester",
        action="store_true",
        help="Audit only English, Hindi, and Hinglish without claiming speaker diversity.",
    )
    args = parser.parse_args()

    report = build_report(args.cases, solo_tester=args.solo_tester)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["manifest_issues"]:
        return 1
    if args.require_audio and (report["audio"]["missing"] or report["audio"]["invalid"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
