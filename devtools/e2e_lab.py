from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import html
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from voicepilot.audio import read_wav
from voicepilot.config import AppConfig, ProfileStyle, Snippet, load_config
from voicepilot.corrections import CorrectionStore, apply_corrections, make_rule
from voicepilot.destination import DestinationContext
from voicepilot.models import engine_for_model, find_speech_model
from voicepilot.instruction_quality import assess_instruction, script_counts
from .phase4_release import evaluate_phase4_release
from .phase5_release import evaluate_phase5_release, expand_phase5_cases
from voicepilot.speech_languages import model_supports_language
from .prompt_audit import audit_all_prompts, prompt_audit_payload
from voicepilot.rewrite import TextRewriter, looks_like_degenerate_output
from voicepilot.rewrite_backends import (
    LlamaServerCompletionBackend,
    OllamaCompletionBackend,
    check_rewrite_backend_health,
)
from voicepilot.snippets import match_snippet
from voicepilot.spoken_formatting import apply_spoken_layout
from voicepilot.speed_lab import score_transcript
from voicepilot.transcribe import FasterWhisperTranscriber
from voicepilot.voice_commands import parse_voice_command, split_trailing_enter_action


@dataclass(frozen=True)
class LabResult:
    run_id: str
    case_id: str
    suite: str
    category: str
    kind: str
    status: str
    score: int | None
    latency_ms: float
    expected: str
    actual: str
    model: str = ""
    gate: str = ""
    notes: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    memory_mb: float | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Winsper end-to-end quality laboratory.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--cases", type=Path, default=Path("e2e/cases.yaml"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/e2e"))
    parser.add_argument(
        "--suite",
        choices=["deterministic", "hardware", "asr", "polish", "prompts", "phase5", "guided", "auto", "all"],
        default="deterministic",
    )
    parser.add_argument("--models", default="", help="Comma-separated ASR models. Defaults to the configured model.")
    parser.add_argument("--audio-roots", default="", help="Comma-separated corpus roots; each must contain the declared WAV filenames.")
    parser.add_argument("--polish-runs", type=int, default=3)
    parser.add_argument("--rewrite-runs", type=int, default=1)
    parser.add_argument("--rewrite-model", default="", help="Override the local Ollama model without changing saved settings.")
    parser.add_argument("--rewrite-provider", default="", help="Override the rewrite backend without changing saved settings.")
    parser.add_argument("--rewrite-temperature", type=float, default=None)
    parser.add_argument("--ollama-repeat-penalty", type=float, default=None)
    parser.add_argument("--ollama-top-p", type=float, default=None)
    parser.add_argument("--ollama-top-k", type=int, default=None)
    parser.add_argument("--ollama-seed", type=int, default=None)
    parser.add_argument("--ollama-num-ctx", type=int, default=None)
    parser.add_argument("--llama-repeat-penalty", type=float, default=None)
    parser.add_argument("--llama-top-p", type=float, default=None)
    parser.add_argument("--llama-top-k", type=int, default=None)
    parser.add_argument("--llama-min-p", type=float, default=None)
    parser.add_argument("--llama-presence-penalty", type=float, default=None)
    parser.add_argument("--llama-seed", type=int, default=None)
    parser.add_argument("--llama-context-size", type=int, default=None)
    parser.add_argument("--case-ids", default="", help="Comma-separated exact case IDs for bounded lab runs.")
    parser.add_argument(
        "--prompt-profile",
        choices=["auto", "fast", "balanced", "best"],
        default="auto",
        help="Override prompt instruction density without changing saved settings.",
    )
    parser.add_argument("--llama-server-path", default="", help="Override the embedded llama-server executable.")
    parser.add_argument("--llama-model-path", default="", help="Override the embedded GGUF model.")
    parser.add_argument("--llama-model-id", default="", help="Label an overridden embedded GGUF model.")
    parser.add_argument("--llama-device", default="", help="Override the embedded llama.cpp device, such as Vulkan1.")
    parser.add_argument("--llama-gpu-layers", default="", help="Override embedded GPU offload, such as auto, all, or 0.")
    parser.add_argument("--guided", action="store_true", help="Prompt for manual real-app results.")
    parser.add_argument("--fail-on-gate", action="store_true")
    parser.add_argument(
        "--certify-phase4",
        action="store_true",
        help="Fail unless every Phase 4 metric passes its minimum representative sample count.",
    )
    parser.add_argument(
        "--certify-phase5",
        action="store_true",
        help="Fail unless at least 500 production Polish cases pass without a detected unsafe output.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    apply_rewrite_overrides(config, args)
    return _run_main(args, config)


def apply_rewrite_overrides(config: AppConfig, args: argparse.Namespace) -> None:
    """Apply CLI backend overrides without silently benchmarking the wrong provider."""
    if args.rewrite_model.strip():
        config.rewrite.model = args.rewrite_model.strip()
        config.rewrite.provider = "ollama"
    if args.rewrite_provider.strip():
        config.rewrite.provider = args.rewrite_provider.strip()
    rewrite_temperature = getattr(args, "rewrite_temperature", None)
    if rewrite_temperature is not None:
        config.rewrite.temperature = float(rewrite_temperature)
    prompt_profile = str(getattr(args, "prompt_profile", "auto") or "auto").strip()
    if prompt_profile:
        config.rewrite.prompt_profile = prompt_profile
    if args.llama_server_path.strip():
        config.rewrite.llama_server_path = args.llama_server_path.strip()
    if args.llama_model_path.strip():
        config.rewrite.llama_model_path = args.llama_model_path.strip()
        config.rewrite.llama_model_id = ""
    if args.llama_model_id.strip():
        config.rewrite.llama_model_id = args.llama_model_id.strip()
    if args.llama_device.strip():
        config.rewrite.llama_device = args.llama_device.strip()
    llama_gpu_layers = str(getattr(args, "llama_gpu_layers", "") or "").strip()
    if llama_gpu_layers:
        config.rewrite.llama_gpu_layers = llama_gpu_layers
    llama_context_size = getattr(args, "llama_context_size", None)
    if llama_context_size is not None:
        config.rewrite.llama_context_size = max(512, int(llama_context_size))


def _run_main(args: argparse.Namespace, config: AppConfig) -> int:
    cases = load_cases(args.cases)
    case_ids = str(getattr(args, "case_ids", "") or "")
    requested_case_ids = {item.strip() for item in case_ids.split(",") if item.strip()}
    if args.suite == "phase5":
        cases = expand_phase5_cases(cases)
    if requested_case_ids:
        if args.suite == "phase5":
            matched_ids = {
                requested
                for requested in requested_case_ids
                if any(
                    str(case.get("id") or "") == requested
                    or str(case.get("id") or "").startswith(f"{requested}--")
                    for case in cases
                )
            }
            cases = [
                case
                for case in cases
                if any(
                    str(case.get("id") or "") == requested
                    or str(case.get("id") or "").startswith(f"{requested}--")
                    for requested in requested_case_ids
                )
            ]
        else:
            cases = [case for case in cases if str(case.get("id") or "") in requested_case_ids]
            matched_ids = {str(case.get("id") or "") for case in cases}
        missing_case_ids = sorted(requested_case_ids - matched_ids)
        if missing_case_ids:
            raise SystemExit(f"Unknown case IDs: {', '.join(missing_case_ids)}")
    models = [item.strip() for item in args.models.split(",") if item.strip()] or [config.speech.model]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    run_dir = args.output / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    runner = LabRunner(
        run_id=run_id,
        config=config,
        config_path=args.config,
        cases_path=args.cases,
        models=models,
        polish_runs=max(1, args.polish_runs),
        rewrite_runs=max(1, args.rewrite_runs),
        guided=args.guided,
        audio_roots=[Path(item.strip()) for item in args.audio_roots.split(",") if item.strip()],
        phase4_certification=args.certify_phase4,
        ollama_option_overrides=ollama_option_overrides(args),
        llama_option_overrides=llama_option_overrides(args),
    )
    results = runner.run(cases, args.suite)
    summary = summarize(results)
    write_artifacts(run_dir, runner.manifest(), results, summary)
    print_summary(run_dir, summary)
    if args.fail_on_gate and summary["gate_failures"]:
        return 2
    if args.certify_phase4 and not summary["phase4"]["ready"]:
        return 3
    if args.certify_phase5 and not summary["phase5"]["ready"]:
        return 4
    return 0


def ollama_option_overrides(args: argparse.Namespace) -> dict[str, object]:
    mapping = {
        "repeat_penalty": getattr(args, "ollama_repeat_penalty", None),
        "top_p": getattr(args, "ollama_top_p", None),
        "top_k": getattr(args, "ollama_top_k", None),
        "seed": getattr(args, "ollama_seed", None),
        "num_ctx": getattr(args, "ollama_num_ctx", None),
    }
    return {key: value for key, value in mapping.items() if value is not None}


def llama_option_overrides(args: argparse.Namespace) -> dict[str, object]:
    mapping = {
        "repeat_penalty": getattr(args, "llama_repeat_penalty", None),
        "top_p": getattr(args, "llama_top_p", None),
        "top_k": getattr(args, "llama_top_k", None),
        "min_p": getattr(args, "llama_min_p", None),
        "presence_penalty": getattr(args, "llama_presence_penalty", None),
        "seed": getattr(args, "llama_seed", None),
    }
    return {key: value for key, value in mapping.items() if value is not None}


class LabRunner:
    def __init__(
        self,
        *,
        run_id: str,
        config: AppConfig,
        config_path: Path,
        cases_path: Path,
        models: list[str],
        polish_runs: int,
        rewrite_runs: int,
        guided: bool,
        audio_roots: list[Path] | None = None,
        phase4_certification: bool = False,
        ollama_option_overrides: dict[str, object] | None = None,
        llama_option_overrides: dict[str, object] | None = None,
    ) -> None:
        self.run_id = run_id
        self.config = config
        self.config_path = config_path
        self.cases_path = cases_path
        self.models = models
        self.polish_runs = polish_runs
        self.rewrite_runs = rewrite_runs
        self.guided = guided
        self.audio_roots = audio_roots or []
        self.phase4_certification = phase4_certification
        self.ollama_option_overrides = dict(ollama_option_overrides or {})
        self.llama_option_overrides = dict(llama_option_overrides or {})
        self._transcribers: dict[str, FasterWhisperTranscriber] = {}
        self._model_runtime_configs: dict[str, object] = {}
        self._model_load_ms: dict[str, float] = {}
        self._polish_health = None
        self._rewriter: TextRewriter | None = None
        self._corrections = CorrectionStore.for_config(
            config_path,
            max_rules=config.correction_memory.max_rules,
            enabled=config.correction_memory.enabled,
        )
        self._nvidia_memory_baseline_mb = nvidia_total_memory_mb()

    def run(self, cases: list[dict[str, Any]], suite: str) -> list[LabResult]:
        try:
            results: list[LabResult] = []
            selected: list[dict[str, Any]] = []
            for case in cases:
                case_suite = str(case.get("suite") or "deterministic")
                if suite not in {"all", "auto"} and case_suite != suite:
                    continue
                if suite == "auto" and case_suite == "guided":
                    continue
                selected.append(case)

            asr_cases = [case for case in selected if case.get("suite") == "asr"]
            phase5_total = sum(case.get("suite") == "phase5" for case in selected)
            phase5_done = 0
            for case in selected:
                if case.get("suite") == "asr":
                    continue
                before = len(results)
                if case.get("suite") == "polish":
                    for iteration in range(self.polish_runs):
                        results.append(self._run_case(case, iteration=iteration + 1))
                elif case.get("kind") == "rewrite":
                    for iteration in range(self.rewrite_runs):
                        results.append(self._run_case(case, iteration=iteration + 1))
                else:
                    results.append(self._run_case(case))
                if case.get("suite") == "phase5":
                    phase5_done += len(results) - before
                    if phase5_done % 25 == 0 or phase5_done == phase5_total:
                        print(f"Phase 5 progress: {phase5_done}/{phase5_total}", flush=True)

            for model in self.models:
                for case in asr_cases:
                    roots = self.audio_roots or [None]
                    for audio_root in roots:
                        results.append(self._run_case(case, model=model, audio_root=audio_root))
                self._transcribers.clear()
                gc.collect()
            return results
        finally:
            if self._rewriter is not None:
                self._rewriter.close()
                self._rewriter = None

    def _run_case(
        self,
        case: dict[str, Any],
        *,
        model: str = "",
        iteration: int = 0,
        audio_root: Path | None = None,
    ) -> LabResult:
        started = time.perf_counter()
        try:
            outcome = self._execute(case, model=model, audio_root=audio_root)
            status = outcome.pop("status", "pass")
            score = outcome.pop("score", 3 if status == "pass" else None)
            notes = outcome.pop("notes", "")
            actual = str(outcome.pop("actual", ""))
            expected = str(outcome.pop("expected", expected_description(case)))
            metrics = outcome
        except Exception as exc:
            status, score, notes, actual, expected, metrics = (
                "error",
                0,
                f"{type(exc).__name__}: {exc}",
                "",
                expected_description(case),
                {},
            )
        latency_ms = (time.perf_counter() - started) * 1000
        metrics.update(self._rewrite_runtime_metrics())
        suffix = f"#run-{iteration}" if iteration else ""
        if audio_root is not None:
            suffix += f"#audio-{audio_root.name}"
        return LabResult(
            run_id=self.run_id,
            case_id=str(case.get("id") or "unnamed") + suffix,
            suite=str(case.get("suite") or "deterministic"),
            category=str(case.get("category") or "uncategorized"),
            kind=str(case.get("kind") or ""),
            status=status,
            score=score,
            latency_ms=latency_ms,
            expected=expected,
            actual=actual,
            model=model,
            gate=str(case.get("gate") or ""),
            notes=notes,
            metrics=metrics,
            memory_mb=process_memory_mb(),
        )

    def _rewrite_runtime_metrics(self) -> dict[str, Any]:
        rewriter = self._rewriter
        if rewriter is None:
            return {}
        metrics: dict[str, Any] = {
            "rewrite_model": rewriter.model_label(),
            "prompt_profile": rewriter.prompt_profile(),
            "prompt_version": rewriter.prompt_version(),
        }
        if rewriter.backend is None:
            return metrics
        runtime = getattr(rewriter.backend, "runtime", None)
        if runtime is None:
            return metrics
        metrics.update(getattr(runtime, "last_completion_metrics", {}) or {})
        process_id = getattr(runtime, "process_id", None)
        if not isinstance(process_id, int):
            return metrics
        metrics["backend_pid"] = process_id
        memory = process_memory_mb(process_id)
        if memory is not None:
            metrics["backend_memory_mb"] = memory
        gpu_memory = nvidia_process_memory_mb(process_id)
        if gpu_memory is None:
            total_gpu_memory = nvidia_total_memory_mb()
            if total_gpu_memory is not None and self._nvidia_memory_baseline_mb is not None:
                gpu_memory = max(0.0, total_gpu_memory - self._nvidia_memory_baseline_mb)
        if gpu_memory is not None:
            metrics["backend_vram_mb"] = gpu_memory
        return metrics

    def _execute(self, case: dict[str, Any], *, model: str = "", audio_root: Path | None = None) -> dict[str, Any]:
        kind = str(case.get("kind") or "")
        if kind == "spoken_layout":
            actual = apply_spoken_layout(str(case.get("input") or ""), bool(case.get("enabled", True)))
            return exact_outcome(actual, str(case.get("expected") or ""))
        if kind == "trailing_action":
            text, key = split_trailing_enter_action(
                str(case.get("input") or ""),
                str(case.get("phrase") or "press enter"),
                bool(case.get("enabled", True)),
            )
            actual = json.dumps({"text": text, "key": key}, ensure_ascii=False)
            expected = json.dumps(
                {"text": str(case.get("expected_text") or ""), "key": str(case.get("expected_key") or "")},
                ensure_ascii=False,
            )
            return exact_outcome(actual, expected)
        if kind == "voice_command":
            command = parse_voice_command(str(case.get("input") or ""))
            actual_payload = {"kind": command.kind, "action": command.action, "label": command.label}
            expected_payload = {
                "kind": str(case.get("expected_kind") or ""),
                "action": str(case.get("expected_action") or ""),
                "label": str(case.get("expected_label") or command.label),
            }
            return exact_outcome(
                json.dumps(actual_payload, sort_keys=True),
                json.dumps(expected_payload, sort_keys=True),
            )
        if kind == "snippet":
            snippets = [
                Snippet(
                    name=str(item.get("name") or ""),
                    trigger=str(item.get("trigger") or ""),
                    text=str(item.get("text") or ""),
                    aliases=list(item.get("aliases") or []),
                    profiles=list(item.get("profiles") or []),
                )
                for item in case.get("snippets") or []
            ]
            match = match_snippet(str(case.get("input") or ""), snippets, str(case.get("profile") or "general"))
            actual = "" if match is None else match.text
            metrics = {"match_mode": "" if match is None else match.mode}
            outcome = exact_outcome(actual, str(case.get("expected") or ""))
            outcome.update(metrics)
            return outcome
        if kind == "correction":
            rules = [
                make_rule(
                    str(item.get("heard") or ""),
                    str(item.get("replacement") or ""),
                    profiles=list(item.get("profiles") or []),
                )
                for item in case.get("rules") or []
            ]
            actual = apply_corrections(str(case.get("input") or ""), rules, str(case.get("profile") or "general"))
            return exact_outcome(actual, str(case.get("expected") or ""))
        if kind == "asr":
            language = str(case.get("language") if case.get("language") is not None else "")
            preset = find_speech_model(model)
            if preset is not None and not model_supports_language(preset, language):
                return {
                    "status": "skip",
                    "score": None,
                    "notes": f"Model {model} does not support language {language or 'Auto / Mixed'}.",
                }
            declared_audio = Path(str(case.get("audio") or ""))
            audio_path = (
                (audio_root / declared_audio.name).resolve()
                if audio_root is not None
                else (self.cases_path.parent / declared_audio).resolve()
            )
            if not audio_path.exists():
                return {"status": "skip", "score": None, "notes": f"Missing corpus audio: {audio_path}"}
            transcriber = self._transcriber(model)
            clip = read_wav(audio_path)
            if case.get("language") is None:
                language = str(transcriber.config.language)
            purpose = str(case.get("purpose") or "dictation")
            case_config = replace(transcriber.config, language=language, purpose=purpose)
            started = time.perf_counter()
            raw_actual = transcriber.transcribe(clip, config=case_config)
            transcription_ms = (time.perf_counter() - started) * 1000
            actual = self._corrections.apply(raw_actual, "general")
            expected = str(case.get("expected") or "")
            if not expected.strip():
                passed = not actual.strip()
                return {
                    "status": "pass" if passed else "fail",
                    "score": 3 if passed else 0,
                    "actual": actual,
                    "expected": "",
                    "hallucinated": not passed,
                    "transcription_ms": transcription_ms,
                    "realtime_factor": (transcription_ms / 1000) / max(clip.duration_seconds, 0.001),
                }
            raw_score = score_transcript(raw_actual, expected)
            transcript_score = score_transcript(actual, expected)
            wer = raw_score.word_error_rate if raw_score is not None else None
            production_wer = transcript_score.word_error_rate if transcript_score is not None else None
            protected_accuracy = token_recall(actual, list(case.get("protected") or []))
            gate = str(case.get("gate") or "")
            scoring_protected_accuracy = None if gate == "first-word-capture" else protected_accuracy
            score = asr_score(production_wer, scoring_protected_accuracy, bool(actual.strip()))
            first_word_exact = first_word_matches(raw_actual, expected)
            first_word_ok = first_word_captured(raw_actual, expected)
            instruction_assessment = (
                assess_instruction(actual, clip, language)
                if purpose == "polish_instruction"
                else None
            )
            required_scripts = [str(item) for item in case.get("required_scripts") or []]
            actual_scripts = script_counts(actual)
            script_preserved = (
                all(actual_scripts.get(script, 0) > 0 for script in required_scripts)
                if required_scripts
                else None
            )
            expected_script = str(case.get("expected_script") or "")
            english_translation = str(case.get("english_translation") or "")
            if expected_script:
                translation_violation = actual_scripts.get(expected_script, 0) == 0
            elif english_translation:
                expected_similarity = score_transcript(actual, expected)
                english_similarity = score_transcript(actual, english_translation)
                translation_violation = bool(
                    english_similarity is not None
                    and expected_similarity is not None
                    and english_similarity.similarity >= 0.65
                    and english_similarity.similarity > expected_similarity.similarity
                )
            else:
                translation_violation = None
            gate_failed = (gate == "protected-terms" and protected_accuracy != 1.0) or (
                gate == "first-word-capture" and not first_word_ok
            ) or (instruction_assessment is not None and not instruction_assessment.accepted) or (
                translation_violation is True
            ) or (script_preserved is False)
            return {
                "status": "pass" if score >= 2 and not gate_failed else "fail",
                "score": score,
                "actual": actual,
                "expected": expected,
                "raw_transcript": raw_actual,
                "wer": wer,
                "production_wer": production_wer,
                "similarity": None if transcript_score is None else transcript_score.similarity,
                "protected_accuracy": protected_accuracy,
                "protected_terms": list(case.get("protected") or []),
                "first_word_ok": first_word_ok,
                "first_word_exact": first_word_exact,
                "language": language,
                "purpose": purpose,
                "corpus_kind": "human" if audio_root is None else "synthetic",
                "instruction_accepted": (
                    instruction_assessment.accepted if instruction_assessment is not None else None
                ),
                "instruction_rejection": (
                    instruction_assessment.code if instruction_assessment is not None and not instruction_assessment.accepted else ""
                ),
                "translation_violation": translation_violation,
                "script_preserved": script_preserved,
                "transcription_ms": transcription_ms,
                "realtime_factor": (transcription_ms / 1000) / max(clip.duration_seconds, 0.001),
                "model_load_ms": self._model_load_ms.get(model),
                "speech_device": str(
                    getattr(self._model_runtime_configs.get(model, case_config), "device", "")
                ),
                "speech_compute_type": str(
                    getattr(self._model_runtime_configs.get(model, case_config), "compute_type", "")
                ),
                "audio_source": str(audio_path),
                "notes": (
                    "Safety gate requires exact protected terms after correction memory."
                    if gate_failed and gate == "protected-terms"
                    else "The transcript translated or lost the selected language."
                    if translation_violation is True
                    else "The transcript did not preserve every required writing system."
                    if script_preserved is False
                    else "First spoken word was not captured."
                    if gate_failed
                    else ""
                ),
            }
        if kind == "polish":
            if self._polish_health is None:
                self._polish_health = check_rewrite_backend_health(self.config.rewrite)
            if not self._polish_health.ready:
                return {
                    "status": "skip",
                    "score": None,
                    "notes": f"{self._polish_health.message}. {self._polish_health.detail}".strip(),
                }
            actual = self._rewrite_engine().polish(
                str(case.get("input") or ""),
                profile=ProfileStyle(
                    label=str(case.get("profile_label") or "E2E"),
                    dictation_prompt=str(case.get("guidance") or ""),
                ),
                app_label=str(case.get("app_label") or "E2E test"),
                destination=destination_from_case(case),
                language=str(case.get("language") or self.config.speech.language),
            ).strip()
            return constraint_outcome(case, actual)
        if kind == "rewrite":
            if self._polish_health is None:
                self._polish_health = check_rewrite_backend_health(self.config.rewrite)
            if not self._polish_health.ready:
                return {
                    "status": "skip",
                    "score": None,
                    "notes": f"{self._polish_health.message}. {self._polish_health.detail}".strip(),
                }
            try:
                actual = self._rewrite_engine().rewrite(
                    str(case.get("input") or ""),
                    str(case.get("instruction") or ""),
                    profile=ProfileStyle(
                        label=str(case.get("profile_label") or "E2E"),
                        rewrite_prompt=str(case.get("guidance") or ""),
                    ),
                    app_label=str(case.get("app_label") or "E2E test"),
                    destination=destination_from_case(case),
                ).strip()
            except RuntimeError as exc:
                if case.get("expect_blocked"):
                    return {
                        "status": "pass",
                        "score": 3,
                        "actual": f"BLOCKED: {exc}",
                        "expected": "Unsafe rewrite is blocked before replacement.",
                    }
                raise
            return constraint_outcome(case, actual)
        if kind == "guided":
            if not self.guided:
                return {"status": "skip", "score": None, "notes": "Run with --guided for real-app certification."}
            return guided_outcome(case)
        if kind == "pytest_hardware":
            node = str(case.get("node") or "")
            if not node:
                return {"status": "error", "score": 0, "notes": "Missing pytest node."}
            environment = os.environ.copy()
            environment["WINSPER_REAL_TESTS"] = "1"
            environment.pop("QT_QPA_PLATFORM", None)
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-s", node],
                cwd=Path.cwd(),
                env=environment,
                capture_output=True,
                text=True,
                timeout=float(case.get("timeout_seconds") or 30),
                check=False,
            )
            output = (completed.stdout + "\n" + completed.stderr).strip()
            passed = completed.returncode == 0
            return {
                "status": "pass" if passed else "fail",
                "score": 3 if passed else 0,
                "actual": output[-1500:],
                "expected": "Hardware pytest node passes.",
                "return_code": completed.returncode,
            }
        if kind == "prompt_inventory":
            audit = audit_all_prompts(self.config)
            failed = [result for result in audit if not result.passed]
            return {
                "status": "pass" if not failed else "fail",
                "score": 3 if not failed else 0,
                "actual": f"{len(audit) - len(failed)}/{len(audit)} prompt contracts passed",
                "expected": "Every constructed prompt contract passes.",
                "prompt_count": len(audit),
                "failed_count": len(failed),
                "inventory": prompt_audit_payload(audit),
                "notes": "; ".join(f"{result.name}: {', '.join(result.failures)}" for result in failed),
            }
        return {"status": "error", "score": 0, "notes": f"Unsupported case kind: {kind}"}

    def _rewrite_engine(self) -> TextRewriter:
        if self._rewriter is None:
            backend = None
            if self.config.rewrite.provider == "ollama" and self.ollama_option_overrides:
                backend = OllamaCompletionBackend(
                    self.config.rewrite,
                    option_overrides=self.ollama_option_overrides,
                )
            elif self.config.rewrite.provider in {"embedded", "llama_cpp", "llama_server"} and self.llama_option_overrides:
                backend = LlamaServerCompletionBackend(
                    self.config.rewrite,
                    option_overrides=self.llama_option_overrides,
                )
            self._rewriter = TextRewriter(self.config.rewrite, self.config.vocabulary, backend=backend)
        return self._rewriter

    def _transcriber(self, model: str) -> FasterWhisperTranscriber:
        if model not in self._transcribers:
            speech = replace(self.config.speech, model=model, engine=engine_for_model(model, self.config.speech.engine))
            if self.phase4_certification:
                if model == "large-v3-turbo":
                    speech = replace(speech, device="cuda", compute_type="float16")
                elif model in {"small", "small.en"}:
                    speech = replace(speech, device="cpu", compute_type="int8")
            self._model_runtime_configs[model] = speech

            def record_fallback(_requested, fallback) -> None:
                self._model_runtime_configs[model] = fallback

            transcriber = FasterWhisperTranscriber(
                speech,
                self.config.vocabulary,
                on_device_fallback=record_fallback,
            )
            started = time.perf_counter()
            transcriber.load_model(speech)
            self._model_load_ms[model] = (time.perf_counter() - started) * 1000
            self._transcribers[model] = transcriber
        return self._transcribers[model]

    def manifest(self) -> dict[str, Any]:
        polish_model_label = (
            self._rewriter.model_label()
            if self._rewriter is not None
            else TextRewriter(self.config.rewrite, []).model_label()
        )
        return {
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "commit": git_commit(),
            "working_tree_dirty": git_worktree_dirty(),
            "evidence_source_sha256": evidence_source_fingerprint(self.cases_path),
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "models": self.models,
            "configured_engine": self.config.speech.engine,
            "configured_model": self.config.speech.model,
            "polish_model": polish_model_label,
            "rewrite_provider": self.config.rewrite.provider,
            "rewrite_temperature": self.config.rewrite.temperature,
            "prompt_profile": self.config.rewrite.prompt_profile,
            "ollama_option_overrides": self.ollama_option_overrides,
            "llama_option_overrides": self.llama_option_overrides,
            "llama_server_path": self.config.rewrite.llama_server_path,
            "llama_model_path": self.config.rewrite.llama_model_path,
            "llama_model_id": self.config.rewrite.llama_model_id,
            "llama_device": self.config.rewrite.llama_device,
            "llama_context_size": self.config.rewrite.llama_context_size,
            "cases": str(self.cases_path),
            "audio_roots": [str(path) for path in self.audio_roots],
        }


