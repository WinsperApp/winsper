from __future__ import annotations

import argparse
import gc
import json
import os
import tempfile
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from voicepilot.action_state import ActionCoordinator, ActionPhase
from voicepilot.app import LastInsertion, WinsperApp
from voicepilot.app_context import ForegroundContext, WindowInfo
from voicepilot.audio import AudioCaptureDiagnostics, AudioClip, AudioStartMetrics, MicrophoneUnavailable
from voicepilot.config import AppConfig, ProfileStyle
from voicepilot.lifecycle_control import CANCEL_BACKEND_GRACE_SECONDS
from voicepilot.paste import InsertResult
from voicepilot.polish_service import TextRewriter
from voicepilot.selection import SelectionResult
from voicepilot.workers import BoundedWorker


@dataclass(frozen=True)
class SoakTargets:
    dictations: int = 1_000
    polish: int = 250
    cancellations: int = 100
    device_changes: int = 50
    sleep_resumes: int = 30


class DeterministicBackend:
    """Local completion adapter: exercises production prompts, not model quality."""

    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def complete(self, prompt: str, *, num_predict: int) -> str:
        if self.closed:
            raise RuntimeError("completion after close")
        if num_predict < 1:
            raise RuntimeError("invalid completion budget")
        self.calls += 1
        if "<<<SELECTED_TEXT>>>" in prompt:
            return "Release ready."
        return "The Q2 report is ready."

    def close(self) -> None:
        self.closed = True


class _Recorder:
    def __init__(self) -> None:
        self.next_text = ""
        self.fail_next_start = False
        self.active = False
        self.closed = False
        self.start_calls = 0
        self.stop_calls = 0
        self.start_failures = 0
        self.last_capture_diagnostics = AudioCaptureDiagnostics(
            device_label="Soak microphone",
            host_api="deterministic",
            sample_rate=16_000,
            channels=1,
            clip_duration_seconds=0.75,
            peak_level=0.1,
            silent_sample_ratio=0.0,
            stop_ms=0.1,
        )

    def start(self) -> AudioStartMetrics:
        if self.closed:
            raise RuntimeError("recording after close")
        if self.fail_next_start:
            self.fail_next_start = False
            self.start_failures += 1
            raise MicrophoneUnavailable("simulated endpoint replacement")
        if self.active:
            raise RuntimeError("overlapping recording")
        self.active = True
        self.start_calls += 1
        return AudioStartMetrics(
            stream_start_ms=0.1,
            first_frame_ms=0.2,
            attempts=1,
            first_frame_received=True,
            device_label="Soak microphone",
        )

    def wait_for_first_frame(self, _timeout: float) -> bool:
        return self.active

    def stop(self) -> AudioClip:
        if not self.active:
            raise RuntimeError("recording stop without start")
        self.active = False
        self.stop_calls += 1
        clip = AudioClip([0.1, -0.1, 0.08, -0.08], 16_000, 0.75)
        clip.soak_text = self.next_text
        return clip

    def drain_warnings(self) -> list[str]:
        return []

    def take_device_identity_update(self):
        return None

    def warm_up(self) -> bool:
        return True

    def close(self) -> None:
        self.active = False
        self.closed = True


class _Transcriber:
    def __init__(self, config) -> None:
        self.config = config
        self.calls = 0
        self.cancels = 0
        self.closed = False
        self.block_next = False
        self.blocked = threading.Event()
        self._active_cancel: threading.Event | None = None
        self._lock = threading.Lock()

    def mode_config(self, model: str):
        return replace(self.config, model=model)

    def transcribe(self, clip, *, on_partial=None, **_kwargs) -> str:
        if self.closed:
            raise RuntimeError("transcription after close")
        self.calls += 1
        text = str(getattr(clip, "soak_text", ""))
        cancel_event = threading.Event()
        with self._lock:
            should_block = self.block_next
            self.block_next = False
            self._active_cancel = cancel_event
        try:
            if should_block:
                self.blocked.set()
                cancel_event.wait(2.0)
            if on_partial and text:
                on_partial(text[: min(len(text), 24)])
            return text
        finally:
            with self._lock:
                if self._active_cancel is cancel_event:
                    self._active_cancel = None
            self.blocked.clear()

    def cancel(self) -> None:
        self.cancels += 1
        with self._lock:
            active = self._active_cancel
        if active is not None:
            active.set()

    def close(self) -> None:
        self.cancel()
        self.closed = True


