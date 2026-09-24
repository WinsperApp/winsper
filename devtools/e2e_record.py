from __future__ import annotations

import argparse
import math
import time
from dataclasses import replace
from pathlib import Path

from voicepilot.audio import write_wav
from voicepilot.audio_factory import create_audio_recorder
from voicepilot.config import load_config
from .e2e_lab import load_cases


SOLO_TESTER_LANGUAGES = ("en", "hi", "mix-hi-en")
READING_WORDS_PER_SECOND = 2.0
READING_BUFFER_SECONDS = 2.0


def recording_seconds(expected: str, minimum_seconds: float) -> float:
    minimum = max(0.5, float(minimum_seconds))
    word_count = len(expected.split())
    if not word_count:
        return minimum
    estimated = math.ceil((word_count / READING_WORDS_PER_SECOND) + READING_BUFFER_SECONDS)
    return max(minimum, float(estimated))


def _language_filter(values: list[str]) -> set[str]:
    return {
        language.strip().casefold()
        for value in values
        for language in value.split(",")
        if language.strip()
    }


def filter_recording_cases(
    cases: list[dict],
    *,
    speaker: str = "",
    category: str = "",
    languages: list[str] | None = None,
    solo_tester: bool = False,
) -> list[dict]:
    if solo_tester and speaker:
        raise ValueError("--solo-tester cannot be combined with --speaker.")
    selected_languages = _language_filter(languages or [])
    if solo_tester:
        supported = set(SOLO_TESTER_LANGUAGES)
        selected_languages = selected_languages or supported
        unsupported = selected_languages - supported
        if unsupported:
            raise ValueError(
                "The solo launch lane supports only en, hi, and mix-hi-en; got "
                + ", ".join(sorted(unsupported))
                + "."
            )

    selected = cases
    if speaker:
        selected = [case for case in selected if str(case.get("speaker") or "speaker-a") == speaker]
    if category:
        selected = [case for case in selected if str(case.get("category") or "") == category]
    if selected_languages:
        selected = [
            case
            for case in selected
            if str(case.get("language") or "").strip().casefold() in selected_languages
        ]
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record the real-voice Winsper E2E corpus.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--cases", type=Path, default=Path("e2e/cases.yaml"))
    parser.add_argument("--case", default="", help="Record one ASR case ID instead of every missing clip.")
    parser.add_argument("--speaker", default="", help="Record only cases assigned to this speaker.")
    parser.add_argument("--category", default="", help="Record only one corpus category.")
    parser.add_argument(
        "--language",
        action="append",
        default=[],
        help="Record one language code; repeat it or pass comma-separated codes.",
    )
    parser.add_argument(
        "--solo-tester",
        action="store_true",
        help="Ignore speaker assignments and record the English, Hindi, and Hinglish launch lane.",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        help="Minimum recording time; longer phrases automatically receive more time.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--list", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = [case for case in load_cases(args.cases) if case.get("suite") == "asr" and case.get("kind") == "asr"]
    try:
        cases = filter_recording_cases(
            cases,
            speaker=args.speaker,
            category=args.category,
            languages=args.language,
            solo_tester=args.solo_tester,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.case:
        cases = [case for case in cases if case.get("id") == args.case]
        if not cases:
            raise SystemExit(f"Unknown ASR case: {args.case}")
    if args.list:
        for case in cases:
            destination = args.cases.parent / str(case.get("audio") or "")
            state = "recorded" if destination.exists() else "missing"
            language = str(case.get("language") or "unspecified")
            print(f"{case.get('id')} [{language}]: {state} -> {destination}")
        recorded = sum((args.cases.parent / str(case.get("audio") or "")).exists() for case in cases)
        print(f"\n{recorded}/{len(cases)} selected clips recorded; {len(cases) - recorded} missing.")
        return 0

    config = load_config(args.config)
    audio_config = replace(config.audio, min_record_seconds=0.0)
    recorded = 0
    for case in cases:
        destination = args.cases.parent / str(case.get("audio") or "")
        if destination.exists() and not args.overwrite:
            print(f"Skipping existing clip: {destination}")
            continue
        expected = str(case.get("expected") or "")
        category = str(case.get("category") or "")
        speaker = "solo tester" if args.solo_tester else str(case.get("speaker") or "speaker-a")
        language = str(case.get("language") or "unspecified")
        environment = str(case.get("environment") or "clean")
        print("\n" + "=" * 72)
        print(f"{case.get('id')} [{category}, {language}] - {speaker}, {environment}")
        if expected:
            print(f'Read exactly: "{expected}"')
        elif category == "silence":
            print("Remain silent for this recording.")
        else:
            print("Produce only the requested background noise; do not speak.")
        duration_seconds = recording_seconds(expected, args.seconds)
        print(f"Recording window: {duration_seconds:.0f} seconds.")
        input("Press Enter when ready...")
        for remaining in range(3, 0, -1):
            print(f"{remaining}...", flush=True)
            time.sleep(1)

        recorder = create_audio_recorder(audio_config)
        try:
            recorder.warm_up()
            metrics = recorder.start()
            print("Recording...", flush=True)
            time.sleep(duration_seconds)
            clip = recorder.stop()
        finally:
            recorder.close()
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_wav(clip, destination)
        print(
            f"Saved {clip.raw_duration_seconds or clip.duration_seconds:.2f}s to {destination} "
            f"(first frame {metrics.first_frame_ms:.1f}ms, attempts {metrics.attempts})."
        )
        recorded += 1
    print(f"\nRecorded {recorded} clip(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
