"""Aggregate blinded end-to-end results collected from Winsper and competitors."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from voicepilot.speed_lab import score_transcript
from .e2e_lab import first_word_captured


REQUIRED_COLUMNS = {
    "product",
    "product_version",
    "mode",
    "case_id",
    "run_number",
    "cold_warm",
    "expected",
    "actual",
    "ready_latency_ms",
    "result_latency_ms",
    "inserted_ok",
    "wrong_target",
    "cancel_leak",
    "hallucination",
    "meaning_score_1_5",
    "format_score_1_5",
}


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _number(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Missing benchmark columns: " + ", ".join(sorted(missing)))
        return list(reader)


def summarize(rows: list[dict[str, str]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[
            (
                row["product"].strip(),
                row["product_version"].strip(),
                row["mode"].strip(),
                row["cold_warm"].strip(),
            )
        ].append(row)

    output: dict[str, Any] = {}
    for (product, version, mode, cold_warm), group in sorted(groups.items()):
        wer_values: list[float] = []
        ready = [value for row in group if (value := _number(row["ready_latency_ms"])) is not None]
        result = [value for row in group if (value := _number(row["result_latency_ms"])) is not None]
        meaning = [value for row in group if (value := _number(row.get("meaning_score_1_5"))) is not None]
        formatting = [value for row in group if (value := _number(row.get("format_score_1_5"))) is not None]
        first_word_samples = 0
        first_word_passes = 0
        for row in group:
            expected = row["expected"].strip()
            actual = row["actual"].strip()
            if expected:
                score = score_transcript(actual, expected)
                if score is not None:
                    wer_values.append(score.word_error_rate)
                first_word_samples += 1
                first_word_passes += first_word_captured(actual, expected)
        output[f"{product}|{version}|{mode}|{cold_warm}"] = {
            "product": product,
            "product_version": version,
            "mode": mode,
            "cold_warm": cold_warm,
            "samples": len(group),
            "mean_wer": statistics.fmean(wer_values) if wer_values else None,
            "first_word_rate": first_word_passes / first_word_samples if first_word_samples else None,
            "mean_meaning_score": statistics.fmean(meaning) if meaning else None,
            "mean_format_score": statistics.fmean(formatting) if formatting else None,
            "inserted_ok_rate": statistics.fmean(1.0 if _truthy(row["inserted_ok"]) else 0.0 for row in group),
            "wrong_target_count": sum(_truthy(row["wrong_target"]) for row in group),
            "cancel_leak_count": sum(_truthy(row["cancel_leak"]) for row in group),
            "hallucination_count": sum(_truthy(row["hallucination"]) for row in group),
            "ready_latency_p50_ms": _percentile(ready, 0.50),
            "ready_latency_p95_ms": _percentile(ready, 0.95),
            "result_latency_p50_ms": _percentile(result, 0.50),
            "result_latency_p95_ms": _percentile(result, 0.95),
        }
    return {"groups": output}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a blinded Winsper/competitor benchmark CSV.")
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/manual-benchmark/summary.json"))
    args = parser.parse_args()
    summary = summarize(load_rows(args.results))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