class _Inserter:
    def __init__(self) -> None:
        self.selection = SelectionResult.no_selection("soak")
        self.insertion_count = 0
        self.copy_count = 0
        self.key_count = 0
        self.last_inserted = ""

    def read_selection(self, *, window_hwnd: int = 0) -> SelectionResult:
        del window_hwnd
        return self.selection

    def paste_text(self, text: str, **_kwargs) -> InsertResult:
        self.insertion_count += 1
        self.last_inserted = text
        return InsertResult(True, False, "verified", verified=True)

    def insert_below_selection(self, text: str, **_kwargs) -> InsertResult:
        return self.paste_text(text)

    def copy_text(self, text: str) -> None:
        self.copy_count += 1
        self.last_inserted = text

    def press_key(self, _key: str) -> None:
        self.key_count += 1


class _History:
    def __init__(self) -> None:
        self.event_count = 0
        self.source_count = 0

    def append(self, _event) -> None:
        self.event_count += 1

    def update_source(self, _event_id: str, _source: str) -> None:
        self.source_count += 1


class _Hud:
    def __init__(self) -> None:
        self.events: deque[tuple[str, str, str]] = deque(maxlen=256)
        self.action_events = 0
        self.stopped = False

    def show(self, title: str, subtitle: str = "", kind: str = "idle") -> None:
        self.events.append((title, subtitle, kind))

    def show_action_message(
        self,
        _action_id: int,
        title: str,
        subtitle: str = "",
        kind: str = "idle",
    ) -> None:
        self.show(title, subtitle, kind)

    def show_action_event(self, _event) -> None:
        self.action_events += 1

    def stop(self) -> None:
        self.stopped = True


class _Tray:
    def __init__(self) -> None:
        self.paused = False
        self.stopped = False

    def set_paused(self, value: bool) -> None:
        self.paused = value

    def refresh_entitlement(self) -> None:
        pass

    def close_owned_windows(self) -> None:
        pass

    def stop(self) -> None:
        self.stopped = True


class _ContextDetector:
    def __init__(self, context: ForegroundContext) -> None:
        self.context = context

    def detect_fast(self, _window=None) -> ForegroundContext:
        return self.context

    def refresh_window(self, _window) -> ForegroundContext:
        return self.context


class _SoakApp(WinsperApp):
    """Winsper production action path with deterministic boundary adapters."""

    def __init__(self, config_path: Path) -> None:
        self.config = AppConfig()
        self.config.hotkeys.tap_to_toggle_dictation = False
        self.config.speech.preload_on_startup = False
        self.config.paste.paste_delay_ms = 0
        self.config.history.enabled = False
        self.config.correction_memory.enabled = False
        self.config.snippets.enabled = False
        self.config.rewrite.preview_before_apply = False
        self.config_path = config_path
        self.context = ForegroundContext(
            process_name="notepad.exe",
            window_title="Soak document",
            profile_name="notes",
            profile=ProfileStyle(label="Notes"),
            window_hwnd=4242,
        )
        self.context_detector = _ContextDetector(self.context)
        self.recorder = _Recorder()
        self.transcriber = _Transcriber(self.config.speech)
        self.inserter = _Inserter()
        self.backend = DeterministicBackend()
        self.rewriter = TextRewriter(self.config.rewrite, [], backend=self.backend)
        self.corrections = type(
            "Corrections",
            (),
            {"apply": staticmethod(lambda text, _profile: text)},
        )()
        self.history = _History()
        self.hud = _Hud()
        self.tray = _Tray()
        self.entitlements = None
        self.last = LastInsertion()
        self.hotkeys = None
        self._lock = threading.Lock()
        self._capture_audio_lock = threading.Lock()
        self._capture_monitor_cancel = None
        self._capture_monitor_action_id = 0
        self._coordinator = ActionCoordinator()
        self._active_started_at = 0.0
        self._is_toggle = False
        self._action_context = None
        self._reload_pending = False
        self._reload_pending_silent = True
        self._stop_event = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._shutdown_complete = threading.Event()
        self._action_worker = BoundedWorker("WinsperActionSoak")
        self._context_thread = None
        self._preload_thread = None
        self._speech_replacement_thread = None
        self._rewrite_preload_thread = None
        self._rewrite_preload_deferred = False
        self._rewrite_preloaded_for = None
        self._rewrite_preload_rewriter = None
        self._rewrite_preload_cancel_event = None
        self._license_refresh_thread = None
        self._context_result = None
        self._context_action_id = 0
        self._polish_selection_captures = {}
        self.usage_actions = 0
        self.runtime_states: deque[tuple[str, str, bool | None]] = deque(maxlen=64)

    @staticmethod
    def _target_is_current(_context: ForegroundContext) -> bool:
        return True

    def _record_usage_safely(self, _words: int) -> None:
        self.usage_actions += 1

    def _write_runtime_state(
        self,
        status: str,
        detail: str = "",
        paused: bool | None = None,
    ) -> None:
        self.runtime_states.append((status, detail, paused))


