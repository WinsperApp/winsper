import tempfile
import threading
import time
from pathlib import Path

from voicepilot.config import AppConfig, load_config
from voicepilot.corrections import CorrectionStore, make_rule
from voicepilot.transcribe import FasterWhisperTranscriber
from voicepilot.polish_service import TextRewriter, protect_vocabulary_spellings
from voicepilot.workers import BoundedWorker


def test_protected_vocabulary_repairs_small_model_spelling_drift_only():
    assert protect_vocabulary_spellings(
        "Hi Dawn. Regards, Soumya.",
        "Hi Dawn. Regards, Soumy.",
        ["Soumya", "JSON"],
    ) == "Hi Dawn. Regards, Soumya."
    assert protect_vocabulary_spellings(
        "Ask Soumya, then Samuel.",
        "Ask Samuel.",
        ["Soumya"],
    ) == "Ask Samuel."
    assert protect_vocabulary_spellings(
        "Send JSON to Jason.",
        "Send JSON to Jason.",
        ["JSON"],
    ) == "Send JSON to Jason."
    assert protect_vocabulary_spellings(
        "Soumya asked Soumya to review it.",
        "Soumya asked Soumy to review it.",
        ["Soumya"],
    ) == "Soumya asked Soumya to review it."


def test_every_rewrite_backend_gets_zero_latency_dictionary_protection():
    class Backend:
        @staticmethod
        def complete(_prompt, *, num_predict):
            assert num_predict > 0
            return "Regards,\nSoumy"

    result = TextRewriter(AppConfig().rewrite, ["Soumya"], backend=Backend()).polish("Regards, Soumya.")

    assert result == "Regards,\nSoumya"


def test_transcriber_uses_bounded_vad_parameters():
    from types import SimpleNamespace

    import numpy as np

    from voicepilot.audio import AudioClip

    captured = {}

    class Model:
        def transcribe(self, _audio, **kwargs):
            captured.update(kwargs)
            return iter([SimpleNamespace(text=" hello")]), None

    transcriber = FasterWhisperTranscriber(AppConfig().speech, [])
    transcriber.load_model = lambda *_args, **_kwargs: Model()
    clip = AudioClip(np.zeros(16000, dtype="float32"), 16000, 1.0)
    assert transcriber.transcribe(clip) == "hello"
    assert captured["vad_parameters"]["min_speech_duration_ms"] == 96
    assert captured["vad_parameters"]["min_silence_duration_ms"] == 800
    assert captured["vad_parameters"]["threshold"] == 0.5
    assert captured["condition_on_previous_text"] is False


def test_cuda_inference_failure_stays_on_cpu_for_session():
    from types import SimpleNamespace

    import numpy as np

    from voicepilot.audio import AudioClip

    calls = []

    class Model:
        def __init__(self, device):
            self.device = device

        def transcribe(self, _audio, **_kwargs):
            calls.append(self.device)

            def segments():
                if self.device == "cuda":
                    raise RuntimeError("Library cublas64_12.dll is not found")
                yield SimpleNamespace(text=" recovered")

            return segments(), None

    config = AppConfig().speech
    config.device = "cuda"
    config.compute_type = "float16"
    fallbacks = []
    transcriber = FasterWhisperTranscriber(
        config, [], on_device_fallback=lambda requested, fallback: fallbacks.append((requested, fallback))
    )
    transcriber.load_model = lambda speech_config, **_kwargs: Model(speech_config.device)
    clip = AudioClip(np.zeros(16000, dtype="float32"), 16000, 1.0)
    assert transcriber.transcribe(clip) == "recovered"
    assert transcriber.transcribe(clip) == "recovered"
    assert calls == ["cuda", "cpu", "cpu"]
    assert len(fallbacks) == 1
    assert fallbacks[0][1].device == "cpu"


