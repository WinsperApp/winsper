from __future__ import annotations

import pytest

from voicepilot import benchmark
from voicepilot import __main__ as voicepilot_main
from voicepilot.speed_lab import SpeedLabStore, create_benchmark_result, result_from_dict


class _Transcriber:
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, _clip) -> str:
        self.calls += 1
        return "ok"


def test_warm_transcription_samples_preserve_each_run(monkeypatch) -> None:
    clock = iter((1.0, 1.1, 2.0, 2.2, 3.0, 3.4))
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(clock))
    transcriber = _Transcriber()

    samples = benchmark.run_warm_transcription_samples(transcriber, object(), 3)

    assert samples == pytest.approx([0.1, 0.2, 0.4])
    assert transcriber.calls == 3


def test_percentile_interpolates_distribution() -> None:
    samples = [0.4, 0.1, 0.3, 0.2]

    assert benchmark.percentile(samples, 50) == pytest.approx(0.25)
    assert benchmark.percentile(samples, 95) == pytest.approx(0.385)
    assert benchmark.percentile([], 95) == 0.0


def test_benchmark_entry_points_default_to_five_warm_runs() -> None:
    assert benchmark.build_parser().parse_args([]).warm_runs == 5
    assert voicepilot_main.build_parser().parse_args([]).warm_runs == 5


def test_warm_timing_summary_reports_real_distribution() -> None:
    lines = benchmark.format_warm_timing_lines([0.1, 0.2, 0.4])

    assert lines[0] == "Warm transcription samples: 3"
    assert lines[1] == "Warm transcription average: 0.23s"
    assert lines[2] == "Warm transcription distribution: p50=0.20s p95=0.38s max=0.40s"


def test_single_warm_timing_is_not_presented_as_distribution() -> None:
    lines = benchmark.format_warm_timing_lines([0.25])

    assert lines == [
        "Warm transcription samples: 1",
        "Warm transcription time: 0.25s",
    ]
    assert all("distribution" not in line.lower() for line in lines)


def test_speed_lab_persists_warm_timing_distribution(tmp_path) -> None:
    store = SpeedLabStore(tmp_path / "speed.json")
    result = create_benchmark_result(
        model="small.en",
        device="cpu",
        compute_type="int8",
        recorded_seconds=5.0,
        transcribed_seconds=4.5,
        load_seconds=0.3,
        transcription_seconds=0.8,
        transcript="hello",
        warm_transcription_seconds=0.23,
        warm_sample_count=3,
        warm_p50_seconds=0.2,
        warm_p95_seconds=0.38,
        warm_max_seconds=0.4,
    )

    store.append(result)
    loaded = store.list()

    assert len(loaded) == 1
    assert loaded[0].warm_transcription_seconds == pytest.approx(0.23)
    assert loaded[0].warm_sample_count == 3
    assert loaded[0].warm_p50_seconds == pytest.approx(0.2)
    assert loaded[0].warm_p95_seconds == pytest.approx(0.38)
    assert loaded[0].warm_max_seconds == pytest.approx(0.4)


def test_speed_lab_reads_legacy_results_without_warm_distribution() -> None:
    result = result_from_dict(
        {
            "model": "base.en",
            "device": "cpu",
            "compute_type": "int8",
            "warm_transcription_seconds": 0.25,
        }
    )

    assert result is not None
    assert result.warm_transcription_seconds == pytest.approx(0.25)
    assert result.warm_sample_count == 0
    assert result.warm_p50_seconds == 0.0
    assert result.warm_p95_seconds == 0.0
    assert result.warm_max_seconds == 0.0