def load_cases(path: Path) -> list[dict[str, Any]]:
    import yaml

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError("E2E cases file must contain a cases list.")
    return [item for item in raw_cases if isinstance(item, dict) and item.get("active", True) is not False]


def destination_from_case(case: dict[str, Any]) -> DestinationContext | None:
    raw = case.get("destination")
    if not isinstance(raw, dict):
        return None
    return DestinationContext(
        kind=str(raw.get("kind") or "general"),
        app_label=str(raw.get("app_label") or case.get("app_label") or ""),
        language=str(raw.get("language") or ""),
        language_source="phase5-matrix",
    )


def exact_outcome(actual: str, expected: str) -> dict[str, Any]:
    passed = actual == expected
    return {
        "status": "pass" if passed else "fail",
        "score": 3 if passed else 0,
        "actual": actual,
        "expected": expected,
    }


def constraint_outcome(case: dict[str, Any], actual: str) -> dict[str, Any]:
    required = [str(item) for item in case.get("must_include") or []]
    forbidden = [str(item) for item in case.get("must_exclude") or []]
    protected = [str(item) for item in case.get("protected") or []]
    alternatives = [[str(item) for item in group] for group in case.get("must_include_any") or []]
    missing = [item for item in required + protected if not phrase_present(actual, item)]
    missing_alternatives = [group for group in alternatives if not any(phrase_present(actual, item) for item in group)]
    leaked = [item for item in forbidden if phrase_present(actual, item)]
    intent = str(case.get("intent") or "")
    intent_ok = not intent or intent != "question" or actual.rstrip().endswith("?")
    degenerate = looks_like_degenerate_output(actual)
    source = str(case.get("input") or "")
    unchanged = " ".join(source.split()) == " ".join(actual.split())
    max_length_ratio = case.get("max_length_ratio")
    source_words = source.split()
    actual_words = actual.split()
    lexical_words = re.findall(r"[^\W_]+(?:['\u2019-][^\W_]+)?", actual, flags=re.UNICODE)
    exact_words = case.get("exact_words")
    exact_words_ok = not isinstance(exact_words, int) or len(lexical_words) == exact_words
    max_words = case.get("max_words")
    max_words_ok = not isinstance(max_words, int) or len(lexical_words) <= max_words
    exact_sentences = case.get("exact_sentences")
    sentence_count = _sentence_count(actual)
    exact_sentences_ok = not isinstance(exact_sentences, int) or sentence_count == exact_sentences
    length_ok = not isinstance(max_length_ratio, (int, float)) or len(actual_words) <= max(
        1,
        int(len(source_words) * float(max_length_ratio)),
    )
    required_structure = str(case.get("required_structure") or "")
    structure_ok = not required_structure or required_structure != "bullets" or _looks_like_list(actual)
    formatting_changed = bool(required_structure and structure_ok and source != actual)
    unexpected_unchanged = bool(case.get("requires_change")) and unchanged and not formatting_changed
    required_scripts = [str(item) for item in case.get("required_scripts") or []]
    observed_scripts = script_counts(actual)
    script_ok = all(observed_scripts.get(script, 0) > 0 for script in required_scripts)
    gated_constraint_failure = bool(case.get("gate") and (missing or missing_alternatives or not intent_ok))
    critical = bool(
        leaked
        or [item for item in protected if item in missing]
        or not actual
        or degenerate
        or unexpected_unchanged
        or not length_ok
        or not structure_ok
        or not script_ok
        or not exact_words_ok
        or not max_words_ok
        or not exact_sentences_ok
        or gated_constraint_failure
    )
    issue_count = (
        len(missing)
        + len(missing_alternatives)
        + len(leaked)
        + (0 if intent_ok else 1)
        + (1 if unexpected_unchanged else 0)
        + (0 if length_ok else 1)
        + (0 if structure_ok else 1)
        + (0 if script_ok else 1)
        + (0 if exact_words_ok else 1)
        + (0 if max_words_ok else 1)
        + (0 if exact_sentences_ok else 1)
    )
    score = 0 if critical else 3 if issue_count == 0 else 2 if issue_count == 1 else 1
    notes = "; ".join(
        part
        for part in (
            f"missing={missing}" if missing else "",
            f"missing_any={missing_alternatives}" if missing_alternatives else "",
            f"forbidden={leaked}" if leaked else "",
            "intent mismatch" if not intent_ok else "",
            "degenerate output" if degenerate else "",
            "unexpected unchanged output" if unexpected_unchanged else "",
            "output exceeded requested length" if not length_ok else "",
            "requested list structure missing" if not structure_ok else "",
            "required writing system missing" if not script_ok else "",
            f"expected exactly {exact_words} words, got {len(lexical_words)}" if not exact_words_ok else "",
            f"expected no more than {max_words} words, got {len(lexical_words)}" if not max_words_ok else "",
            f"expected exactly {exact_sentences} sentences, got {sentence_count}" if not exact_sentences_ok else "",
        )
        if part
    )
    return {
        "status": "pass" if score >= 2 else "fail",
        "score": score,
        "actual": actual,
        "expected": expected_description(case),
        "missing_count": len(missing),
        "leak_count": len(leaked),
        "intent_ok": intent_ok,
        "degenerate": degenerate,
        "unexpected_unchanged": unexpected_unchanged,
        "length_ok": length_ok,
        "structure_ok": structure_ok,
        "script_ok": script_ok,
        "exact_words_ok": exact_words_ok,
        "max_words_ok": max_words_ok,
        "exact_sentences_ok": exact_sentences_ok,
        "notes": notes,
    }