def test_cuda_language_detection_failure_falls_back_to_cpu():
    from types import SimpleNamespace

    import numpy as np

    from voicepilot.audio import AudioClip

    calls = []

    class Model:
        def __init__(self, device):
            self.device = device

        def transcribe(self, _audio, **kwargs):
            calls.append((self.device, kwargs["language"]))
            if self.device == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            return iter([SimpleNamespace(text=" recovered")]), None

    config = AppConfig().speech
    config.device = "cuda"
    config.compute_type = "float16"
    config.language = ""
    fallbacks = []
    transcriber = FasterWhisperTranscriber(
        config, [], on_device_fallback=lambda requested, fallback: fallbacks.append((requested, fallback))
    )
    transcriber.load_model = lambda speech_config, **_kwargs: Model(speech_config.device)
    clip = AudioClip(np.zeros(16000, dtype="float32"), 16000, 1.0)

    assert transcriber.transcribe(clip) == "recovered"
    assert calls == [("cuda", None), ("cpu", None)]
    assert len(fallbacks) == 1
    assert fallbacks[0][1].device == "cpu"


def test_cuda_model_load_failure_notifies_cpu_fallback():
    import sys
    from types import SimpleNamespace
    from unittest.mock import patch

    calls = []

    class WhisperModel:
        def __init__(self, _model, *, device, compute_type):
            calls.append((device, compute_type))
            if device == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found")

    config = AppConfig().speech
    config.model = "local-whisper-model"
    config.device = "cuda"
    config.compute_type = "float16"
    fallbacks = []
    transcriber = FasterWhisperTranscriber(
        config,
        [],
        on_device_fallback=lambda requested, fallback: fallbacks.append((requested, fallback)),
    )

    with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=WhisperModel)}):
        assert transcriber.load_model(config) is not None

    assert calls == [("cuda", "float16"), ("cpu", "int8")]
    assert len(fallbacks) == 1
    assert fallbacks[0][0].device == "cuda"
    assert fallbacks[0][1].device == "cpu"
    assert fallbacks[0][1].compute_type == "int8"


def test_persisted_speech_fallback_is_written_to_durable_runtime_log(tmp_path):
    from dataclasses import replace
    from threading import RLock
    from unittest.mock import patch

    from voicepilot.app_speech_backend import SpeechBackendLifecycleMixin
    from voicepilot.config import AppConfig, load_config, save_config

    class Harness(SpeechBackendLifecycleMixin):
        pass

    path = tmp_path / "config.yaml"
    config = AppConfig()
    config.speech.device = "cuda"
    config.speech.compute_type = "float16"
    save_config(config, path)
    harness = Harness()
    harness.config = config
    harness.config_path = path
    harness._lock = RLock()
    fallback = replace(config.speech, device="cpu", compute_type="int8")

    with patch("voicepilot.app_speech_backend.write_runtime_log") as runtime_log:
        harness._persist_speech_device_fallback(config.speech, fallback)

    saved = load_config(path)
    assert (saved.speech.device, saved.speech.compute_type) == ("cpu", "int8")
    runtime_log.assert_called_once()
    assert runtime_log.call_args.args[:2] == (path, "speech acceleration fallback")
    assert "using cpu/int8" in runtime_log.call_args.args[2]


def test_isolated_preload_forwards_cuda_fallback_to_parent():
    from dataclasses import replace

    from voicepilot.isolated_transcribe import IsolatedSpeechTranscriber

    config = AppConfig().speech
    requested = replace(config, device="cuda", compute_type="float16")
    fallback = replace(config, device="cpu", compute_type="int8")
    received = []
    transcriber = IsolatedSpeechTranscriber(config, [])
    transcriber.on_device_fallback = lambda wanted, actual: received.append((wanted, actual))
    messages = iter(
        [
            {"kind": "fallback", "requested": requested, "fallback": fallback},
            {"kind": "result", "text": ""},
        ]
    )
    transcriber._send = lambda _payload, **_kwargs: object()
    transcriber._receive = lambda _request_id, _session: next(messages)

    assert transcriber.load_model(requested)
    assert received == [(requested, fallback)]


def test_bounded_worker_rejects_parallel_work():
    import threading

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    worker = BoundedWorker("WinsperTestWorker")

    def task():
        started.set()
        release.wait(2)
        finished.set()

    assert worker.submit(task)
    assert started.wait(1)
    assert not worker.submit(lambda: None)
    release.set()
    assert finished.wait(1)
    assert worker.stop()
    assert not worker.submit(lambda: None)


