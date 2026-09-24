from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SUITE_TIMEOUT_SECONDS = 900.0
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROMPT_SOURCE_PATHS = (
    REPOSITORY_ROOT / "voicepilot" / "destination.py",
    REPOSITORY_ROOT / "voicepilot" / "instruction_quality.py",
    REPOSITORY_ROOT / "voicepilot" / "polish_prompts.py",
    REPOSITORY_ROOT / "voicepilot" / "polish_service.py",
    REPOSITORY_ROOT / "voicepilot" / "polish_validation.py",
    REPOSITORY_ROOT / "voicepilot" / "self_corrections.py",
    REPOSITORY_ROOT / "voicepilot" / "spoken_formatting.py",
    REPOSITORY_ROOT / "voicepilot" / "voice_commands.py",
)


@dataclass(frozen=True)
class Candidate:
    id: str
    label: str
    path: Path
    source: str


NEW_MODELS = (
    ("lfm2.5-1.2b", "LFM2.5 1.2B", "LFM2.5-1.2B-Instruct-Q4_K_M.gguf"),
    ("ministral-3-3b", "Ministral 3 3B", "Ministral-3-3B-Instruct-2512-Q4_K_M.gguf"),
    ("qwen3.5-2b", "Qwen 3.5 2B", "Qwen3.5-2B.q4_k_m.gguf"),
    ("smollm3-3b", "SmolLM3 3B", "SmolLM3-Q4_K_M.gguf"),
)

BASELINES = (
    ("qwen2.5-1.5b", "Qwen 2.5 1.5B", "library/qwen2.5/1.5b"),
    ("llama3.2-3b", "Llama 3.2 3B", "library/llama3.2/3b"),
    ("qwen3-8b", "Qwen 3 8B", "library/qwen3/8b"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark local GGUF polish models through Winsper production prompts.")
    parser.add_argument("--models-dir", type=Path, default=Path("models_test"))
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--device", default="CUDA0")
    parser.add_argument("--backend-label", default="cuda")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--cases", type=Path, default=Path("e2e/cases.yaml"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/model-benchmark"))
    parser.add_argument("--names", default="", help="Comma-separated candidate IDs; defaults to every discovered model.")
    parser.add_argument("--no-baselines", action="store_true")
    parser.add_argument(
        "--suite-timeout-seconds",
        type=positive_seconds,
        default=DEFAULT_SUITE_TIMEOUT_SECONDS,
        help="Wall-clock limit for each model/suite subprocess (default: 900 seconds).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    candidates = discover_candidates(args.models_dir, include_baselines=not args.no_baselines)
    selected_names = {item.strip() for item in args.names.split(",") if item.strip()}
    if selected_names:
        candidates = [candidate for candidate in candidates if candidate.id in selected_names]
        missing = selected_names - {candidate.id for candidate in candidates}
        if missing:
            raise RuntimeError("Unknown or missing candidates: " + ", ".join(sorted(missing)))
    if not candidates:
        raise RuntimeError("No benchmark candidates found.")
    runtime = args.runtime.resolve()
    if not runtime.is_file():
        raise RuntimeError(f"llama-server runtime missing: {runtime}")

    evidence_captured_at = datetime.now(timezone.utc).isoformat()
    input_evidence = {
        "config": file_evidence(args.config),
        "cases": file_evidence(args.cases),
        "runtime": file_evidence(runtime),
        "prompt_implementation": source_bundle_evidence(PROMPT_SOURCE_PATHS),
    }
    candidates_evidence = [candidate_evidence(candidate) for candidate in candidates]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{args.backend_label}"
    output = args.output / run_id
    raw_root = output / "raw"
    raw_root.mkdir(parents=True, exist_ok=False)
    all_rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, candidate in enumerate(candidates, start=1):
        print(f"[{index}/{len(candidates)}] {candidate.label} ({args.backend_label})", flush=True)
        for suite in ("polish", "prompts"):
            try:
                run_dir = run_e2e(
                    candidate,
                    suite=suite,
                    runtime=runtime,
                    device=args.device,
                    runs=max(1, args.runs),
                    config=args.config,
                    cases=args.cases,
                    output=raw_root / candidate.id / suite,
                    timeout_seconds=args.suite_timeout_seconds,
                )
                rows = load_rows(run_dir)
                for row_index, row in enumerate(rows):
                    row["benchmark_model_id"] = candidate.id
                    row["benchmark_model_label"] = candidate.label
                    row["benchmark_backend"] = args.backend_label
                    row["benchmark_suite_run"] = suite
                    row["benchmark_row_index"] = row_index
                all_rows.extend(rows)
            except Exception as exc:
                failures.append({"model": candidate.id, "suite": suite, "error": str(exc)})
                print(f"  {suite}: ERROR {exc}", flush=True)

    summaries = [summarize_candidate(candidate, all_rows) for candidate in candidates]
    summaries.sort(key=ranking_key)
    strict_gate_failures = sum(summary["safety_failures"] for summary in summaries)
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime": str(runtime),
        "device": args.device,
        "backend": args.backend_label,
        "runs_per_case": max(1, args.runs),
        "suites": ["polish", "prompts"],
        "strict_gates": True,
        "strict_gate_failures": strict_gate_failures,
        "suite_timeout_seconds": args.suite_timeout_seconds,
        "evidence_captured_at": evidence_captured_at,
        "inputs": input_evidence,
        "candidates": candidates_evidence,
        "execution_failures": failures,
    }
    write_outputs(output, manifest, summaries, all_rows)
    print_leaderboard(output, summaries, failures)
    return 1 if failures or strict_gate_failures else 0


