from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from devtools.audio_polish_benchmark import (
    build_parser,
    score_polished_output,
    summarize as summarize_audio_polish,
)
from devtools.model_matrix import (
    DEFAULT_SUITE_TIMEOUT_SECONDS,
    Candidate,
    build_parser as build_model_matrix_parser,
    candidate_evidence,
    file_evidence,
    ollama_model_blob,
    run_e2e,
    source_bundle_evidence,
    summarize_candidate,
)


def test_audio_polish_runtime_is_optional(monkeypatch):
    monkeypatch.setattr("sys.argv", ["audio-polish", "--asr-results", "results.jsonl"])

    assert build_parser().parse_args().runtime is None


def test_ollama_model_blob_resolves_model_layer(tmp_path, monkeypatch):
    monkeypatch.setattr("devtools.model_matrix.Path.home", lambda: tmp_path)
    root = tmp_path / ".ollama" / "models"
    manifest = root / "manifests" / "registry.ollama.ai" / "library" / "test" / "latest"
    blob = root / "blobs" / "sha256-abc"
    manifest.parent.mkdir(parents=True)
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"GGUF")
    manifest.write_text(
        json.dumps(
            {
                "layers": [
                    {
                        "mediaType": "application/vnd.ollama.image.model",
                        "digest": "sha256:abc",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert ollama_model_blob("library/test/latest") == blob.resolve()


def test_model_matrix_parser_has_bounded_suite_timeout():
    default_args = build_model_matrix_parser().parse_args(["--runtime", "server.exe"])
    custom_args = build_model_matrix_parser().parse_args(
        ["--runtime", "server.exe", "--suite-timeout-seconds", "12.5"]
    )

    assert default_args.suite_timeout_seconds == DEFAULT_SUITE_TIMEOUT_SECONDS
    assert custom_args.suite_timeout_seconds == 12.5


def test_run_e2e_enforces_timeout_strict_gates_and_model_id(tmp_path, monkeypatch):
    model = tmp_path / "model.gguf"
    runtime = tmp_path / "llama-server.exe"
    model.write_bytes(b"GGUF")
    runtime.write_bytes(b"runtime")
    candidate = Candidate("test-model", "Test model", model, "fixture")
    output = tmp_path / "output"
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        (output / "run-id").mkdir()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("devtools.model_matrix.subprocess.run", fake_run)

    run_dir = run_e2e(
        candidate,
        suite="polish",
        runtime=runtime,
        device="CUDA0",
        runs=2,
        config=tmp_path / "config.yaml",
        cases=tmp_path / "cases.yaml",
        output=output,
        timeout_seconds=12.5,
    )

    command = captured["command"]
    assert captured["kwargs"]["timeout"] == 12.5
    assert "--fail-on-gate" in command
    assert command[command.index("--llama-model-id") + 1] == "test-model"
    assert run_dir == (output / "run-id").resolve()


def test_run_e2e_keeps_results_when_strict_gates_fail(tmp_path, monkeypatch):
    model = tmp_path / "model.gguf"
    runtime = tmp_path / "llama-server.exe"
    model.write_bytes(b"GGUF")
    runtime.write_bytes(b"runtime")
    candidate = Candidate("test-model", "Test model", model, "fixture")
    output = tmp_path / "output"

    def fake_run(command, **_kwargs):
        (output / "run-id").mkdir()
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="strict gate failed")

    monkeypatch.setattr("devtools.model_matrix.subprocess.run", fake_run)

    run_dir = run_e2e(
        candidate,
        suite="prompts",
        runtime=runtime,
        device="CUDA0",
        runs=1,
        config=tmp_path / "config.yaml",
        cases=tmp_path / "cases.yaml",
        output=output,
        timeout_seconds=12.5,
    )

    assert run_dir == (output / "run-id").resolve()


def test_run_e2e_reports_bounded_timeout(tmp_path, monkeypatch):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    candidate = Candidate("slow-model", "Slow model", model, "fixture")

    def time_out(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, timeout=4, output=b"partial progress")

    monkeypatch.setattr("devtools.model_matrix.subprocess.run", time_out)

    with pytest.raises(RuntimeError, match="suite 'prompts' timed out after 4 seconds.*slow-model"):
        run_e2e(
            candidate,
            suite="prompts",
            runtime=tmp_path / "llama-server.exe",
            device="CPU",
            runs=1,
            config=tmp_path / "config.yaml",
            cases=tmp_path / "cases.yaml",
            output=tmp_path / "output",
            timeout_seconds=4,
        )


def test_reproducibility_evidence_hashes_models_and_prompt_sources(tmp_path):
    model = tmp_path / "model.gguf"
    prompt = tmp_path / "polish_prompts.py"
    model.write_bytes(b"model bytes")
    prompt.write_bytes(b"prompt bytes")
    expected_model_hash = hashlib.sha256(b"model bytes").hexdigest()

    candidate = candidate_evidence(Candidate("model", "Model", model, "fixture"))
    source_bundle = source_bundle_evidence((prompt, tmp_path / "missing.py"))

    assert candidate["sha256"] == expected_model_hash
    assert candidate["size_bytes"] == len(b"model bytes")
    assert file_evidence(prompt)["sha256"] == hashlib.sha256(b"prompt bytes").hexdigest()
    assert source_bundle["id"] == "winsper-polish-prompt-pipeline"
    assert len(source_bundle["sha256"]) == 64
    assert source_bundle["files"][1]["exists"] is False


def test_model_summary_separates_cold_row_and_ranks_safety(tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    candidate = Candidate("test", "Test", model, "fixture")
    rows = [
        _row("case-a#run-1", 5000, gate="", actual="Alpha", index=0),
        _row("case-a#run-2", 100, gate="", actual="Alpha", index=1),
        _row("case-b#run-1", 200, gate="facts", actual="Bad", index=2, passed=False),
    ]

    summary = summarize_candidate(candidate, rows)

    assert summary["cold_median_ms"] == 5000
    assert summary["warm_median_ms"] == 150
    assert summary["safety_failures"] == 1
    assert summary["backend_memory_peak_mb"] == 256
    assert summary["backend_vram_peak_mb"] == 1024
    assert summary["tokens_per_second"] == 50


def test_audio_polish_summary_tracks_improvement_and_protected_terms():
    source = {
        "model": "speech",
        "case_id": "case#audio-real",
        "actual": "Send this to Somya.",
        "expected": "Send this to Avery.",
    }
    result = score_polished_output(
        "polish",
        source,
        "Send this to Avery.",
        100,
        ["Avery"],
    )

    summary = summarize_audio_polish([result])["polish"]

    assert result["wer_delta"] < 0
    assert result["protected_accuracy"] == 1
    assert summary["improved"] == 1
    assert summary["worsened"] == 0


def _row(case_id, latency, *, gate, actual, index, passed=True):
    return {
        "benchmark_model_id": "test",
        "benchmark_suite_run": "polish",
        "benchmark_row_index": index,
        "case_id": case_id,
        "kind": "polish",
        "status": "pass" if passed else "fail",
        "score": 3 if passed else 0,
        "latency_ms": latency,
        "gate": gate,
        "notes": "",
        "actual": actual,
        "metrics": {
            "backend_memory_mb": 256,
            "backend_vram_mb": 1024,
            "llama_predicted_per_second": 50,
        },
    }
