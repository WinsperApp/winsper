from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from voicepilot.audio import AudioClip, write_wav
from .e2e_lab import load_cases


DEFAULT_VOICES = ("Microsoft David Desktop", "Microsoft Zira Desktop")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a labelled synthetic Winsper ASR corpus with Windows TTS.")
    parser.add_argument("--cases", type=Path, default=Path("e2e/cases.yaml"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/e2e/synthetic-corpus"))
    parser.add_argument("--voices", default=",".join(DEFAULT_VOICES))
    parser.add_argument("--seconds", type=float, default=5.0, help="Duration for silence and noise fixtures.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    voices = [voice.strip() for voice in args.voices.split(",") if voice.strip()]
    cases = [case for case in load_cases(args.cases) if case.get("suite") == "asr" and case.get("kind") == "asr"]
    roots: list[Path] = []
    for voice in voices:
        root = args.output / slugify(voice)
        root.mkdir(parents=True, exist_ok=True)
        roots.append(root)
        for case in cases:
            destination = root / Path(str(case.get("audio") or "")).name
            expected = str(case.get("expected") or "")
            category = str(case.get("category") or "")
            if expected:
                synthesize(expected, destination, voice)
            elif category == "silence":
                write_silence(destination, args.seconds)
            else:
                write_noise(destination, args.seconds)
            print(f"{voice}: {case.get('id')} -> {destination}")
    manifest = {
        "source": "synthetic-windows-tts",
        "voices": voices,
        "roots": [str(root) for root in roots],
        "limitation": "Synthetic speech validates repeatable ASR plumbing, not real-human accent quality.",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Audio roots: " + ",".join(str(root) for root in roots))
    return 0


def synthesize(text: str, destination: Path, voice: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["WINSPER_TTS_TEXT"] = text
    environment["WINSPER_TTS_OUTPUT"] = str(destination.resolve())
    environment["WINSPER_TTS_VOICE"] = voice
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SelectVoice($env:WINSPER_TTS_VOICE); "
        "$s.SetOutputToWaveFile($env:WINSPER_TTS_OUTPUT); "
        "$s.Speak($env:WINSPER_TTS_TEXT); "
        "$s.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )


def write_silence(destination: Path, seconds: float) -> None:
    import numpy as np

    samples = np.zeros(max(1, int(16000 * seconds)), dtype="float32")
    write_wav(AudioClip(samples, 16000, seconds, seconds), destination)


def write_noise(destination: Path, seconds: float) -> None:
    import numpy as np

    rng = np.random.default_rng(20260701)
    samples = rng.normal(0.0, 0.008, max(1, int(16000 * seconds))).astype("float32")
    write_wav(AudioClip(samples, 16000, seconds, seconds), destination)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "voice"


if __name__ == "__main__":
    raise SystemExit(main())