def test_gui_child_receives_graceful_close_before_forced_fallback():
    from unittest.mock import patch

    from voicepilot.process_control import close_process_gracefully

    class Process:
        pid = 321

        def __init__(self):
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            assert timeout > 0
            self.returncode = 0
            return 0

        def terminate(self):
            self.terminated = True

    process = Process()
    close_requests = []
    with patch("voicepilot.process_control.request_process_windows_close", side_effect=close_requests.append):
        assert close_process_gracefully(process, timeout=1.0)

    assert close_requests == [321]
    assert not process.terminated


def test_tray_closes_every_owned_window_process():
    from unittest.mock import patch

    from voicepilot.tray import WinsperTray

    settings_process = object()
    history_process = object()
    with WinsperTray._window_lock:
        WinsperTray._window_processes = {
            "--settings": settings_process,
            "--history": history_process,
        }
    tray = WinsperTray.__new__(WinsperTray)
    closed = []
    with patch("voicepilot.tray.close_process_gracefully", side_effect=closed.append):
        tray.close_owned_windows()

    assert closed == [settings_process, history_process]


def test_tray_copy_last_result_invokes_recovery_callback():
    from voicepilot.tray import WinsperTray

    copied = []
    tray = WinsperTray.__new__(WinsperTray)
    tray.on_copy_last_result = lambda: copied.append(True)

    tray._copy_last_result()

    assert copied == [True]
    assert WinsperTray._window_processes == {}


def test_app_shutdown_is_ordered_idempotent_and_survives_component_errors(tmp_path):
    import threading

    from voicepilot.app import WinsperApp

    events = []

    class Component:
        def __init__(self, label, fail=False):
            self.label = label
            self.fail = fail

        def stop(self):
            events.append(self.label)
            if self.fail:
                raise RuntimeError(self.label)

        def close(self):
            self.stop()

    class Tray(Component):
        def close_owned_windows(self):
            events.append("windows")

    class Worker:
        def stop(self, timeout):
            events.append(f"worker:{timeout}")
            return True

    app = WinsperApp.__new__(WinsperApp)
    app.config_path = tmp_path / "config.yaml"
    app._stop_event = threading.Event()
    app._lock = threading.Lock()
    app._shutdown_lock = threading.Lock()
    app._shutdown_started = False
    app._shutdown_complete = threading.Event()
    app.hotkeys = Component("hotkeys")
    app.tray = Tray("tray")
    app.recorder = Component("microphone", fail=True)
    app.rewriter = Component("rewrite")
    app._action_worker = Worker()
    app._context_thread = None
    app._preload_thread = None
    app.hud = Component("hud")
    app._discard_active_recording = lambda: events.append("recording")
    app._write_runtime_state = lambda status, detail: events.append(f"state:{status}:{detail}")

    app.shutdown()
    app.shutdown()

    assert app._stop_event.is_set()
    assert events[:5] == [
        "hotkeys",
        "windows",
        "tray",
        "recording",
        "microphone",
    ]
    assert set(events[5:-1]) == {"worker:2.0", "rewrite", "hud"}
    assert events[-1] == "state:not_running:Winsper has stopped"


def test_app_shutdown_runs_independent_slow_closers_in_parallel(tmp_path):
    import threading
    import time

    from voicepilot.app import WinsperApp

    class SlowComponent:
        def stop(self):
            time.sleep(0.2)

        close = stop

    class Tray:
        def close_owned_windows(self):
            pass

        def stop(self):
            pass

    class Worker:
        def stop(self, timeout):
            del timeout
            time.sleep(0.2)
            return True

    app = WinsperApp.__new__(WinsperApp)
    app.config_path = tmp_path / "config.yaml"
    app._stop_event = threading.Event()
    app._lock = threading.Lock()
    app._shutdown_lock = threading.Lock()
    app._shutdown_started = False
    app._shutdown_complete = threading.Event()
    app.hotkeys = SlowComponent()
    app.tray = Tray()
    app.recorder = SlowComponent()
    app.rewriter = SlowComponent()
    app.hud = SlowComponent()
    app._action_worker = Worker()
    app._context_thread = None
    app._preload_thread = None
    app._rewrite_preload_thread = None
    app._discard_active_recording = lambda: None
    app._close_transcriber = lambda: time.sleep(0.2)
    app._write_runtime_state = lambda *_args: None

    started_at = time.perf_counter()
    app.shutdown()
    elapsed = time.perf_counter() - started_at

    # Hotkeys and microphone close serially first (0.4 s); four independent
    # backend/HUD closers then overlap (~0.2 s instead of ~0.8 s).
    assert elapsed < 0.8