class RuntimeSoak:
    def __init__(self, targets: SoakTargets) -> None:
        self.targets = targets
        self.counts = {name: 0 for name in asdict(targets)}
        self.errors: list[str] = []
        self.successful_actions = 0
        self.recovery_probes = 0
        self.selection_rewrites = 0

    def run(self) -> dict[str, Any]:
        started = time.perf_counter()
        window = WindowInfo(4242, "notepad.exe", "Soak document")
        with tempfile.TemporaryDirectory(prefix="winsper-action-soak-") as temp:
            app = _SoakApp(Path(temp) / "config.yaml")
            try:
                with (
                    patch(
                        "voicepilot.lifecycle_capture.get_foreground_window_details",
                        return_value=window,
                    ),
                    patch(
                        "voicepilot.app_pipeline.get_foreground_window_details",
                        return_value=window,
                    ),
                    patch(
                        "voicepilot.lifecycle_capture.polish_setup_issue",
                        return_value=None,
                    ),
                ):
                    for _ in range(5):
                        self._run_action(app, "dictate", "The warm-up is ready.")
                    for index in range(2):
                        self._run_polish(app, selected=bool(index % 2))
                    # Warm every recovery path before measuring steady-state
                    # growth. Otherwise the first cancellation timer, endpoint
                    # recovery, and pause/resume allocations are incorrectly
                    # counted as a long-session leak.
                    self._cancel(app, processing=False)
                    self._cancel(app, processing=True)
                    self._device_change(app)
                    self._sleep_resume(app)
                    time.sleep(CANCEL_BACKEND_GRACE_SECONDS + 0.1)
                    gc.collect()
                    memory_before = process_memory_mb()
                    memory_after_500 = None

                    for _ in range(self.targets.dictations):
                        self._run_action(app, "dictate", "The Q2 report is ready.")
                        self.counts["dictations"] += 1
                        if self.counts["dictations"] == 500:
                            gc.collect()
                            memory_after_500 = process_memory_mb()
                    for index in range(self.targets.polish):
                        self._run_polish(app, selected=bool(index % 2))
                        self.counts["polish"] += 1
                    for index in range(self.targets.cancellations):
                        self._cancel(app, processing=bool(index % 2))
                        self.counts["cancellations"] += 1
                    for _ in range(self.targets.device_changes):
                        self._device_change(app)
                        self.counts["device_changes"] += 1
                    for _ in range(self.targets.sleep_resumes):
                        self._sleep_resume(app)
                        self.counts["sleep_resumes"] += 1

                    # Processing cancellation intentionally keeps a bounded
                    # recovery timer alive for the backend grace period. Give
                    # those production timers time to release their app/worker
                    # references before measuring settled-session memory.
                    settle_seconds = (
                        CANCEL_BACKEND_GRACE_SECONDS + 0.1
                        if self.targets.cancellations
                        else 0.0
                    )
                    if settle_seconds:
                        time.sleep(settle_seconds)
                    gc.collect()
                    memory_after = process_memory_mb()
            except Exception as exc:
                self.errors.append(f"{type(exc).__name__}: {exc}")
                memory_before = locals().get("memory_before")
                memory_after_500 = locals().get("memory_after_500")
                memory_after = process_memory_mb()
            finally:
                app.shutdown()

        expected = asdict(self.targets)
        counts_match = self.counts == expected
        memory_available = memory_before is not None and memory_after is not None
        memory_growth_percent = percent_growth(memory_before or 0.0, memory_after or 0.0)
        checkpoint_available = memory_after_500 is not None
        first_500_growth_percent = (
            percent_growth(memory_before or 0.0, memory_after_500 or 0.0)
            if checkpoint_available
            else memory_growth_percent
        )
        steady_growth_percent = (
            percent_growth(memory_after_500 or 0.0, memory_after or 0.0)
            if checkpoint_available
            else 0.0
        )
        # Repeated actions may fill small, bounded runtime caches. Use the
        # 500-action checkpoint to distinguish that from continuing growth.
        memory_gate_growth_percent = (
            steady_growth_percent if checkpoint_available else memory_growth_percent
        )
        warmup_growth_mb = (
            max(0.0, (memory_after_500 or 0.0) - (memory_before or 0.0))
            if checkpoint_available
            else 0.0
        )
        expected_recoveries = (
            self.targets.cancellations
            + self.targets.device_changes
            + self.targets.sleep_resumes
            + 4  # two cancellations, one device change, and one resume warm-up
        )
        closed = bool(
            app.recorder.closed
            and app.transcriber.closed
            and app.backend.closed
            and app.hud.stopped
            and app.tray.stopped
            and app._shutdown_complete.is_set()
        )
        report = {
            "evidence_level": "application-action-soak",
            "targets": expected,
            "completed": dict(self.counts),
            "counts_match": counts_match,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "memory_before_mb": None if memory_before is None else round(memory_before, 3),
            "memory_after_500_mb": (
                None if memory_after_500 is None else round(memory_after_500, 3)
            ),
            "memory_after_mb": None if memory_after is None else round(memory_after, 3),
            "memory_growth_percent": round(memory_growth_percent, 3),
            "first_500_growth_percent": round(first_500_growth_percent, 3),
            "steady_growth_percent": round(steady_growth_percent, 3),
            "memory_gate_growth_percent": round(memory_gate_growth_percent, 3),
            "memory_warmup_growth_mb": round(warmup_growth_mb, 3),
            "memory_warmup_budget_mb": 16.0,
            "memory_gate_percent": 5.0,
            "memory_ready": (
                memory_available
                and memory_gate_growth_percent < 5.0
                and warmup_growth_mb < 16.0
            ),
            "settle_seconds": round(locals().get("settle_seconds", 0.0), 3),
            "pipeline": {
                "successful_actions": self.successful_actions,
                "recovery_probes": self.recovery_probes,
                "expected_recovery_probes": expected_recoveries,
                "selection_rewrites": self.selection_rewrites,
                "transcriptions": app.transcriber.calls,
                "transcription_cancels": app.transcriber.cancels,
                "completion_calls": app.backend.calls,
                "insertions": app.inserter.insertion_count,
                "history_checkpoints": app.history.event_count,
                "usage_actions": app.usage_actions,
                "microphone_starts": app.recorder.start_calls,
                "microphone_stops": app.recorder.stop_calls,
                "device_start_failures": app.recorder.start_failures,
                "hud_action_events": app.hud.action_events,
            },
            "warmup": {
                "dictations": 5,
                "polish": 2,
                "cancellations": 2,
                "device_changes": 1,
                "sleep_resumes": 1,
            },
            "closed_cleanly": closed,
            "final_phase": app._coordinator.query().phase.name,
            "errors": list(self.errors),
            "covered": [
                "production hotkey start/stop and capture lifecycle",
                "production dictation and both Polish branches",
                "production worker, prompt, history, and insertion transaction",
                "capture and in-flight transcription cancellation",
                "microphone-start failure followed by successful action recovery",
                "pause/resume followed by successful action recovery",
                "bounded production shutdown",
            ],
            "not_covered": [
                "physical microphone signal or device replacement",
                "real Windows sleep/resume",
                "real ASR or LLM inference",
                "OS clipboard, registered global hotkey, or external focused-app insertion",
            ],
        }
        pipeline_ready = bool(
            report["pipeline"]["recovery_probes"] == expected_recoveries
            and report["pipeline"]["insertions"] == self.successful_actions
            and report["pipeline"]["history_checkpoints"] == self.successful_actions
            and report["pipeline"]["usage_actions"] == self.successful_actions
            and report["pipeline"]["device_start_failures"]
            == self.targets.device_changes + 1
        )
        report["ready"] = bool(
            counts_match
            and report["memory_ready"]
            and pipeline_ready
            and closed
            and report["final_phase"] == ActionPhase.SHUTTING_DOWN.name
            and not self.errors
        )
        return report

    def _run_action(
        self,
        app: _SoakApp,
        mode: str,
        text: str,
        *,
        selected_text: str = "",
    ) -> None:
        before = app.inserter.insertion_count
        app.recorder.next_text = text
        app.inserter.selection = (
            SelectionResult.captured(selected_text, "soak")
            if selected_text
            else SelectionResult.no_selection("soak")
        )
        app._on_hotkey_start(mode)
        state = app._coordinator.query()
        if state.phase is not ActionPhase.CAPTURING:
            raise RuntimeError(f"{mode} did not enter capture: {state.phase.name}")
        app._on_hotkey_stop(mode)
        self._wait_idle(app)
        if app.inserter.insertion_count != before + 1:
            raise RuntimeError(f"{mode} did not complete one insertion")
        self.successful_actions += 1

    def _run_polish(self, app: _SoakApp, *, selected: bool) -> None:
        if selected:
            self._run_action(
                app,
                "polish",
                "Make this concise.",
                selected_text="The release candidate is fully prepared for distribution.",
            )
            self.selection_rewrites += 1
        else:
            self._run_action(app, "polish", "um the Q2 report is ready")

    def _cancel(self, app: _SoakApp, *, processing: bool) -> None:
        app.recorder.next_text = "This action will be cancelled."
        app.inserter.selection = SelectionResult.no_selection("soak")
        if processing:
            app.transcriber.block_next = True
        app._on_hotkey_start("dictate")
        if processing:
            app._on_hotkey_stop("dictate")
            if not app.transcriber.blocked.wait(2.0):
                raise RuntimeError("transcription cancellation did not reach the backend")
        app.cancel_current_action()
        self._wait_idle(app)
        self._run_action(app, "dictate", "Cancellation recovery is ready.")
        self.recovery_probes += 1

    def _device_change(self, app: _SoakApp) -> None:
        app.recorder.fail_next_start = True
        app._on_hotkey_start("dictate")
        if app._coordinator.query().phase is not ActionPhase.IDLE:
            raise RuntimeError("microphone failure did not return to idle")
        self._run_action(app, "dictate", "Microphone recovery is ready.")
        self.recovery_probes += 1

    def _sleep_resume(self, app: _SoakApp) -> None:
        app.pause_listening()
        if app._coordinator.query().phase is not ActionPhase.PAUSED:
            raise RuntimeError("pause did not enter paused state")
        app.resume_listening()
        if app._coordinator.query().phase is not ActionPhase.IDLE:
            raise RuntimeError("resume did not return to idle")
        self._run_action(app, "dictate", "Resume recovery is ready.")
        self.recovery_probes += 1

    @staticmethod
    def _wait_idle(app: _SoakApp, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (
                app._coordinator.query().phase is ActionPhase.IDLE
                and not app._action_worker.busy
            ):
                return
            time.sleep(0.001)
        state = app._coordinator.query()
        raise RuntimeError(
            f"action did not drain: phase={state.phase.name}; stage={state.stage.name}"
        )


def process_memory_mb() -> float | None:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except (ImportError, OSError):
        pass
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

        counters = Counters(cb=ctypes.sizeof(Counters))
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_memory = kernel32.K32GetProcessMemoryInfo
        get_memory.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        get_memory.restype = wintypes.BOOL
        if not get_memory(
            kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        ):
            return None
        return counters.WorkingSetSize / (1024 * 1024)
    except (AttributeError, OSError):
        return None


def percent_growth(before: float, after: float) -> float:
    if before <= 0:
        return 0.0
    return max(0.0, (after - before) / before * 100.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run Winsper's production application-action soak with "
            "deterministic boundary adapters."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/runtime-soak.json"),
    )
    parser.add_argument("--dictations", type=int, default=1_000)
    parser.add_argument("--polish", type=int, default=250)
    parser.add_argument("--cancellations", type=int, default=100)
    parser.add_argument("--device-changes", type=int, default=50)
    parser.add_argument("--sleep-resumes", type=int, default=30)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    targets = SoakTargets(
        dictations=max(0, args.dictations),
        polish=max(0, args.polish),
        cancellations=max(0, args.cancellations),
        device_changes=max(0, args.device_changes),
        sleep_resumes=max(0, args.sleep_resumes),
    )
    report = RuntimeSoak(targets).run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Application-action soak: {'PASS' if report['ready'] else 'FAIL'}; "
        f"memory gate growth {report['memory_gate_growth_percent']:.2f}% "
        f"(total {report['memory_growth_percent']:.2f}%); report {args.output}"
    )
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
