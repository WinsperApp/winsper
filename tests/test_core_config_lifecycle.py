import os
import tempfile

import pytest
from pathlib import Path

from voicepilot.config import AppConfig, load_config, parse_bool, save_config
from voicepilot import autostart, model_storage
from voicepilot.autostart import startup_script_content
from voicepilot.control import consume_control_command, control_command_path, request_control_command
from voicepilot.corrections import CorrectionStore, apply_corrections, make_rule
from voicepilot.models import (
    SPEECH_MODEL_PRESETS,
    cache_dir_name,
    copy_models_between_locations,
    configure_model_storage,
    copy_models_to_storage,
    installed_status,
    huggingface_cache_root,
    model_path_is_complete,
)
from voicepilot.ollama import format_ollama_health, model_available, parse_ollama_models, OllamaHealth
from voicepilot.privacy import format_bytes, privacy_report
from voicepilot.runtime_log import read_recent_runtime_log, runtime_log_path_for_config, write_runtime_log
from voicepilot.runtime_state import read_runtime_state, runtime_state_path, write_runtime_state
from voicepilot.speed_lab import (
    BenchmarkResult,
    SpeedLabStore,
    apply_speed_profile,
    balanced_model,
    result_key,
    score_transcript,
    speed_lab_clip_path_for_config,
)
from voicepilot.usage import record_usage, usage_summary
from voicepilot.voice_commands import parse_voice_command
from voicepilot.storage import atomic_write_text, remove_stale_download_parts
from voicepilot.vocabulary import effective_vocabulary


def test_effective_vocabulary_is_app_independent_and_deduplicated():
    config = AppConfig()
    config.vocabulary = ["Soumya", "json"]

    vocabulary = effective_vocabulary(config)

    assert vocabulary[0] == "Soumya"
    assert vocabulary.count("json") == 1
    assert "API" in vocabulary
    assert "YAML" in vocabulary


def sample_benchmark(
    model: str,
    realtime_factor: float,
    created_at: str = "2026-05-14T00:00:00+00:00",
) -> BenchmarkResult:
    return BenchmarkResult(
        model=model,
        device="cpu",
        compute_type="int8",
        recorded_seconds=5.0,
        transcribed_seconds=5.0,
        load_seconds=0.2,
        transcription_seconds=5.0 * realtime_factor,
        warm_transcription_seconds=4.0 * realtime_factor,
        realtime_factor=realtime_factor,
        transcript_preview="hello",
        expected_text="",
        accuracy_score=None,
        word_error_rate=None,
        created_at=created_at,
    )


def test_quoted_boolean_config_values_are_parsed():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        path.write_text(
            "\n".join(
                (
                    "tray:",
                    '  enabled: "false"',
                    "hotkeys:",
                    '  tap_to_toggle_dictation: "off"',
                    "snippets:",
                    '  enabled: "no"',
                    "profiles:",
                    '  enabled: "0"',
                    "browser_context:",
                    '  enabled: "false"',
                    "spoken_formatting:",
                    '  enabled: "false"',
                )
            ),
            encoding="utf-8",
        )

        config = load_config(path)

    assert config.tray.enabled is False
    assert config.hotkeys.tap_to_toggle_dictation is False
    assert config.snippets.enabled is False
    assert config.profiles.enabled is False
    assert config.browser_context.enabled is False
    assert config.spoken_formatting.enabled is False


def test_parse_bool_preserves_default_for_unknown_values():
    assert parse_bool("true", False) is True
    assert parse_bool("false", True) is False
    assert parse_bool("not-a-boolean", True) is True
    assert parse_bool(None, False) is False


def test_writing_style_config_round_trips_and_normalizes():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.writing_style.preset = "Custom"
        config.writing_style.custom_instruction = "  Keep sentences short.\nUse plain language.  "
        save_config(config, path)

        loaded = load_config(path)

    assert loaded.writing_style.preset == "custom"
    assert loaded.writing_style.custom_instruction == "Keep sentences short. Use plain language."