def test_owner_pid_is_forwarded_to_auxiliary_windows():
    from voicepilot.__main__ import build_parser

    args = build_parser().parse_args(["--owner-pid", "1234", "--settings"])
    assert args.owner_pid == 1234
    assert args.settings


def test_appearance_reload_preserves_warm_transcriber():
    from voicepilot.app import WinsperApp
    from voicepilot.config import save_config

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.hud.enabled = False
        config.tray.enabled = False
        save_config(config, config_path)
        app = WinsperApp(config, config_path)
        original = app.transcriber

        changed = load_config(config_path)
        changed.hud.theme = "light"
        save_config(changed, config_path)
        assert app.reload_config()
        assert app.transcriber is original
        app._action_worker.stop()


def test_speech_reload_retires_old_worker_without_blocking():
    from voicepilot.app import WinsperApp
    from voicepilot.config import save_config

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.hud.enabled = False
        config.tray.enabled = False
        config.speech.preload_on_startup = False
        save_config(config, config_path)
        app = WinsperApp(config, config_path)
        original = app.transcriber
        retirement_started = threading.Event()
        allow_retirement = threading.Event()
        retirement_closed = threading.Event()

        def slow_cancel():
            retirement_started.set()
            allow_retirement.wait(timeout=1.0)

        original.cancel = slow_cancel
        original.close = retirement_closed.set
        changed = load_config(config_path)
        changed.speech.model = "base.en"
        changed.dictation.ramble_model = "base.en"
        changed.speech.preload_on_startup = False
        save_config(changed, config_path)

        started_at = time.perf_counter()
        assert app.reload_config(silent=True)
        elapsed = time.perf_counter() - started_at

        assert elapsed < 0.25
        assert app.transcriber is not original
        assert retirement_started.wait(timeout=0.5)
        allow_retirement.set()
        assert retirement_closed.wait(timeout=0.5)
        app._action_worker.stop()


def test_speech_runtime_reload_yields_optional_polish_warmup():
    from unittest.mock import Mock

    from voicepilot.app import WinsperApp
    from voicepilot.config import save_config

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.hud.enabled = False
        config.tray.enabled = False
        config.speech.preload_on_startup = False
        save_config(config, config_path)
        app = WinsperApp(config, config_path)
        app._cancel_rewrite_preload = Mock()
        app._replace_transcriber = Mock()

        changed = load_config(config_path)
        changed.speech.model = "base.en"
        changed.dictation.ramble_model = "base.en"
        save_config(changed, config_path)

        assert app.reload_config(silent=True)

        app._cancel_rewrite_preload.assert_called_once_with(defer=True)
        app._replace_transcriber.assert_called_once_with(changed)
        app._action_worker.stop()


def test_reload_refreshes_corrections_written_by_settings():
    from voicepilot.app import WinsperApp
    from voicepilot.config import save_config

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.hud.enabled = False
        config.tray.enabled = False
        save_config(config, config_path)
        settings_store = CorrectionStore.for_config(config_path)
        settings_store.replace_all([make_rule("alpha", "old")])
        app = WinsperApp(config, config_path)
        assert app.corrections.apply("alpha") == "old"

        settings_store.replace_all([make_rule("alpha", "new")])
        assert app.reload_config(silent=True)
        assert app.corrections.apply("alpha") == "new"
        app._action_worker.stop()


def test_pending_silent_reload_stays_silent():
    from unittest.mock import Mock

    from voicepilot.app import WinsperApp
    from voicepilot.config import save_config

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.hud.enabled = False
        config.tray.enabled = False
        save_config(config, config_path)
        app = WinsperApp(config, config_path)
        app.hud.show = Mock()
        app._coordinator.start_capture("dictate")
        assert app.reload_config(silent=True) is False
        app._coordinator.cancel(app._coordinator.current_action_id())

        app._poll_control_command()

        assert app._reload_pending is False
        app.hud.show.assert_not_called()
        app._action_worker.stop()
