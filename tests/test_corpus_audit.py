from __future__ import annotations

import csv
from pathlib import Path

import pytest

from devtools.corpus_audit import (
    MINIMUM_COVERAGE,
    SOLO_TESTER_LANGUAGES,
    audit_manifest,
    build_report,
    coverage_for,
    filter_languages,
    load_asr_cases,
    speaker_counts,
)
from devtools.e2e_record import filter_recording_cases, recording_seconds
from devtools.manual_benchmark import REQUIRED_COLUMNS


ROOT = Path(__file__).resolve().parents[1]


def test_release_corpus_manifest_meets_every_minimum():
    cases = load_asr_cases(ROOT / "e2e" / "cases.yaml")

    assert not audit_manifest(cases)
    coverage = coverage_for(cases)
    assert all(coverage[name] >= minimum for name, minimum in MINIMUM_COVERAGE.items())
    assert all(count >= 30 for count in speaker_counts(cases).values())


def test_release_corpus_has_unique_ids_and_audio_paths():
    cases = load_asr_cases(ROOT / "e2e" / "cases.yaml")

    assert len({case["id"] for case in cases}) == len(cases)
    assert len({case["audio"] for case in cases}) == len(cases)


def test_solo_tester_lane_is_complete_and_does_not_claim_speaker_diversity():
    cases_path = ROOT / "e2e" / "cases.yaml"
    cases = load_asr_cases(cases_path)
    selected = filter_languages(cases, set(SOLO_TESTER_LANGUAGES))

    assert {case["language"] for case in selected} == set(SOLO_TESTER_LANGUAGES)
    assert not audit_manifest(selected, require_speaker_diversity=False)
    report = build_report(cases_path, solo_tester=True)
    assert "single-tester" in report["evidence_scope"]
    assert "not broad speaker/accent certification" in report["evidence_scope"]
    assert report["speakers"] == {"solo-tester": 124}
    assert set(report["assignment_buckets"]) == {"speaker-a", "speaker-b", "speaker-c"}


def test_solo_recorder_ignores_assignment_buckets_and_accepts_language_override():
    cases = load_asr_cases(ROOT / "e2e" / "cases.yaml")
    selected = filter_recording_cases(cases, solo_tester=True)

    assert {case["language"] for case in selected} == set(SOLO_TESTER_LANGUAGES)
    assert {case.get("speaker", "speaker-a") for case in selected} == {
        "speaker-a",
        "speaker-b",
        "speaker-c",
    }
    assert all(case["language"] == "hi" for case in filter_recording_cases(cases, languages=["hi"]))
    with pytest.raises(ValueError, match="supports only"):
        filter_recording_cases(cases, languages=["fr"], solo_tester=True)


def test_recording_time_scales_with_phrase_length_and_keeps_requested_minimum():
    assert recording_seconds("", 6) == 6
    assert recording_seconds("Short phrase.", 6) == 6
    assert recording_seconds(" ".join(["word"] * 20), 6) == 12
    assert recording_seconds(" ".join(["word"] * 60), 6) == 32


def test_manual_benchmark_template_contains_required_columns():
    with (ROOT / "e2e" / "manual-benchmark-template.csv").open(encoding="utf-8", newline="") as stream:
        columns = set(next(csv.reader(stream)))

    assert REQUIRED_COLUMNS <= columns