def test_new_builtin_profile_is_added_without_overwriting_existing_profile_customization():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        path.write_text(
            "\n".join(
                (
                    "profiles:",
                    "  styles:",
                    "    general:",
                    "      label: My General",
                    "      dictation_prompt: Keep my custom behavior.",
                    "      rewrite_prompt: Keep my custom rewrite.",
                )
            ),
            encoding="utf-8",
        )

        loaded = load_config(path)

    assert loaded.profiles.styles["general"].label == "My General"
    assert loaded.profiles.styles["notes"].label == "Notes"
    assert "intentional fragments" in loaded.profiles.styles["notes"].dictation_prompt


def test_model_storage_config_round_trips():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.model_storage.path = str(Path(temp) / "models")
        save_config(config, path)

        loaded = load_config(path)

    assert loaded.model_storage.path.endswith("models")


def test_hud_mode_position_and_recording_chimes_round_trip():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        config = AppConfig()
        config.hud.mode = "compact"
        config.hud.position = "top"
        config.hud.recording_chimes = False
        save_config(config, path)

        loaded = load_config(path)

    assert loaded.hud.mode == "compact"
    assert loaded.hud.position == "top"
    assert loaded.hud.recording_chimes is False


def test_unknown_hud_position_falls_back_to_bottom_center():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        path.write_text("hud:\n  position: floating\n", encoding="utf-8")

        loaded = load_config(path)

    assert loaded.hud.position == "center"


def test_configured_model_storage_controls_speech_cache():
    with tempfile.TemporaryDirectory() as temp:
        try:
            configure_model_storage(Path(temp))
            assert huggingface_cache_root() == Path(temp).resolve() / "speech"
        finally:
            configure_model_storage("")


def test_every_speech_model_download_is_pinned_to_an_exact_revision():
    assert SPEECH_MODEL_PRESETS
    assert all(
        len(preset.revision) == 40
        and preset.revision == preset.revision.lower()
        and all(character in "0123456789abcdef" for character in preset.revision)
        for preset in SPEECH_MODEL_PRESETS
    )


def test_model_storage_copy_moves_only_known_model_folders():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        speech_source = root / "speech-source"
        polish_source = root / "polish-source"
        destination = root / "destination"
        preset = SPEECH_MODEL_PRESETS[0]
        speech_model = speech_source / cache_dir_name(preset.repo_id)
        speech_model.mkdir(parents=True)
        (speech_model / "marker.bin").write_bytes(b"speech")
        unrelated = speech_source / "models--unrelated--repository"
        unrelated.mkdir(parents=True)
        (unrelated / "marker.bin").write_bytes(b"unrelated")
        polish_model = polish_source / "models" / "winsper-polish"
        polish_model.mkdir(parents=True)
        (polish_model / "model.gguf").write_bytes(b"polish")

        copied = copy_models_to_storage(
            destination,
            speech_source=speech_source,
            polish_source=polish_source,
        )

        assert copied == 2
        assert (destination / "speech" / speech_model.name / "marker.bin").read_bytes() == b"speech"
        assert not (destination / "speech" / unrelated.name).exists()
        assert (destination / "polish" / "models" / "winsper-polish" / "model.gguf").read_bytes() == b"polish"
        assert speech_model.exists()


def test_model_storage_copy_supports_split_default_destinations():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        speech_source = root / "custom" / "speech"
        polish_source = root / "custom" / "polish"
        speech_destination = root / "default-speech"
        polish_destination = root / "default-polish"
        preset = SPEECH_MODEL_PRESETS[0]
        speech_model = speech_source / cache_dir_name(preset.repo_id)
        speech_model.mkdir(parents=True)
        (speech_model / "marker.bin").write_bytes(b"speech")
        polish_model = polish_source / "models" / "winsper-polish"
        polish_model.mkdir(parents=True)
        (polish_model / "model.gguf").write_bytes(b"polish")

        copied = copy_models_between_locations(
            speech_source=speech_source,
            speech_destination=speech_destination,
            polish_source=polish_source,
            polish_destination=polish_destination,
        )

        assert copied == 2
        assert (
            speech_destination / speech_model.name / "marker.bin"
        ).read_bytes() == b"speech"
        assert (
            polish_destination / "models" / "winsper-polish" / "model.gguf"
        ).read_bytes() == b"polish"
        assert polish_model.exists()


