from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from voicepilot.config import ProfileStyle, load_config
from .e2e_lab import first_word_matches, load_cases, token_recall
from .model_matrix import discover_candidates
from voicepilot.rewrite import TextRewriter
from voicepilot.speed_lab import score_transcript


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Polish real ASR outputs with candidate embedded models.")
    parser.add_argument("--asr-results", type=Path, required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--models-dir", type=Path, default=Path("models_test"))
    parser.add_argument("--names", default="llama3.2-3b,qwen3-8b")
    parser.add_argument("--device", default="CUDA0")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--cases", type=Path, default=Path("e2e/cases.yaml"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/model-benchmark"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    names = {item.strip() for item in args.names.split(",") if item.strip()}
    candidates = [
        candidate
        for candidate in discover_candidates(args.models_dir, include_baselines=True)
        if candidate.id in names
    ]
    missing = names - {candidate.id for candidate in candidates}
    if missing:
        raise RuntimeError("Missing candidates: " + ", ".join(sorted(missing)))
    source_rows = [
        json.loads(line)
        for line in args.asr_results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    source_rows = [
        row
        for row in source_rows
        if row.get("suite") == "asr"
        and row.get("status") != "skip"
        and str(row.get("expected") or "").strip()
        and str(row.get("actual") or "").strip()
    ]
    protected_by_case = {
        str(case.get("id") or ""): [str(item) for item in case.get("protected") or []]
        for case in load_cases(args.cases)
    }
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-audio-polish"
    output = args.output / run_id
    output.mkdir(parents=True, exist_ok=False)
    all_rows: list[dict[str, Any]] = []
    config = load_config(args.config)
    for index, candidate in enumerate(candidates, start=1):
        print(f"[{index}/{len(candidates)}] {candidate.label}", flush=True)
        rewrite_config = replace(
            config.rewrite,
            provider="embedded",
            llama_server_path=str(args.runtime.resolve()) if args.runtime is not None else "",
            llama_model_path=str(candidate.path),
            llama_device=args.device,
        )
        with TextRewriter(rewrite_config, config.vocabulary) as rewriter:
            rewriter.warm_up()
            for source in source_rows:
                started = time.perf_counter()
                output_text = rewriter.polish(
                    str(source["actual"]),
                    profile=ProfileStyle(label="Audio E2E"),
                    app_label="Winsper audio E2E",
                    language=str(source.get("language") or config.speech.language),
                ).strip()
                latency_ms = (time.perf_counter() - started) * 1000
                base_case_id = str(source.get("case_id") or "").split("#", 1)[0]
                all_rows.append(
                    score_polished_output(
                        candidate.id,
                        source,
                        output_text,
                        latency_ms,
                        protected_by_case.get(base_case_id, []),
                    )
                )
    summaries = summarize(all_rows)
    (output / "results.json").write_text(json.dumps(all_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    (output / "report.md").write_text(render_report(summaries, all_rows), encoding="utf-8")
    for model_id, summary in summaries.items():
        print(
            f"{model_id}: WER {summary['raw_wer']:.3f} -> {summary['polished_wer']:.3f}; "
            f"improved {summary['improved']}, worsened {summary['worsened']}; "
            f"protected {summary['protected_accuracy']:.1%}",
            flush=True,
        )
    print(f"Report: {output / 'report.md'}", flush=True)
    return 0


def score_polished_output(
    model_id: str,
    source: dict[str, Any],
    polished: str,
    latency_ms: float,
    protected: list[str],
) -> dict[str, Any]:
    expected = str(source["expected"])
    raw = str(source["actual"])
    raw_score = score_transcript(raw, expected)
    polished_score = score_transcript(polished, expected)
    raw_wer = raw_score.word_error_rate if raw_score is not None else 1.0
    polished_wer = polished_score.word_error_rate if polished_score is not None else 1.0
    return {
        "model_id": model_id,
        "speech_model": source.get("model"),
        "case_id": source.get("case_id"),
        "raw": raw,
        "polished": polished,
        "expected": expected,
        "raw_wer": raw_wer,
        "polished_wer": polished_wer,
        "wer_delta": polished_wer - raw_wer,
        "protected_accuracy": token_recall(polished, protected),
        "first_word_ok": first_word_matches(polished, expected),
        "latency_ms": latency_ms,
        "protected_terms": protected,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for model_id in sorted({str(row["model_id"]) for row in rows}):
        selected = [row for row in rows if row["model_id"] == model_id]
        protected = [
            float(row["protected_accuracy"])
            for row in selected
            if isinstance(row.get("protected_accuracy"), (int, float))
        ]
        summaries[model_id] = {
            "executions": len(selected),
            "raw_wer": statistics.fmean(float(row["raw_wer"]) for row in selected),
            "polished_wer": statistics.fmean(float(row["polished_wer"]) for row in selected),
            "improved": sum(float(row["wer_delta"]) < -1e-9 for row in selected),
            "unchanged": sum(abs(float(row["wer_delta"])) <= 1e-9 for row in selected),
            "worsened": sum(float(row["wer_delta"]) > 1e-9 for row in selected),
            "protected_accuracy": statistics.fmean(protected) if protected else 1.0,
            "median_latency_ms": statistics.median(float(row["latency_ms"]) for row in selected),
        }
    return summaries


def render_report(summaries: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Winsper real-audio polish benchmark",
        "",
        "| Model | Raw WER | Polished WER | Improved | Unchanged | Worsened | Protected | Median latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model_id, summary in summaries.items():
        lines.append(
            f"| {model_id} | {summary['raw_wer']:.3f} | {summary['polished_wer']:.3f} | "
            f"{summary['improved']} | {summary['unchanged']} | {summary['worsened']} | "
            f"{summary['protected_accuracy']:.1%} | {summary['median_latency_ms']:.1f} ms |"
        )
    lines.extend(["", "## Changed transcripts", ""])
    for row in rows:
        if abs(float(row["wer_delta"])) <= 1e-9:
            continue
        lines.extend(
            [
                f"### {row['model_id']} / {row['speech_model']} / {row['case_id']}",
                "",
                f"- Raw: {row['raw']}",
                f"- Polished: {row['polished']}",
                f"- Expected: {row['expected']}",
                f"- WER delta: {row['wer_delta']:+.3f}",
                "",
            ]
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