def discover_candidates(models_dir: Path, *, include_baselines: bool) -> list[Candidate]:
    candidates: list[Candidate] = []
    for model_id, label, filename in NEW_MODELS:
        path = (models_dir / filename).resolve()
        if path.is_file():
            candidates.append(Candidate(model_id, label, path, "downloaded"))
    if include_baselines:
        for model_id, label, manifest_name in BASELINES:
            path = ollama_model_blob(manifest_name)
            if path is not None:
                candidates.append(Candidate(model_id, label, path, "ollama-baseline"))
    return candidates


def ollama_model_blob(manifest_name: str) -> Path | None:
    root = Path.home() / ".ollama" / "models"
    manifest_path = root / "manifests" / "registry.ollama.ai" / Path(manifest_name)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for layer in payload.get("layers") or []:
        if layer.get("mediaType") != "application/vnd.ollama.image.model":
            continue
        digest = str(layer.get("digest") or "")
        path = root / "blobs" / digest.replace(":", "-", 1)
        return path.resolve() if path.is_file() else None
    return None


def run_e2e(
    candidate: Candidate,
    *,
    suite: str,
    runtime: Path,
    device: str,
    runs: int,
    config: Path,
    cases: Path,
    output: Path,
    timeout_seconds: float = DEFAULT_SUITE_TIMEOUT_SECONDS,
) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    before = {path.resolve() for path in output.iterdir() if path.is_dir()}
    command = [
        sys.executable,
        "-m",
        "devtools.e2e_lab",
        "--config",
        str(config),
        "--cases",
        str(cases),
        "--output",
        str(output),
        "--suite",
        suite,
        "--polish-runs",
        str(runs),
        "--rewrite-runs",
        str(runs),
        "--rewrite-provider",
        "embedded",
        "--llama-server-path",
        str(runtime),
        "--llama-model-path",
        str(candidate.path),
        "--llama-model-id",
        candidate.id,
        "--llama-device",
        device,
        "--fail-on-gate",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        detail = bounded_tail(exc.stderr or exc.stdout)
        message = (
            f"E2E suite '{suite}' timed out after {timeout_seconds:g} seconds "
            f"for model '{candidate.id}'"
        )
        if detail:
            message += f". Last output: {detail}"
        raise RuntimeError(message) from exc
    if completed.stdout.strip():
        print(indent(bounded_tail(completed.stdout)), flush=True)
    created = sorted(
        (path.resolve() for path in output.iterdir() if path.is_dir() and path.resolve() not in before),
        key=lambda path: path.stat().st_mtime_ns,
    )
    if not created:
        raise RuntimeError("E2E produced no run directory.")
    if completed.returncode not in {0, 2}:
        detail = bounded_tail(completed.stderr or completed.stdout, limit=1200)
        raise RuntimeError(detail or f"E2E exited with {completed.returncode}")
    if completed.returncode == 2 and completed.stderr.strip():
        print(indent("Strict gate failures recorded:\n" + bounded_tail(completed.stderr, limit=1200)), flush=True)
    return created[-1]


def load_rows(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "results.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize_candidate(candidate: Candidate, all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in all_rows if row.get("benchmark_model_id") == candidate.id]
    inference = [row for row in rows if row.get("kind") in {"polish", "rewrite"}]
    cold_rows: list[dict[str, Any]] = []
    warm_rows: list[dict[str, Any]] = []
    for suite in ("polish", "prompts"):
        suite_rows = [row for row in inference if row.get("benchmark_suite_run") == suite]
        if suite_rows:
            cold_rows.append(suite_rows[0])
            warm_rows.extend(suite_rows[1:])
    scores = [float(row["score"]) for row in inference if isinstance(row.get("score"), (int, float))]
    gated_failures = [
        row
        for row in inference
        if row.get("gate") and row.get("status") in {"fail", "error"}
    ]
    case_outputs: dict[str, set[str]] = {}
    for row in inference:
        case_id = re.sub(r"#run-\d+$", "", str(row.get("case_id") or ""))
        normalized = " ".join(str(row.get("actual") or "").casefold().split())
        case_outputs.setdefault(case_id, set()).add(normalized)
    consistent_cases = sum(len(outputs) <= 1 for outputs in case_outputs.values())
    memories = metric_values(inference, "backend_memory_mb")
    vram = metric_values(inference, "backend_vram_mb")
    token_rates = metric_values(inference, "llama_predicted_per_second")
    return {
        "id": candidate.id,
        "label": candidate.label,
        "path": str(candidate.path),
        "source": candidate.source,
        "size_mb": candidate.path.stat().st_size / (1024 * 1024),
        "executions": len(inference),
        "passed": sum(row.get("status") == "pass" for row in inference),
        "failed": sum(row.get("status") in {"fail", "error"} for row in inference),
        "pass_rate": safe_ratio(sum(row.get("status") == "pass" for row in inference), len(inference)),
        "quality_points": sum(scores),
        "quality_max": len(scores) * 3,
        "quality_percent": safe_ratio(sum(scores), len(scores) * 3),
        "safety_failures": len(gated_failures),
        "failed_gates": sorted({str(row.get("gate")) for row in gated_failures}),
        "cold_median_ms": median([float(row["latency_ms"]) for row in cold_rows]),
        "warm_median_ms": median([float(row["latency_ms"]) for row in warm_rows]),
        "warm_p95_ms": percentile([float(row["latency_ms"]) for row in warm_rows], 95),
        "tokens_per_second": median(token_rates),
        "backend_memory_peak_mb": max(memories) if memories else None,
        "backend_vram_peak_mb": max(vram) if vram else None,
        "consistency_percent": safe_ratio(consistent_cases, len(case_outputs)),
        "failure_details": [
            {
                "case_id": row.get("case_id"),
                "gate": row.get("gate"),
                "score": row.get("score"),
                "notes": row.get("notes"),
                "actual": row.get("actual"),
            }
            for row in inference
            if row.get("status") in {"fail", "error"}
        ],
    }


def ranking_key(summary: dict[str, Any]) -> tuple:
    return (
        summary["safety_failures"],
        -(summary["quality_percent"] or 0),
        summary["warm_median_ms"] or float("inf"),
    )


def write_outputs(
    output: Path,
    manifest: dict[str, Any],
    summaries: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> None:
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    with (output / "results.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (output / "report.md").write_text(render_report(manifest, summaries), encoding="utf-8")


def render_report(manifest: dict[str, Any], summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# Winsper Polish model matrix",
        "",
        f"Backend: `{manifest['backend']}` (`{manifest['device']}`)",
        f"Runtime: `{manifest['runtime']}`",
        f"Repeated runs per production case: {manifest['runs_per_case']}",
        f"Strict safety gates: {'enabled' if manifest.get('strict_gates') else 'disabled'}",
        f"Per-suite wall timeout: {number(manifest.get('suite_timeout_seconds'))} seconds",
        "",
        "| Rank | Model | Quality | Safety failures | Warm median | Warm P95 | tok/s | RAM peak | VRAM peak | Consistency |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, summary in enumerate(summaries, start=1):
        lines.append(
            f"| {rank} | {summary['label']} | {percent(summary['quality_percent'])} | "
            f"{summary['safety_failures']} | {number(summary['warm_median_ms'])} ms | "
            f"{number(summary['warm_p95_ms'])} ms | {number(summary['tokens_per_second'])} | "
            f"{number(summary['backend_memory_peak_mb'])} MB | {number(summary['backend_vram_peak_mb'])} MB | "
            f"{percent(summary['consistency_percent'])} |"
        )
    inputs = manifest.get("inputs") or {}
    lines.extend(["", "## Reproducibility", ""])
    for key in ("config", "cases", "runtime"):
        item = inputs.get(key) or {}
        lines.append(f"- {key.title()} `{item.get('id') or 'unknown'}`: `{item.get('sha256') or 'missing'}`")
    prompt = inputs.get("prompt_implementation") or {}
    lines.append(f"- Prompt pipeline `{prompt.get('id') or 'unknown'}`: `{prompt.get('sha256') or 'missing'}`")
    for candidate in manifest.get("candidates") or []:
        lines.append(f"- Model `{candidate.get('id') or 'unknown'}`: `{candidate.get('sha256') or 'missing'}`")
    lines.extend(["", "## Failures", ""])
    for summary in summaries:
        lines.append(f"### {summary['label']}")
        if not summary["failure_details"]:
            lines.extend(["", "None.", ""])
            continue
        lines.append("")
        for failure in summary["failure_details"]:
            lines.append(
                f"- `{failure['case_id']}` gate `{failure['gate'] or 'none'}`: "
                f"{failure['notes'] or 'constraint failure'} → {failure['actual']}"
            )
        lines.append("")
    if manifest["execution_failures"]:
        lines.extend(["## Execution errors", ""])
        for failure in manifest["execution_failures"]:
            lines.append(f"- `{failure['model']}/{failure['suite']}`: {failure['error']}")
        lines.append("")
    return "\n".join(lines)


def print_leaderboard(output: Path, summaries: list[dict[str, Any]], failures: list[dict[str, str]]) -> None:
    for rank, summary in enumerate(summaries, start=1):
        print(
            f"{rank}. {summary['label']}: quality {percent(summary['quality_percent'])}, "
            f"safety {summary['safety_failures']}, warm p50 {number(summary['warm_median_ms'])} ms",
            flush=True,
        )
    if failures:
        print(f"Execution errors: {len(failures)}", flush=True)
    print(f"Report: {output / 'report.md'}", flush=True)


def metric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = (row.get("metrics") or {}).get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def percentile(values: list[float], percentage: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentage / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def safe_ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1f}"


def indent(value: str) -> str:
    return "\n".join(f"  {line}" for line in value.splitlines())


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be a finite number greater than zero")
    return seconds


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_evidence(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    exists = resolved.is_file()
    return {
        "id": path.name,
        "path": str(resolved),
        "exists": exists,
        "size_bytes": resolved.stat().st_size if exists else None,
        "sha256": sha256_file(resolved) if exists else None,
    }


def source_bundle_evidence(paths: tuple[Path, ...]) -> dict[str, Any]:
    files = [file_evidence(path) for path in paths]
    digest = hashlib.sha256()
    for item in files:
        digest.update(str(item["id"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["sha256"] or "missing").encode("ascii"))
        digest.update(b"\0")
    return {
        "id": "winsper-polish-prompt-pipeline",
        "sha256": digest.hexdigest(),
        "files": files,
    }


def candidate_evidence(candidate: Candidate) -> dict[str, Any]:
    evidence = file_evidence(candidate.path)
    return {
        **asdict(candidate),
        "path": str(candidate.path),
        "size_bytes": evidence["size_bytes"],
        "sha256": evidence["sha256"],
    }


def bounded_tail(value: str | bytes | None, *, limit: int = 4000) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value or "").strip()[-limit:]


if __name__ == "__main__":
    raise SystemExit(main())
