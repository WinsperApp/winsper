from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from voicepilot.config import AppConfig
from devtools.e2e_lab import (
    LabResult,
    LabRunner,
    apply_rewrite_overrides,
    constraint_outcome,
    first_word_captured,
    first_word_matches,
    phrase_present,
    load_cases,
    llama_option_overrides,
    ollama_option_overrides,
    percentile,
    source_fingerprint,
    summarize,
    token_recall,
    write_artifacts,
)


def test_source_fingerprint_binds_file_content(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("first", encoding="utf-8")
    first = source_fingerprint([source])

    source.write_text("second", encoding="utf-8")

    assert source_fingerprint([source]) != first


def test_rewrite_model_override_selects_ollama_unless_provider_is_explicit():
    config = AppConfig()
    config.rewrite.provider = "embedded"
    args = SimpleNamespace(
        rewrite_model="qwen3:4b-instruct",
        rewrite_provider="",
        prompt_profile="auto",
        llama_server_path="",
        llama_model_path="",
        llama_model_id="",
        llama_device="",
        llama_gpu_layers="all",
        llama_context_size=8192,
    )

    apply_rewrite_overrides(config, args)

    assert config.rewrite.provider == "ollama"
    assert config.rewrite.model == "qwen3:4b-instruct"
    assert config.rewrite.prompt_profile == "auto"
    assert config.rewrite.llama_context_size == 8192
    assert config.rewrite.llama_gpu_layers == "all"

    args.rewrite_provider = "embedded"
    apply_rewrite_overrides(config, args)
    assert config.rewrite.provider == "embedded"


def test_lab_ollama_sampling_overrides_drop_unset_values():
    args = SimpleNamespace(
        ollama_repeat_penalty=1.05,
        ollama_top_p=0.8,
        ollama_top_k=20,
        ollama_seed=42,
        ollama_num_ctx=None,
    )

    assert ollama_option_overrides(args) == {
        "repeat_penalty": 1.05,
        "top_p": 0.8,
        "top_k": 20,
        "seed": 42,
    }


def test_lab_llama_sampling_overrides_drop_unset_values():
    args = SimpleNamespace(
        llama_repeat_penalty=1.05,
        llama_top_p=0.8,
        llama_top_k=20,
        llama_min_p=0.0,
        llama_presence_penalty=None,
        llama_seed=42,
    )

    assert llama_option_overrides(args) == {
        "repeat_penalty": 1.05,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "seed": 42,
    }


def make_result(
    case_id: str,
    status: str,
    score: int | None,
    *,
    gate: str = "",
    latency_ms: float = 10.0,
) -> LabResult:
    return LabResult(
        run_id="run",
        case_id=case_id,
        suite="deterministic",
        category="test",
        kind="spoken_layout",
        status=status,
        score=score,
        latency_ms=latency_ms,
        expected="expected",
        actual="actual",
        gate=gate,
    )


def test_case_loader_keeps_feature_disabled_scenarios():
    cases = load_cases(Path("e2e/cases.yaml"))
    ids = {case["id"] for case in cases}

    assert "layout-disabled" in ids
    assert "action-enter-disabled" in ids


def test_gated_constraints_reject_missing_or_degenerate_output():
    case = {"gate": "facts", "must_include": ["Q2"]}

    assert constraint_outcome(case, "Revenue increased.")["status"] == "fail"
    assert constraint_outcome(case, "?" * 100)["status"] == "fail"


def test_constraints_enforce_exact_word_and_sentence_counts():
    word_case = {"gate": "word-limit", "exact_words": 5}
    max_word_case = {"gate": "word-limit", "max_words": 5}
    sentence_case = {"gate": "sentence-limit", "exact_sentences": 2}

    assert constraint_outcome(word_case, "Clear products align teams well.")["status"] == "pass"
    assert constraint_outcome(word_case, "Clear products align every delivery team well.")["status"] == "fail"
    assert constraint_outcome(max_word_case, "Clear products align teams well.")["status"] == "pass"
    assert constraint_outcome(max_word_case, "Clear products align every delivery team well.")["status"] == "fail"
    assert constraint_outcome(sentence_case, "First sentence. Second sentence!")["status"] == "pass"
    assert constraint_outcome(sentence_case, "First. Second. Third.")["status"] == "fail"


def test_deterministic_catalog_passes_without_external_services(tmp_path):
    runner = LabRunner(
        run_id="test-run",
        config=AppConfig(),
        config_path=tmp_path / "config.yaml",
        cases_path=Path("e2e/cases.yaml"),
        models=["small.en"],
        polish_runs=1,
        rewrite_runs=1,
        guided=False,
        audio_roots=[],
    )

    results = runner.run(load_cases(Path("e2e/cases.yaml")), "deterministic")

    assert len(results) >= 20
    assert all(result.status == "pass" for result in results)
    assert all(result.score == 3 for result in results)


def test_asr_lab_skips_language_incompatible_model_before_inference(tmp_path):
    runner = LabRunner(
        run_id="test-run",
        config=AppConfig(),
        config_path=tmp_path / "config.yaml",
        cases_path=Path("e2e/cases.yaml"),
        models=["small.en"],
        polish_runs=1,
        rewrite_runs=1,
        guided=False,
        audio_roots=[],
    )
    case = {
        "id": "incompatible-language",
        "suite": "asr",
        "kind": "asr",
        "category": "fixed-language",
        "audio": "audio/first-word-winsper.wav",
        "language": "fr",
        "expected": "ignored",
    }

    result = runner._run_case(case, model="small.en")

    assert result.status == "skip"
    assert "does not support language fr" in result.notes


def test_summary_keeps_failed_and_unassessed_gates_separate():
    summary = summarize(
        [
            make_result("pass", "pass", 3, gate="delivery"),
            make_result("fail", "fail", 0, gate="safety"),
            make_result("skip", "skip", None, gate="hardware"),
        ]
    )

    assert summary["pass_rate"] == 0.5
    assert summary["gate_failures"] == ["deterministic:safety"]
    assert summary["unassessed_gates"] == ["deterministic:hardware"]
    assert not summary["phase4"]["ready"]
    assert all(gate["status"] == "insufficient" for gate in summary["phase4"]["gates"].values())


def test_phase4_release_gate_requires_representative_counts_and_targets():
    results = []
    for model in ("small.en", "large-v3-turbo"):
        for index in range(50):
            results.append(
                LabResult(
                    run_id="run",
                    case_id=f"asr-{model}-{index}",
                    suite="asr",
                    category="certification",
                    kind="asr",
                    status="pass",
                    score=3,
                    latency_ms=100,
                    expected="expected",
                    actual="actual",
                    model=model,
                    gate="first-word-capture",
                    metrics={
                        "language": "en",
                        "speech_device": "cuda" if model == "large-v3-turbo" else "cpu",
                        "speech_compute_type": "float16" if model == "large-v3-turbo" else "int8",
                        "purpose": "polish_instruction",
                        "corpus_kind": "human",
                        "production_wer": 0.05,
                        "protected_accuracy": 1.0,
                        "protected_terms": ["Winsper"],
                        "translation_violation": False,
                        "script_preserved": True,
                        "first_word_ok": True,
                    },
                )
            )

    phase4 = summarize(results)["phase4"]

    assert phase4["ready"]
    assert all(gate["status"] == "pass" for gate in phase4["gates"].values())
    assert all(profile["ready"] for profile in phase4["profiles"].values())


def test_phase4_gate_excludes_optional_or_wrong_language_policy_models():
    result = LabResult(
        run_id="run",
        case_id="optional-speed-model",
        suite="asr",
        category="certification",
        kind="asr",
        status="fail",
        score=0,
        latency_ms=10,
        expected="Winsper",
        actual="Winspur",
        model="parakeet-tdt-0.6b-v2-int8",
        metrics={
            "language": "en",
            "corpus_kind": "human",
            "production_wer": 1.0,
            "first_word_ok": False,
        },
    )

    phase4 = summarize([result])["phase4"]

    assert not phase4["ready"]
    assert all(gate["samples"] == 0 for gate in phase4["gates"].values())


def test_phase4_first_word_gate_counts_only_explicit_boundary_cases():
    result = LabResult(
        run_id="run",
        case_id="ordinary-asr",
        suite="asr",
        category="clean",
        kind="asr",
        status="pass",
        score=3,
        latency_ms=100,
        expected="Expected text",
        actual="Expected text",
        model="small.en",
        metrics={
            "language": "en",
            "speech_device": "cpu",
            "speech_compute_type": "int8",
            "corpus_kind": "human",
            "production_wer": 0.0,
            "first_word_ok": True,
        },
    )

    phase4 = summarize([result])["phase4"]

    assert phase4["profiles"]["cpu"]["gates"]["first_word_capture"]["samples"] == 0


def test_phase4_gate_excludes_large_model_that_fell_back_to_cpu():
    result = LabResult(
        run_id="run",
        case_id="large-cpu-fallback",
        suite="asr",
        category="certification",
        kind="asr",
        status="pass",
        score=3,
        latency_ms=100,
        expected="Winsper",
        actual="Winsper",
        model="large-v3-turbo",
        metrics={
            "language": "en",
            "corpus_kind": "human",
            "speech_device": "cpu",
            "speech_compute_type": "int8",
            "production_wer": 0.0,
            "first_word_ok": True,
        },
    )

    phase4 = summarize([result])["phase4"]

    assert not phase4["ready"]
    assert all(gate["samples"] == 0 for gate in phase4["gates"].values())


def test_percentile_interpolates_small_samples():
    assert percentile([10.0, 20.0, 30.0], 50) == 20.0
    assert percentile([10.0, 20.0], 95) == 19.5
    assert percentile([], 95) is None


def test_first_word_gate_requires_exact_first_token():
    assert first_word_matches("Winsper captured this", "Winsper should capture this")
    assert not first_word_matches("Winspur captured this", "Winsper should capture this")
    assert not first_word_matches("", "Winsper should capture this")


def test_first_word_capture_distinguishes_near_spelling_from_omission():
    assert first_word_captured("Winspur captured this", "Winsper should capture this")
    assert first_word_captured("Winsper captured this", "Winsper should capture this")
    assert not first_word_captured("Should capture this", "Winsper should capture this")
    assert not first_word_captured("", "Winsper should capture this")
    assert not first_word_captured("At the office", "I am at the office")


def test_constraint_phrase_matching_does_not_match_inside_words():
    assert phrase_present("Remove um from this", "um")
    assert not phrase_present("Review the document", "um")
    assert phrase_present("Authentication token", "token")
    assert phrase_present("The price is ₹2,499.", "₹")
    assert phrase_present("Open www.fb.com now.", "www.fb.com")


def test_protected_token_recall_uses_whole_phrase_matching():
    assert token_recall("Use Redis cache here", ["Redis"]) == 1
    assert token_recall("Use reddish cache here", ["Redis"]) == 0
    assert token_recall("PostgreSQL schema updated", ["PostgreSQL schema"]) == 1


def test_asr_pipeline_applies_correction_memory_before_protected_gate(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    correction_store = LabRunner(
        run_id="setup",
        config=AppConfig(),
        config_path=config_path,
        cases_path=tmp_path / "cases.yaml",
        models=["fake"],
        polish_runs=1,
        rewrite_runs=1,
        guided=False,
        audio_roots=[],
    )._corrections
    correction_store.add_rule("Samya", "Avery")

    class FakeClip:
        duration_seconds = 1.0

    class FakeTranscriber:
        config = AppConfig().speech

        def transcribe(self, clip, config=None):
            return "Send this to Samya."

    runner = LabRunner(
        run_id="test-run",
        config=AppConfig(),
        config_path=config_path,
        cases_path=tmp_path / "cases.yaml",
        models=["fake"],
        polish_runs=1,
        rewrite_runs=1,
        guided=False,
        audio_roots=[],
    )
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"fake")
    monkeypatch.setattr(runner, "_transcriber", lambda model: FakeTranscriber())
    monkeypatch.setattr("devtools.e2e_lab.read_wav", lambda path: FakeClip())

    outcome = runner._execute(
        {
            "kind": "asr",
            "audio": "clip.wav",
            "expected": "Send this to Avery.",
            "protected": ["Avery"],
            "gate": "protected-terms",
        },
        model="fake",
    )

    assert outcome["status"] == "pass"
    assert outcome["raw_transcript"] == "Send this to Samya."
    assert outcome["actual"] == "Send this to Avery."
    assert outcome["production_wer"] == 0
    assert outcome["protected_accuracy"] == 1


def test_artifacts_include_machine_and_human_readable_results(tmp_path):
    results = [make_result("pass", "pass", 3)]
    summary = summarize(results)
    manifest = {"run_id": "run", "commit": "abc", "platform": "Windows"}

    write_artifacts(tmp_path, manifest, results, summary)

    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["passed"] == 1
    assert '"case_id": "pass"' in (tmp_path / "results.jsonl").read_text(encoding="utf-8")
    assert "Winsper E2E Laboratory" in (tmp_path / "report.html").read_text(encoding="utf-8")
    assert (tmp_path / "results.csv").exists()