def test_default_storage_detects_complete_legacy_speech_cache(tmp_path, monkeypatch):
    home = tmp_path / "home"
    app_data = tmp_path / "app-data"
    preset = SPEECH_MODEL_PRESETS[0]
    cached = home / ".cache" / "huggingface" / "hub" / cache_dir_name(preset.repo_id)
    cached.mkdir(parents=True)
    if preset.engine == "sherpa_onnx":
        for name in ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"):
            (cached / name).write_bytes(b"ready")
    else:
        (cached / "model.bin").write_bytes(b"ready")
        (cached / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("voicepilot.model_storage.Path.home", lambda: home)
    monkeypatch.setenv("LOCALAPPDATA", str(app_data))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    configure_model_storage(None)

    status = installed_status(preset, include_size=False)

    assert status.installed
    assert status.cache_path == cached


def test_correction_rule_parses_quoted_false():
    from voicepilot.corrections import rule_from_dict

    rule = rule_from_dict({"heard": "wrong", "replacement": "right", "enabled": "false"})

    assert rule is not None
    assert rule.enabled is False


def test_usage_summary_tracks_words_and_time_saved():
    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        record_usage(config_path, 80)
        record_usage(config_path, 20)
        summary = usage_summary(config_path)
        assert summary.today_words == 100
        assert summary.total_words == 100
        assert summary.today_actions == 2
        assert summary.today_minutes_saved == 2.5


def test_voice_command_shorter_preset():
    command = parse_voice_command("make it shorter")
    assert command.kind == "edit"
    assert command.label == "Shorter"
    assert "shorter" in command.instruction


def test_voice_command_bullet_preset_accepts_natural_target_wrappers():
    for spoken in (
        "turn these into bullet points",
        "turn those into a bullet list",
        "convert these to bullets",
        "convert this into bullet points",
    ):
        command = parse_voice_command(spoken)

        assert command.kind == "edit"
        assert command.label == "Bullets"
        assert "bullet character •" in command.instruction
        assert "destination is Markdown or code" in command.instruction


def test_voice_command_translate_preset():
    command = parse_voice_command("translate this to Hindi")
    assert command.kind == "edit"
    assert command.label == "Translate to Hindi"
    assert "Hindi" in command.instruction


def test_voice_command_replace_last_sentence():
    command = parse_voice_command("replace the last sentence with see you tomorrow")
    assert command.kind == "edit"
    assert command.label == "Replace last sentence"
    assert "see you tomorrow" in command.instruction


def test_voice_command_local_action():
    command = parse_voice_command("undo last paste")
    assert command.kind == "action"
    assert command.action == "undo_last"


def test_selected_text_instruction_never_becomes_a_local_action():
    command = parse_voice_command("undo last paste", local_actions_enabled=False)

    assert command.kind == "raw"
    assert command.instruction == "undo last paste"


def test_correction_replaces_phrase_case_insensitive():
    rule = make_rule("avery morgan", "Avery Morgan")
    assert apply_corrections("hello avery morgan", [rule]) == "hello Avery Morgan"


def test_correction_profile_scope():
    rule = make_rule("terminal", "Windows Terminal", profiles=["code"])
    assert apply_corrections("open terminal", [rule], profile_name="code") == "open Windows Terminal"
    assert apply_corrections("open terminal", [rule], profile_name="email") == "open terminal"


def test_correction_replacement_treats_backslashes_literally():
    rule = make_rule("path", r"C:\1\project")
    assert apply_corrections("open path", [rule]) == r"open C:\1\project"


def test_correction_store_roundtrip_and_trim():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp:
        store = CorrectionStore(Path(temp) / "corrections.json", max_rules=1)
        store.add_rule("one", "1")
        store.add_rule("two", "2")
        rules = store.list()
        assert len(rules) == 1
        assert rules[0].heard == "two"
        assert store.apply("one two") == "one 2"


def test_correction_store_starts_with_removable_winsper_correction():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "corrections.json"
        store = CorrectionStore(path)

        assert [(rule.heard, rule.replacement) for rule in store.list()] == [("win spur", "Winsper")]
        assert store.apply("Open win spur settings") == "Open Winsper settings"

        store.clear()
        assert path.exists()
        assert CorrectionStore(path).list() == []


def test_speed_lab_store_latest_by_model():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp:
        store = SpeedLabStore(Path(temp) / "speed.json")
        store.append(sample_benchmark("base.en", 0.8, "2026-05-14T00:00:00+00:00"))
        store.append(sample_benchmark("base.en", 0.7, "2026-05-14T00:01:00+00:00"))
        latest = store.latest_by_model()
        assert latest[result_key("base.en", "cpu", "int8")].realtime_factor == 0.7


def test_speed_lab_scores_expected_text():
    score = score_transcript("hello Avery from Winsper", "hello avery from winsper")
    assert score is not None
    assert score.word_error_rate < 0.4
    assert score.accuracy_score > 0.6


def test_speed_lab_clip_path():
    from pathlib import Path

    assert speed_lab_clip_path_for_config(Path("C:/tmp/config.yaml")).name == "speed_lab_clip.wav"


def test_speed_lab_balanced_prefers_small_when_fast_enough():
    latest = {
        result_key("base.en", "cpu", "int8"): sample_benchmark("base.en", 0.5),
        result_key("small.en", "cpu", "int8"): sample_benchmark("small.en", 1.0),
    }
    assert balanced_model(latest) == "small.en"


def test_speed_lab_balanced_defaults_to_small_without_results():
    assert balanced_model({}) == "small.en"


def test_apply_fast_profile_sets_mode_models():
    config = AppConfig()
    latest = {
        result_key("base.en", "cpu", "int8"): sample_benchmark("base.en", 0.4),
        result_key("small.en", "cpu", "int8"): sample_benchmark("small.en", 1.1),
    }
    apply_speed_profile(config, "fast", latest)
    assert config.dictation.ramble_model == "base.en"
    assert config.dictation.polish_model == "base.en"
    assert config.dictation.rewrite_instruction_model == "base.en"
    assert config.speech.preload_on_startup is True


def test_apply_instant_profile_alias_sets_mode_models():
    config = AppConfig()
    apply_speed_profile(config, "instant", {})
    assert config.dictation.ramble_model == "base.en"
    assert config.speech.engine == "faster_whisper"


def test_cpu_speed_profiles_do_not_probe_gpu(monkeypatch):
    def unexpected_probe():
        raise AssertionError("CPU profiles must not perform a synchronous GPU probe")

    monkeypatch.setattr("voicepilot.speed_lab.detect_hardware", unexpected_probe)
    monkeypatch.setattr("voicepilot.speed_lab.nvidia_acceleration_ready", unexpected_probe)

    apply_speed_profile(AppConfig(), "instant", {})
    apply_speed_profile(AppConfig(), "balanced", {})


def test_gpu_profile_requires_verified_eligible_nvidia_runtime(monkeypatch):
    from voicepilot.models import HardwareSummary

    hardware = HardwareSummary("CPU", 16, ("NVIDIA Test",), True, False)
    monkeypatch.setattr("voicepilot.speed_lab.detect_hardware", lambda: hardware)
    monkeypatch.setattr("voicepilot.speed_lab.nvidia_acceleration_ready", lambda: False)
    config = AppConfig()

    apply_speed_profile(config, "gpu_boost", {})

    assert config.speech.device == "cpu"
    assert config.speech.compute_type == "int8"
    assert config.speech.model == "small.en"

    monkeypatch.setattr("voicepilot.speed_lab.nvidia_acceleration_ready", lambda: True)
    apply_speed_profile(config, "gpu_boost", {})

    assert config.speech.device == "cuda"
    assert config.speech.compute_type == "float16"
    assert config.speech.model == "large-v3-turbo"


def test_unsupported_fast_profile_falls_back_to_balanced_multilingual_model():
    config = AppConfig()
    config.speech.language = "hi"

    message = apply_speed_profile(config, "instant", {})

    assert config.speech.model == "small"
    assert config.dictation.ramble_model == "small"
    assert config.dictation.polish_model == "small"
    assert config.dictation.rewrite_instruction_model == "small"
    assert "Fast is unavailable for this language, so Balanced was applied." in message


def test_privacy_format_bytes():
    assert format_bytes(0) == "0 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1024 * 1024) == "1.0 MB"


def test_privacy_report_mentions_local_processing():
    from pathlib import Path

    report = privacy_report(AppConfig(), Path("C:/tmp/config.yaml"))
    assert "Audio is captured only for the current hotkey action" in report
    assert "does not write normal dictation audio to a temporary WAV file" in report
    assert "Speech-to-text uses local faster-whisper models" in report
    assert "temporarily uses the Windows clipboard" in report
    assert "license key, Dodo product ID" not in report
    assert "Diagnostics do not intentionally include dictated or selected text" in report
    assert "no automatic crash-report upload" in report


def test_runtime_log_roundtrip():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        write_runtime_log(config_path, "test error", "Something happened", RuntimeError("boom"))
        assert runtime_log_path_for_config(config_path).name == "voicepilot.log"
        recent = read_recent_runtime_log(config_path)
        assert "test error" in recent
        assert "Something happened" in recent
        assert "RuntimeError: boom" in recent


def test_runtime_log_redacts_credentials_from_messages_and_tracebacks(tmp_path):
    config_path = tmp_path / "config.yaml"
    write_runtime_log(
        config_path,
        "provider error",
        "license_key=WINSPER-SECRET Authorization: Bearer token-value",
        RuntimeError("api_key: private-value&token=query-value"),
    )
    recent = read_recent_runtime_log(config_path)
    assert "WINSPER-SECRET" not in recent
    assert "token-value" not in recent
    assert "private-value" not in recent
    assert "query-value" not in recent
    assert recent.count("[redacted]") >= 4


def test_control_command_roundtrip():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        request_control_command(config_path, "stop")
        assert control_command_path(config_path).exists()
        assert consume_control_command(config_path) == "stop"
        assert consume_control_command(config_path) is None
        request_control_command(config_path, "reload")
        assert consume_control_command(config_path) == "reload"
        request_control_command(config_path, "pause")
        assert consume_control_command(config_path) == "pause"
        request_control_command(config_path, "resume")
        assert consume_control_command(config_path) == "resume"


def test_runtime_state_roundtrip():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        write_runtime_state(config_path, "paused", "Listening paused", paused=True)
        assert runtime_state_path(config_path).exists()
        state = read_runtime_state(config_path)
        assert state is not None
        assert state.status == "paused"
        assert state.paused is True
        assert state.detail == "Listening paused"


def test_runtime_state_rejects_stale_active_process(monkeypatch):
    from voicepilot import runtime_state

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        write_runtime_state(config_path, "listening", "Hotkeys active")
        monkeypatch.setattr(runtime_state, "process_is_alive", lambda _pid: False)
        assert read_runtime_state(config_path) is None


def test_runtime_state_rejects_reused_process_id(monkeypatch):
    from voicepilot import runtime_state

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        monkeypatch.setattr(runtime_state, "process_creation_marker", lambda _pid: 101)
        write_runtime_state(config_path, "listening", "Hotkeys active")
        monkeypatch.setattr(runtime_state, "process_is_alive", lambda _pid: True)
        monkeypatch.setattr(runtime_state, "process_creation_marker", lambda _pid: 202)
        assert read_runtime_state(config_path) is None


def test_runtime_state_keeps_explicit_not_running_state(monkeypatch):
    from voicepilot import runtime_state

    with tempfile.TemporaryDirectory() as temp:
        config_path = Path(temp) / "config.yaml"
        write_runtime_state(config_path, "not_running", "Winsper has stopped")
        monkeypatch.setattr(runtime_state, "process_is_alive", lambda _pid: False)
        state = read_runtime_state(config_path)

        assert state is not None
        assert state.status == "not_running"


def test_atomic_write_replaces_complete_file():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "state.txt"
        atomic_write_text(path, "first")
        atomic_write_text(path, "second")
        assert path.read_text(encoding="utf-8") == "second"
        assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_stale_download_cleanup_preserves_recent_resume_data(tmp_path):
    stale_part = tmp_path / "polish.gguf.part"
    stale_incomplete = tmp_path / "blobs" / "speech.incomplete"
    recent_part = tmp_path / "runtime.zip.part"
    unrelated = tmp_path / "notes.txt"
    stale_incomplete.parent.mkdir()
    for path in (stale_part, stale_incomplete, recent_part, unrelated):
        path.write_bytes(b"partial")
    now = 10_000_000.0
    stale_time = now - (8 * 24 * 60 * 60)
    recent_time = now - (2 * 24 * 60 * 60)
    os.utime(stale_part, (stale_time, stale_time))
    os.utime(stale_incomplete, (stale_time, stale_time))
    os.utime(recent_part, (recent_time, recent_time))
    os.utime(unrelated, (stale_time, stale_time))

    removed = remove_stale_download_parts(tmp_path, now=now)

    assert removed == 2
    assert not stale_part.exists()
    assert not stale_incomplete.exists()
    assert recent_part.exists()
    assert unrelated.exists()


def test_cancelled_speech_download_discards_incomplete_repo_data(tmp_path, monkeypatch):
    preset = model_storage.find_speech_model("base.en")
    assert preset is not None
    repo_cache = tmp_path / model_storage.cache_dir_name(preset.repo_id)
    partial = repo_cache / "blobs" / "model.incomplete"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"partial")
    completed_blob = repo_cache / "blobs" / "completed-model-file"
    completed_blob.write_bytes(b"complete file from unfinished model")
    monkeypatch.setattr(model_storage, "huggingface_cache_root", lambda: tmp_path)

    def cancelled(*_args, **_kwargs):
        raise model_storage.ModelDownloadCancelled("Model download cancelled.")

    monkeypatch.setattr(model_storage, "_download_model", cancelled)

    with pytest.raises(model_storage.ModelDownloadCancelled):
        model_storage.download_model("base.en")

    assert not repo_cache.exists()


