from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path
from dataclasses import replace

from .audio import read_wav, write_wav
from .audio_factory import create_audio_recorder
from .config import load_config, resolve_config_path
from .models import find_speech_model, installed_status
from .speed_lab import SpeedLabStore, create_benchmark_result, speed_lab_clip_path_for_config
from .transcribe import FasterWhisperTranscriber
from .vocabulary import effective_vocabulary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark local Winsper transcription.")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--model", default=None, help="Override speech.model, e.g. base.en or small.en.")
    parser.add_argument("--models", default=None, help="Comma-separated models to benchmark from one recording.")
    parser.add_argument("--device", default=None, help="Override speech.device, e.g. cpu or cuda.")
    parser.add_argument("--compute-type", default=None, help="Override speech.compute_type, e.g. int8 or float16.")
    parser.add_argument("--seconds", type=int, default=5, help="Recording duration.")
    parser.add_argument("--audio-file", type=Path, default=None, help="Reuse a WAV clip instead of recording.")
    parser.add_argument("--save-clip", action="store_true", help="Save the recorded clip for repeatable benchmark runs.")
    parser.add_argument("--expected-text", default="", help="Expected transcript for accuracy scoring.")
    parser.add_argument("--expected-file", type=Path, default=None, help="Read expected transcript text from a file.")
    parser.add_argument("--warm-runs", type=int, default=5, help="Extra warm transcriptions after the first pass.")
    parser.add_argument("--no-save", action="store_true", help="Do not save results to speed_benchmarks.json.")
    return parser


def main() -> int:
    return run_benchmark(build_parser().parse_args())


def run_benchmark(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.model:
        config.speech.model = args.model
    if args.device:
        config.speech.device = args.device
    if args.compute_type:
        config.speech.compute_type = args.compute_type

    models = parse_models(args.models) or [config.speech.model]
    config_path = resolve_config_path(args.config)
    expected_text = load_expected_text(args.expected_text, args.expected_file)

    for model in models:
        preset = find_speech_model(model)
        if preset is not None and not installed_status(preset, include_size=False).installed:
            print(f"{model} is not installed yet. First run will download it once.")

    if args.audio_file:
        clip = read_wav(args.audio_file)
        print(f"Loaded benchmark clip: {args.audio_file}")
    else:
        recorder = create_audio_recorder(config.audio)
        try:
            print(f"Recording {args.seconds}s once. Speak after the beep line.")
            print("=== START SPEAKING ===")
            recorder.start()
            time.sleep(args.seconds)
            clip = recorder.stop()
            if args.save_clip:
                clip_path = speed_lab_clip_path_for_config(config_path)
                write_wav(clip, clip_path)
                print(f"Saved benchmark clip to {clip_path}")
        finally:
            recorder.close()
    raw_duration = clip.raw_duration_seconds or clip.duration_seconds
    print(f"Recorded {raw_duration:.2f}s; benchmark audio is {clip.duration_seconds:.2f}s after silence trim.")
    if expected_text:
        print(f"Accuracy scoring enabled against {len(expected_text.split())} expected words.")
    print("")

    store = SpeedLabStore.for_config(config_path)
    vocabulary = effective_vocabulary(config)
    for model in models:
        base_transcriber = FasterWhisperTranscriber(config.speech, vocabulary)
        speech_config = base_transcriber.mode_config(model)
        if args.device:
            speech_config = replace(speech_config, device=args.device)
        if args.compute_type:
            speech_config = replace(speech_config, compute_type=args.compute_type)
        transcriber = FasterWhisperTranscriber(speech_config, vocabulary)
        print(f"Preparing {model} on {speech_config.device}/{speech_config.compute_type}...")
        load_started = time.perf_counter()
        _ = transcriber.model
        load_elapsed = time.perf_counter() - load_started
        print(f"Model ready in {load_elapsed:.2f}s.")
        print(f"Transcribing with {model}...")
        started = time.perf_counter()
        text = transcriber.transcribe(clip)
        elapsed = time.perf_counter() - started
        warm_timings = run_warm_transcription_samples(transcriber, clip, max(0, args.warm_runs))
        warm_elapsed = statistics.fmean(warm_timings) if warm_timings else 0.0
        result = create_benchmark_result(
            model=model,
            device=speech_config.device,
            compute_type=speech_config.compute_type,
            recorded_seconds=raw_duration,
            transcribed_seconds=clip.duration_seconds,
            load_seconds=load_elapsed,
            transcription_seconds=elapsed,
            transcript=text,
            expected_text=expected_text,
            warm_transcription_seconds=warm_elapsed,
            warm_sample_count=len(warm_timings),
            warm_p50_seconds=percentile(warm_timings, 50),
            warm_p95_seconds=percentile(warm_timings, 95),
            warm_max_seconds=max(warm_timings, default=0.0),
        )
        if not args.no_save:
            store.append(result)
        print("")
        print(f"Model: {model}")
        print("Transcript:")
        print(text or "(empty)")
        print(f"Load time: {load_elapsed:.2f}s")
        print(f"Transcription time: {elapsed:.2f}s")
        for line in format_warm_timing_lines(warm_timings):
            print(line)
        print(f"Cold total: {load_elapsed + elapsed:.2f}s")
        print(f"Realtime factor: {result.realtime_factor:.2f}x")
        if result.accuracy_score is not None and result.word_error_rate is not None:
            print(f"Accuracy score: {result.accuracy_score:.0%}")
            print(f"Word error rate: {result.word_error_rate:.0%}")
        print("")
    if not args.no_save:
        print(f"Saved benchmark results to {store.path}")
    return 0


def parse_models(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def load_expected_text(value: str, path: Path | None) -> str:
    if path is None:
        return value.strip()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Could not read expected transcript file {path}: {exc}") from exc


def run_warm_transcriptions(transcriber: FasterWhisperTranscriber, clip, warm_runs: int) -> float:
    timings = run_warm_transcription_samples(transcriber, clip, warm_runs)
    return statistics.fmean(timings) if timings else 0.0


def run_warm_transcription_samples(transcriber: FasterWhisperTranscriber, clip, warm_runs: int) -> list[float]:
    timings: list[float] = []
    for _index in range(warm_runs):
        started = time.perf_counter()
        transcriber.transcribe(clip)
        timings.append(time.perf_counter() - started)
    return timings


def percentile(samples: list[float], value: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * max(0.0, min(100.0, value)) / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def format_warm_timing_lines(samples: list[float]) -> list[str]:
    if not samples:
        return []
    lines = [f"Warm transcription samples: {len(samples)}"]
    if len(samples) == 1:
        lines.append(f"Warm transcription time: {samples[0]:.2f}s")
        return lines
    lines.extend(
        [
            f"Warm transcription average: {statistics.fmean(samples):.2f}s",
            (
                "Warm transcription distribution: "
                f"p50={percentile(samples, 50):.2f}s "
                f"p95={percentile(samples, 95):.2f}s "
                f"max={max(samples):.2f}s"
            ),
        ]
    )
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
