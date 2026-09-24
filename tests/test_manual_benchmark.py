from __future__ import annotations

import pytest

from devtools.manual_benchmark import summarize


def result_row(**overrides: str) -> dict[str, str]:
    row = {
        "product": "Winsper",
        "product_version": "1.0.1",
        "mode": "Dictate",
        "case_id": "case-1",
        "run_number": "1",
        "cold_warm": "warm",
        "expected": "Send the report tomorrow",
        "actual": "Send the report tomorrow",
        "ready_latency_ms": "40",
        "result_latency_ms": "200",
        "inserted_ok": "yes",
        "wrong_target": "no",
        "cancel_leak": "no",
        "hallucination": "no",
        "meaning_score_1_5": "5",
        "format_score_1_5": "5",
    }
    row.update(overrides)
    return row


def test_manual_benchmark_reports_quality_latency_and_safety():
    summary = summarize(
        [
            result_row(),
            result_row(
                run_number="2",
                actual="Send report tomorrow",
                ready_latency_ms="60",
                result_latency_ms="300",
                inserted_ok="no",
                wrong_target="yes",
            ),
        ]
    )["groups"]["Winsper|1.0.1|Dictate|warm"]

    assert summary["samples"] == 2
    assert summary["mean_wer"] == pytest.approx(0.125)
    assert summary["first_word_rate"] == 1.0
    assert summary["inserted_ok_rate"] == 0.5
    assert summary["wrong_target_count"] == 1
    assert summary["mean_meaning_score"] == 5
    assert summary["mean_format_score"] == 5
    assert summary["ready_latency_p50_ms"] == 50
    assert summary["ready_latency_p95_ms"] == 59
    assert summary["result_latency_p50_ms"] == 250
    assert summary["result_latency_p95_ms"] == 295


def test_manual_benchmark_keeps_products_and_modes_separate():
    groups = summarize(
        [
            result_row(),
            result_row(product="Aqua", product_version="current"),
            result_row(mode="Polish"),
        ]
    )["groups"]

    assert set(groups) == {
        "Aqua|current|Dictate|warm",
        "Winsper|1.0.1|Dictate|warm",
        "Winsper|1.0.1|Polish|warm",
    }