def test_model_path_completeness():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        assert not model_path_is_complete(root, "faster_whisper")
        (root / "model.bin").write_bytes(b"x")
        (root / "config.json").write_text("{}", encoding="utf-8")
        assert model_path_is_complete(root, "faster_whisper")


def test_startup_script_mentions_config_and_skip_setup():
    from pathlib import Path

    text = startup_script_content(Path("C:/tmp/config.yaml"))
    assert "--skip-setup" in text
    assert "config.yaml" in text
    assert "voicepilot" in text


def test_start_with_windows_creates_and_removes_startup_launcher(tmp_path, monkeypatch):
    launcher = tmp_path / "Startup" / "Winsper.vbs"
    monkeypatch.setattr(autostart, "startup_script_path", lambda: launcher)
    monkeypatch.setattr(autostart, "app_working_directory", lambda: Path("C:/Winsper"))
    monkeypatch.setattr(
        autostart,
        "app_command",
        lambda arguments, *, windowed: ["C:/Winsper/Winsper.exe", *arguments],
    )

    autostart.set_start_with_windows(tmp_path / "config.yaml", True)

    assert autostart.is_start_with_windows_enabled()
    launcher_text = launcher.read_text(encoding="utf-8")
    assert "Winsper.exe" in launcher_text
    assert "--skip-setup" in launcher_text
    assert str(tmp_path / "config.yaml") in launcher_text

    autostart.set_start_with_windows(tmp_path / "config.yaml", False)

    assert not launcher.exists()


def test_ollama_model_parsing_and_matching():
    body = '{"models":[{"name":"qwen2.5:1.5b"},{"model":"llama3.2:3b"}]}'
    models = parse_ollama_models(body)
    assert models == ["qwen2.5:1.5b", "llama3.2:3b"]
    assert model_available("qwen2.5:1.5b", models)
    assert model_available("llama3.2", models)
    assert not model_available("mistral", models)


def test_ollama_health_format_mentions_missing_model():
    health = OllamaHealth(
        reachable=True,
        model_available=False,
        model="qwen2.5:1.5b",
        models=("llama3.2:3b",),
        tags_url="http://127.0.0.1:11434/api/tags",
        latency_ms=12,
    )
    assert "qwen2.5:1.5b missing" in format_ollama_health(health)
