from __future__ import annotations

import queue
import threading
import time
from dataclasses import replace

from .audio import RecordingTooShort
from .audio_factory import create_audio_recorder
from .config import AppConfig, load_config
from .control import request_control_command
from .hotkeys import GlobalHoldHotkeys
from .models import format_download_progress, quick_setup_model_for
from .runtime_state import read_runtime_state
from .settings_helpers import (
    audio_levels,
    dictation_model_status,
    friendly_check_error,
    stop_recorder_quietly,
)
from .transcribe import FasterWhisperTranscriber
from .vocabulary import effective_vocabulary


class SettingsHomeChecksMixin:
    """Interactive microphone, dictation, and hotkey checks for General."""

    def _start_home_mic_test(self) -> None:
        if self.home_test_kind:
            return
        config = load_config(self.config_path)
        self.home_test_kind = "mic"
        self._set_home_test_busy(True)
        self._set_home_check("Testing microphone", "Recording for 2 seconds. Speak normally.", "neutral")
        self._ensure_home_test_timer()
        threading.Thread(target=self._run_home_mic_test, args=(config,), name="WinsperSettingsMicTest", daemon=True).start()

    def _run_home_mic_test(self, config: AppConfig) -> None:
        recorder = create_audio_recorder(config.audio)
        try:
            recorder.start()
            time.sleep(2.0)
            clip = recorder.stop()
            peak, rms = audio_levels(clip.samples)
            if peak < 0.012:
                self.home_test_events.put(
                    ("warn", "Mic is very quiet", f"Peak {peak:.3f}, RMS {rms:.3f}. Move closer or choose another mic.")
                )
            else:
                self.home_test_events.put(
                    (
                        "done",
                        "Mic works",
                        f"Captured {clip.raw_duration_seconds or clip.duration_seconds:.1f}s. Peak {peak:.3f}, RMS {rms:.3f}.",
                    )
                )
        except RecordingTooShort as exc:
            self.home_test_events.put(("error", "Mic needs attention", str(exc)))
        except Exception as exc:
            self.home_test_events.put(("error", "Mic needs attention", friendly_check_error(exc)))
        finally:
            stop_recorder_quietly(recorder)

    def _start_home_dictation_test(self) -> None:
        if self.home_test_kind:
            return
        config = load_config(self.config_path)
        self.home_test_kind = "dictation"
        self._set_home_test_busy(True)
        self._set_home_check("Testing dictation", "Recording for 4 seconds. Speak a short sentence.", "neutral")
        self._ensure_home_test_timer()
        threading.Thread(target=self._run_home_dictation_test, args=(config,), name="WinsperSettingsDictationTest", daemon=True).start()

    def _run_home_dictation_test(self, config: AppConfig) -> None:
        recorder = create_audio_recorder(config.audio)
        started = time.perf_counter()
        try:
            recorder.start()
            time.sleep(4.0)
            clip = recorder.stop()
            transcriber = FasterWhisperTranscriber(config.speech, effective_vocabulary(config))
            selected_speech_config = transcriber.mode_config(config.dictation.ramble_model)
            test_model = quick_setup_model_for(selected_speech_config.model)
            speech_config = transcriber.mode_config(test_model)
            if speech_config.device == "cuda":
                speech_config = replace(speech_config, device="cpu", compute_type="int8")
                self.home_test_events.put(
                    (
                        "status",
                        "CPU fallback",
                        "Testing with CPU/int8 so dictation works even when NVIDIA CUDA runtime is not installed.",
                    )
                )
            title, detail = dictation_model_status(speech_config.model)
            if speech_config.model != selected_speech_config.model:
                title = "Quick dictation check"
                detail = f"Using {speech_config.model} so this test does not block on {selected_speech_config.model}. {detail}"
            self.home_test_events.put(("status", title, detail))
            load_started = time.perf_counter()
            transcriber.load_model(
                speech_config,
                progress_callback=lambda progress: self.home_test_events.put(
                    ("status", f"{progress.status}: {progress.model}", format_download_progress(progress))
                ),
            )
            load_elapsed = time.perf_counter() - load_started
            self.home_test_events.put(
                ("status", "Transcribing", f"Model ready in {load_elapsed:.1f}s. Processing {clip.duration_seconds:.1f}s locally.")
            )
            profile = config.profiles.styles.get(config.profiles.default_profile)
            text = transcriber.transcribe(clip, profile=profile, config=speech_config).strip()
            elapsed = time.perf_counter() - started
            if not text:
                self.home_test_events.put(("error", "No speech detected", "Check the microphone and try again."))
                return
            preview = text if len(text) <= 140 else f"{text[:137]}..."
            detail = f"{len(text.split())} words in {elapsed:.1f}s using {speech_config.model}: {preview}"
            self.home_test_events.put(("done", "Dictation works", detail))
        except RecordingTooShort as exc:
            self.home_test_events.put(("error", "Dictation needs attention", str(exc)))
        except Exception as exc:
            self.home_test_events.put(("error", "Dictation needs attention", friendly_check_error(exc)))
        finally:
            stop_recorder_quietly(recorder)

    def _start_home_hotkey_test(self) -> None:
        if self.home_test_kind:
            return
        self.home_test_kind = "hotkey"
        self._set_home_test_busy(True)
        self._set_home_check("Preparing hotkey test", "Pausing the listener briefly so this test does not start dictation.", "neutral")
        self.home_resume_listener_after_hotkey = False
        running = self._listener_is_running()
        state = read_runtime_state(self.config_path, max_age_seconds=60) if running else None
        if running and state is None:
            self._set_home_check("Restart needed", "Restart Winsper once before using the safe hotkey test.", "warn")
            self.home_test_kind = ""
            self._set_home_test_busy(False)
            return
        if running and not (state and state.paused):
            self.home_resume_listener_after_hotkey = True
            try:
                request_control_command(self.config_path, "pause")
            except Exception:
                self.home_resume_listener_after_hotkey = False
        from PySide6.QtCore import QTimer

        QTimer.singleShot(450 if running else 0, self._begin_home_hotkey_test)

    def _begin_home_hotkey_test(self) -> None:
        if self.home_test_kind != "hotkey":
            return
        self._set_home_check("Listening for hotkey", f"Hold and release {self.config.hotkeys.dictate}.", "neutral")
        self._ensure_home_test_timer()
        self.home_hotkey_tester = GlobalHoldHotkeys(
            dictate_combo=self.config.hotkeys.dictate,
            polish_combo="",
            rewrite_combo="",
            on_start=lambda mode: self.home_test_events.put(("hotkey_start", mode, "")),
            on_stop=lambda mode: self.home_test_events.put(("hotkey_stop", mode, "")),
            windows_poll_only=True,
        )
        try:
            self.home_hotkey_tester.start()
        except Exception as exc:
            self.home_test_events.put(("error", "Hotkey needs attention", friendly_check_error(exc)))
            return
        from PySide6.QtCore import QTimer

        QTimer.singleShot(12000, self._home_hotkey_timeout)

    def _home_hotkey_timeout(self) -> None:
        if self.home_test_kind == "hotkey":
            self.home_test_events.put(
                ("error", "Hotkey not detected", f"Try holding {self.config.hotkeys.dictate}, or choose another shortcut.")
            )

    def _ensure_home_test_timer(self) -> None:
        if self.home_test_timer is not None:
            return
        from PySide6.QtCore import QTimer

        self.home_test_timer = QTimer(self.window)
        self.home_test_timer.timeout.connect(self._poll_home_test_events)
        self.home_test_timer.start(120)

    def _poll_home_test_events(self) -> None:
        while True:
            try:
                event, title, detail = self.home_test_events.get_nowait()
            except queue.Empty:
                return
            if event == "status":
                self._set_home_check(title, detail, "neutral")
            elif event == "warn":
                self._set_home_check(title, detail, "warn")
                self._finish_home_test()
            elif event == "done":
                self._set_home_check(title, detail, "good")
                self._finish_home_test()
            elif event == "error":
                self._set_home_check(title, detail, "bad")
                self._finish_home_test()
            elif event == "hotkey_start":
                self._set_home_check("Hotkey detected", "Release it to finish the check.", "good")
            elif event == "hotkey_stop":
                self._set_home_check("Hotkey works", f"Dictate shortcut detected: {self.config.hotkeys.dictate}.", "good")
                self._finish_home_test()

    def _finish_home_test(self) -> None:
        if self.home_test_kind == "hotkey":
            self._stop_home_hotkey_test()
        self.home_test_kind = ""
        self._set_home_test_busy(False)
        if self.home_test_timer is not None:
            self.home_test_timer.stop()
            self.home_test_timer = None

    def _stop_home_hotkey_test(self) -> None:
        if self.home_hotkey_tester is not None:
            self.home_hotkey_tester.stop()
            self.home_hotkey_tester = None
        if self.home_resume_listener_after_hotkey:
            try:
                request_control_command(self.config_path, "resume")
            except Exception:
                pass
        self.home_resume_listener_after_hotkey = False

    def _cleanup_home_tests(self) -> None:
        self._stop_home_hotkey_test()
        self._stop_model_download_timer()
        if self.polish_test_timer is not None:
            self.polish_test_timer.stop()
            self.polish_test_timer = None
        if self.home_test_timer is not None:
            self.home_test_timer.stop()
            self.home_test_timer = None
        self.home_test_kind = ""

    def _set_home_test_busy(self, busy: bool) -> None:
        for button in self.home_test_buttons.values():
            button.setEnabled(not busy)

    def _set_home_check(self, status: str, detail: str, tone: str) -> None:
        if self.home_check_status is None or self.home_check_result is None:
            return
        self.home_check_status.show()
        self.home_check_result.show()
        self.home_check_status.setText(status)
        self.home_check_result.setText(detail)
        self._set_tone(self.home_check_status, tone)