def _looks_like_list(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 3:
        return True
    return len(re.findall(r"(?m)^\s*(?:[-*\u2022]|\d+[.)])\s+", text)) >= 2


def _sentence_count(text: str) -> int:
    value = text.strip()
    if not value:
        return 0
    return max(1, len(re.findall(r"[.!?]+(?=\s|$)", value)))


def phrase_present(text: str, phrase: str) -> bool:
    import re

    folded_phrase = phrase.casefold().strip()
    parts = [re.escape(part) for part in folded_phrase.split()]
    if not parts:
        return False
    prefix = r"(?<!\w)" if folded_phrase[0].isalnum() or folded_phrase[0] == "_" else ""
    suffix = r"(?!\w)" if folded_phrase[-1].isalnum() or folded_phrase[-1] == "_" else ""
    pattern = prefix + r"\s+".join(parts) + suffix
    return re.search(pattern, text.casefold()) is not None


def guided_outcome(case: dict[str, Any]) -> dict[str, Any]:
    print("\n" + "=" * 72)
    print(f"{case.get('id')}: {case.get('title') or case.get('category')}")
    print(str(case.get("instructions") or "Perform the scenario and inspect the result."))
    print(f"Expected: {expected_description(case)}")
    actual = input("Actual result: ").strip()
    while True:
        raw_score = input("Score (0 fail, 1 recovery, 2 minor issue, 3 perfect, s skip): ").strip().lower()
        if raw_score == "s":
            return {"status": "skip", "score": None, "actual": actual, "notes": "Skipped by tester"}
        if raw_score in {"0", "1", "2", "3"}:
            score = int(raw_score)
            break
    notes = input("Notes: ").strip()
    return {
        "status": "pass" if score >= 2 else "fail",
        "score": score,
        "actual": actual,
        "expected": expected_description(case),
        "notes": notes,
    }


def expected_description(case: dict[str, Any]) -> str:
    if case.get("expected") is not None:
        return str(case["expected"])
    parts = []
    if case.get("must_include"):
        parts.append("include: " + ", ".join(str(item) for item in case["must_include"]))
    if case.get("must_exclude"):
        parts.append("exclude: " + ", ".join(str(item) for item in case["must_exclude"]))
    if case.get("protected"):
        parts.append("protect: " + ", ".join(str(item) for item in case["protected"]))
    if isinstance(case.get("exact_words"), int):
        parts.append(f"exactly {case['exact_words']} words")
    if isinstance(case.get("max_words"), int):
        parts.append(f"no more than {case['max_words']} words")
    if isinstance(case.get("exact_sentences"), int):
        parts.append(f"exactly {case['exact_sentences']} sentences")
    return "; ".join(parts)


def token_recall(text: str, tokens: list[str]) -> float | None:
    if not tokens:
        return None
    return sum(1 for token in tokens if phrase_present(text, token)) / len(tokens)


def first_word_matches(actual: str, expected: str) -> bool:
    import re

    actual_words = re.findall(r"\b[\w'-]+\b", actual.casefold())
    expected_words = re.findall(r"\b[\w'-]+\b", expected.casefold())
    return bool(actual_words and expected_words and actual_words[0] == expected_words[0])


def first_word_captured(actual: str, expected: str, minimum_similarity: float = 0.65) -> bool:
    """Distinguish an omitted first word from a near-spelling ASR error."""
    import re
    from difflib import SequenceMatcher

    actual_words = re.findall(r"\b[\w'-]+\b", actual.casefold())
    expected_words = re.findall(r"\b[\w'-]+\b", expected.casefold())
    if not actual_words or not expected_words:
        return False
    if actual_words[0] == expected_words[0]:
        return True
    if min(len(actual_words[0]), len(expected_words[0])) < 4:
        return False
    return SequenceMatcher(None, actual_words[0], expected_words[0]).ratio() >= minimum_similarity


def asr_score(wer: float | None, protected_accuracy: float | None, has_text: bool) -> int:
    if not has_text:
        return 0
    if protected_accuracy is not None and protected_accuracy < 0.5:
        return 0
    if wer is None:
        return 2
    if wer <= 0.10 and (protected_accuracy is None or protected_accuracy == 1.0):
        return 3
    if wer <= 0.25:
        return 2
    if wer <= 0.50:
        return 1
    return 0


def summarize(results: list[LabResult]) -> dict[str, Any]:
    executed = [result for result in results if result.status != "skip"]
    latencies = [result.latency_ms for result in executed]
    scores = [result.score for result in executed if result.score is not None]
    groups: dict[str, dict[str, Any]] = {}
    for result in results:
        key = f"{result.suite}/{result.category}" + (f"/{result.model}" if result.model else "")
        group = groups.setdefault(
            key,
            {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "scores": [],
                "latencies": [],
                "wer": [],
                "realtime_factor": [],
                "protected_accuracy": [],
            },
        )
        group["total"] += 1
        group["passed"] += result.status == "pass"
        group["failed"] += result.status in {"fail", "error"}
        group["skipped"] += result.status == "skip"
        if result.score is not None:
            group["scores"].append(result.score)
        if result.status != "skip":
            group["latencies"].append(result.latency_ms)
        for metric in ("wer", "realtime_factor", "protected_accuracy"):
            value = result.metrics.get(metric)
            if isinstance(value, (int, float)):
                group[metric].append(float(value))
    for group in groups.values():
        group["average_score"] = average(group.pop("scores"))
        group["p50_ms"] = percentile(group["latencies"], 50)
        group["p95_ms"] = percentile(group["latencies"], 95)
        group.pop("latencies")
        group["average_wer"] = average(group.pop("wer"))
        group["average_realtime_factor"] = average(group.pop("realtime_factor"))
        group["average_protected_accuracy"] = average(group.pop("protected_accuracy"))

    gates: dict[str, dict[str, int]] = {}
    for result in results:
        if not result.gate:
            continue
        gate_name = f"{result.suite}:{result.gate}"
        gate = gates.setdefault(gate_name, {"executed": 0, "failures": 0, "skipped": 0})
        gate["skipped"] += result.status == "skip"
        if result.status != "skip":
            gate["executed"] += 1
            gate["failures"] += result.status in {"fail", "error"}
    gate_failures = [name for name, gate in gates.items() if gate["failures"]]
    unassessed_gates = [name for name, gate in gates.items() if not gate["executed"]]
    memory = [result.memory_mb for result in executed if result.memory_mb is not None]
    models: dict[str, dict[str, Any]] = {}
    for result in results:
        if result.suite != "asr" or not result.model or result.status == "skip":
            continue
        model = models.setdefault(
            result.model,
            {"total": 0, "passed": 0, "scores": [], "wer": [], "rtf": [], "protected": [], "load_ms": []},
        )
        model["total"] += 1
        model["passed"] += result.status == "pass"
        if result.score is not None:
            model["scores"].append(result.score)
        for key, target in (
            ("wer", "wer"),
            ("realtime_factor", "rtf"),
            ("protected_accuracy", "protected"),
            ("model_load_ms", "load_ms"),
        ):
            value = result.metrics.get(key)
            if isinstance(value, (int, float)):
                model[target].append(float(value))
    for model in models.values():
        model["average_score"] = average(model.pop("scores"))
        model["average_wer"] = average(model.pop("wer"))
        model["average_realtime_factor"] = average(model.pop("rtf"))
        model["average_protected_accuracy"] = average(model.pop("protected"))
        model["load_ms"] = average(model.pop("load_ms"))
    return {
        "total": len(results),
        "executed": len(executed),
        "passed": sum(result.status == "pass" for result in results),
        "failed": sum(result.status in {"fail", "error"} for result in results),
        "skipped": sum(result.status == "skip" for result in results),
        "pass_rate": (sum(result.status == "pass" for result in executed) / len(executed)) if executed else None,
        "average_score": average(scores),
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "p99_ms": percentile(latencies, 99),
        "memory_min_mb": min(memory) if memory else None,
        "memory_peak_mb": max(memory) if memory else None,
        "memory_growth_mb": (max(memory) - min(memory)) if memory else None,
        "models": models,
        "groups": groups,
        "gates": gates,
        "gate_failures": gate_failures,
        "unassessed_gates": unassessed_gates,
        "phase4": evaluate_phase4_release(results),
        "phase5": evaluate_phase5_release(results),
    }


def write_artifacts(run_dir: Path, manifest: dict[str, Any], results: list[LabResult], summary: dict[str, Any]) -> None:
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    with (run_dir / "results.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
    with (run_dir / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "suite",
                "category",
                "kind",
                "model",
                "status",
                "score",
                "latency_ms",
                "memory_mb",
                "gate",
                "expected",
                "actual",
                "notes",
            ],
        )
        writer.writeheader()
        for result in results:
            row = asdict(result)
            row["latency_ms"] = round(result.latency_ms, 2)
            row["memory_mb"] = "" if result.memory_mb is None else round(result.memory_mb, 1)
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
    (run_dir / "report.html").write_text(render_html(manifest, summary, results), encoding="utf-8")


def render_html(manifest: dict[str, Any], summary: dict[str, Any], results: list[LabResult]) -> str:
    pass_rate = "N/A" if summary["pass_rate"] is None else f"{summary['pass_rate']:.1%}"
    gate_state = "PASS" if not summary["gate_failures"] else "FAIL: " + ", ".join(summary["gate_failures"])
    phase4_state = "PASS" if summary["phase4"]["ready"] else "NOT CERTIFIED"
    phase5 = summary["phase5"]
    phase5_branches = " &middot; ".join(
        f"{branch.title()} {details['passed']}/{details['executed']}"
        for branch, details in phase5["branches"].items()
    )
    phase5_block = (
        ""
        if not phase5["executed"]
        else (
            f"<p><strong>Phase 5:</strong> {'PASS' if phase5['ready'] else 'NOT CERTIFIED'} &middot; "
            f"{phase5['passed']}/{phase5['executed']} passed &middot; "
            f"inference p95 {format_optional(phase5['warm_p95_ms'], 1)} ms "
            f"(target {phase5['latency_target_ms']:.0f} ms)<br>{phase5_branches}</p>"
        )
    )
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(result.case_id)}</td><td>{html.escape(result.category)}</td>"
        f"<td>{html.escape(result.model or '—')}</td><td class='{result.status}'>{html.escape(result.status.upper())}</td>"
        f"<td>{'—' if result.score is None else result.score}</td><td>{result.latency_ms:.1f}</td>"
        f"<td>{html.escape(result.notes)}</td>"
        "</tr>"
        for result in results
    )
    group_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(name)}</td><td>{group['passed']}/{group['total'] - group['skipped']}</td>"
        f"<td>{format_optional(group['average_score'], 2)}</td><td>{format_optional(group['p50_ms'], 1)}</td>"
        f"<td>{format_optional(group['p95_ms'], 1)}</td><td>{format_optional(group['average_wer'], 3)}</td>"
        f"<td>{format_optional(group['average_realtime_factor'], 3)}</td><td>{group['skipped']}</td>"
        "</tr>"
        for name, group in summary["groups"].items()
    )
    model_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(name)}</td><td>{model['passed']}/{model['total']}</td>"
        f"<td>{format_optional(model['average_score'], 2)}</td><td>{format_optional(model['average_wer'], 3)}</td>"
        f"<td>{format_optional(model['average_protected_accuracy'], 3)}</td>"
        f"<td>{format_optional(model['average_realtime_factor'], 3)}</td><td>{format_optional(model['load_ms'], 1)}</td>"
        "</tr>"
        for name, model in summary["models"].items()
    )
    phase4_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(profile_name.upper())}</td><td>{html.escape(gate['name'])}</td>"
        f"<td class='{gate['status']}'>{gate['status'].upper()}</td>"
        f"<td>{format_optional(gate['value'], 3)}</td><td>{html.escape(gate['target'])}</td>"
        f"<td>{gate['samples']}/{gate['minimum_samples']}</td>"
        "</tr>"
        for profile_name, profile in summary["phase4"]["profiles"].items()
        for gate in profile["gates"].values()
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Winsper E2E {html.escape(manifest['run_id'])}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:32px;background:#0f1117;color:#e8ecf3}}
.grid{{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:12px}}
.card{{background:#191d27;border:1px solid #2a3140;border-radius:14px;padding:16px}}
.value{{font-size:28px;font-weight:650}} table{{width:100%;border-collapse:collapse;margin-top:18px}}
th,td{{text-align:left;padding:9px;border-bottom:1px solid #2a3140;font-size:13px}}
.pass{{color:#42d392}}.fail,.error{{color:#ff6b6b}}.skip{{color:#9aa4b2}}
h1,h2{{font-weight:650}} small{{color:#9aa4b2}}
</style></head><body>
<h1>Winsper E2E Laboratory</h1><small>{html.escape(manifest['commit'])} · {html.escape(manifest['platform'])}</small>
<div class="grid">
<div class="card"><div>Pass rate</div><div class="value">{pass_rate}</div></div>
<div class="card"><div>Average score</div><div class="value">{format_optional(summary['average_score'], 2)}</div></div>
<div class="card"><div>p50</div><div class="value">{format_optional(summary['p50_ms'], 1)} ms</div></div>
<div class="card"><div>p95</div><div class="value">{format_optional(summary['p95_ms'], 1)} ms</div></div>
<div class="card"><div>Safety gates</div><div class="value">{html.escape(gate_state)}</div></div>
</div>
<p><strong>Phase 4:</strong> {phase4_state}</p>
<table><tr><th>Profile</th><th>Release metric</th><th>Status</th><th>Value</th><th>Target</th><th>Samples</th></tr>{phase4_rows}</table>
{phase5_block}
<p><small>Runner working set: {format_optional(summary['memory_min_mb'], 1)}–{format_optional(summary['memory_peak_mb'], 1)} MB
(growth {format_optional(summary['memory_growth_mb'], 1)} MB). Latency values are case runtimes; ASR RTF is reported separately.</small></p>
<h2>ASR model leaderboard</h2>
<table><tr><th>Model</th><th>Passed</th><th>Avg score</th><th>WER</th><th>Protected</th><th>RTF</th><th>Load ms</th></tr>{model_rows}</table>
<h2>Category statistics</h2>
<table><tr><th>Group</th><th>Passed</th><th>Avg score</th><th>p50 ms</th><th>p95 ms</th><th>WER</th><th>RTF</th><th>Skipped</th></tr>{group_rows}</table>
<h2>Cases</h2>
<table><tr><th>Case</th><th>Category</th><th>Model</th><th>Status</th><th>Score</th><th>Latency ms</th><th>Notes</th></tr>{rows}</table>
</body></html>"""


def print_summary(run_dir: Path, summary: dict[str, Any]) -> None:
    rate = "N/A" if summary["pass_rate"] is None else f"{summary['pass_rate']:.1%}"
    print(f"Executed {summary['executed']} of {summary['total']} cases: {summary['passed']} passed, {summary['failed']} failed.")
    print(f"Pass rate: {rate}; average score: {format_optional(summary['average_score'], 2)}/3")
    print(f"Latency: p50 {format_optional(summary['p50_ms'], 1)} ms; p95 {format_optional(summary['p95_ms'], 1)} ms")
    print(
        "Runner memory: "
        f"{format_optional(summary['memory_min_mb'], 1)}-{format_optional(summary['memory_peak_mb'], 1)} MB; "
        f"growth {format_optional(summary['memory_growth_mb'], 1)} MB"
    )
    if summary["gate_failures"]:
        print("FAILED SAFETY GATES: " + ", ".join(summary["gate_failures"]))
    if summary["unassessed_gates"]:
        print("UNASSESSED SAFETY GATES: " + ", ".join(summary["unassessed_gates"]))
    phase4 = summary["phase4"]
    print("Phase 4 release gates: " + ("PASS" if phase4["ready"] else "NOT CERTIFIED"))
    for profile_name, profile in phase4["profiles"].items():
        print(f"  {profile_name.upper()}: " + ("PASS" if profile["ready"] else "NOT CERTIFIED"))
        for gate in profile["gates"].values():
            print(
                f"    {gate['name']}: {gate['status']} "
                f"({gate['samples']}/{gate['minimum_samples']} samples, target {gate['target']})"
            )
    phase5 = summary["phase5"]
    if phase5["executed"]:
        print("Phase 5 Polish gates: " + ("PASS" if phase5["ready"] else "NOT CERTIFIED"))
        print(
            f"  coverage: {phase5['executed']}/{phase5['coverage_target']} cases; "
            f"failures: {phase5['failed']}; inference p95: {format_optional(phase5['warm_p95_ms'], 1)} ms "
            f"(target {phase5['latency_target_ms']:.0f} ms)"
        )
        if phase5["failed_gates"]:
            print("  failed gates: " + ", ".join(phase5["failed_gates"]))
        for branch, details in phase5["branches"].items():
            print(
                f"  {branch}: {details['passed']}/{details['executed']} passed; "
                f"inference p95: {format_optional(details['warm_p95_ms'], 1)} ms"
            )
            if details["failed_gates"]:
                print(f"    failed gates: {', '.join(details['failed_gates'])}")
    print(f"Report: {run_dir / 'report.html'}")


def average(values: list[float] | list[int]) -> float | None:
    return statistics.fmean(values) if values else None


def percentile(values: list[float], percentage: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentage / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def format_optional(value: float | None, digits: int) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path.cwd(),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def git_worktree_dirty() -> bool | None:
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=Path.cwd(),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return bool(output.strip())
    except Exception:
        return None


def source_fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted((value.resolve() for value in paths), key=lambda value: str(value).casefold()):
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def evidence_source_fingerprint(cases_path: Path) -> str:
    root = Path.cwd()
    return source_fingerprint(
        [
            root / "voicepilot" / "polish_prompts.py",
            root / "voicepilot" / "polish_prompt_constraints.py",
            root / "voicepilot" / "polish_prompt_support.py",
            root / "voicepilot" / "polish_service.py",
            root / "voicepilot" / "self_corrections.py",
            root / "voicepilot" / "rewrite_backends.py",
            root / "devtools" / "e2e_lab.py",
            root / "devtools" / "phase5_release.py",
            cases_path,
        ]
    )


def process_memory_mb(process_id: int | None = None) -> float | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        get_memory = kernel32.K32GetProcessMemoryInfo
        get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        get_memory.restype = wintypes.BOOL
        close_handle = False
        if process_id is None:
            process = kernel32.GetCurrentProcess()
        else:
            process = kernel32.OpenProcess(0x0400 | 0x0010, False, process_id)
            close_handle = True
            if not process:
                return None
        try:
            if not get_memory(process, ctypes.byref(counters), counters.cb):
                return None
            return counters.WorkingSetSize / (1024 * 1024)
        finally:
            if close_handle:
                kernel32.CloseHandle(process)
    except Exception:
        return None


def nvidia_process_memory_mb(process_id: int) -> float | None:
    rows = _run_nvidia_query(
        "--query-compute-apps=pid,used_memory",
        "--format=csv,noheader,nounits",
    )
    if rows is None:
        return None
    for line in rows:
        raw_pid, separator, raw_memory = line.partition(",")
        if not separator:
            continue
        try:
            if int(raw_pid.strip()) == process_id:
                return float(raw_memory.strip())
        except ValueError:
            continue
    return None


def nvidia_total_memory_mb() -> float | None:
    rows = _run_nvidia_query(
        "--query-gpu=memory.used",
        "--format=csv,noheader,nounits",
    )
    if not rows:
        return None
    try:
        return sum(float(line.strip()) for line in rows)
    except ValueError:
        return None


def _run_nvidia_query(*arguments: str) -> list[str] | None:
    try:
        completed = subprocess.run(
            ["nvidia-smi", *arguments],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode:
        return None
    return [line for line in completed.stdout.splitlines() if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
