
from voicepilot.config import AppConfig
from voicepilot.corrections import CorrectionStore
from voicepilot.rewrite import (
    apply_cpp_file_aliases,
    apply_spoken_formatting,
    clean_model_output,
    missing_protected_identifiers,
    prepare_polish_input,
    preserves_numeric_facts,
    TextRewriter,
)
from voicepilot.speed_lab import BenchmarkResult
from voicepilot.transcribe import FasterWhisperTranscriber
from voicepilot.updates import parse_update_manifest, version_key

def sample_benchmark(model: str, realtime_factor: float, created_at: str = "2026-05-14T00:00:00+00:00") -> BenchmarkResult:
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


def test_corrections_store_caches_until_explicit_reload(tmp_path):
    from voicepilot.corrections import CorrectionRule
    import json

    path = tmp_path / "corrections.json"
    store = CorrectionStore(path)

    rules = [
        CorrectionRule("1", "hello", "hi", []),
        CorrectionRule("2", "world", "earth", []),
    ]
    store.replace_all(rules)

    loaded = store.list()
    assert len(loaded) == 2
    assert store._cached_rules is not loaded

    path.write_text(json.dumps({"rules": []}), encoding="utf-8")
    assert len(store.list()) == 2
    store.reload()
    assert store.list() == []

    store.add_rule("test", "passed")
    assert len(store.list()) == 1

    pat1 = store._get_compiled_pattern("test")
    pat2 = store._get_compiled_pattern("test")
    assert pat1 is pat2


def test_model_request_and_runtime_keys_have_distinct_responsibilities():
    from voicepilot.config import SpeechConfig
    from voicepilot.transcribe import model_key, model_runtime_key

    c1 = SpeechConfig(model="small.en", device="cpu", compute_type="int8", language="en", beam_size=5)
    c2 = SpeechConfig(model="small.en", device="cpu", compute_type="int8", language="es", beam_size=1)

    assert model_key(c1) != model_key(c2)
    assert model_runtime_key(c1) == model_runtime_key(c2)


def test_model_cache_is_bounded_lru(monkeypatch):
    import sys
    from types import SimpleNamespace

    from voicepilot.config import SpeechConfig
    from voicepilot.transcribe import model_runtime_key

    class FakeWhisperModel:
        def __init__(self, model_ref, device, compute_type):
            self.model_ref = model_ref
            self.device = device
            self.compute_type = compute_type

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    base = SpeechConfig(model="model-a", max_cached_models=2)
    transcriber = FasterWhisperTranscriber(base, [])
    config_a = base
    config_b = SpeechConfig(model="model-b", max_cached_models=2)
    config_c = SpeechConfig(model="model-c", max_cached_models=2)

    model_a = transcriber.load_model(config_a)
    transcriber.load_model(config_b)
    assert transcriber.load_model(config_a) is model_a
    transcriber.load_model(config_c)

    assert list(transcriber._models) == [model_runtime_key(config_a), model_runtime_key(config_c)]


def test_model_runtime_is_reused_across_language_and_beam_changes(monkeypatch):
    import sys
    from types import SimpleNamespace

    from voicepilot.config import SpeechConfig

    created = []

    class FakeWhisperModel:
        def __init__(self, model_ref, device, compute_type):
            created.append((model_ref, device, compute_type))

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    base = SpeechConfig(model="local-model", language="en", beam_size=1)
    transcriber = FasterWhisperTranscriber(base, [])

    first = transcriber.load_model(base)
    second = transcriber.load_model(SpeechConfig(model="local-model", language="fr", beam_size=5))

    assert second is first
    assert created == [("local-model", "cpu", "int8")]


def test_clean_model_output_removes_only_known_wrappers():
    assert clean_model_output("```text\nHello\n```") == "Hello"
    assert clean_model_output("Rewritten text: Hello") == "Hello"
    assert clean_model_output("A literal label: Hello") == "A literal label: Hello"
    multiple_blocks = "```python\nprint('one')\n```\n\n```python\nprint('two')\n```"
    assert clean_model_output(multiple_blocks) == multiple_blocks
    assert clean_model_output("Explanation\n```text\nHello\n```") == "Explanation\n```text\nHello\n```"


def test_resample_preserves_speech_band_and_rejects_aliases():
    import numpy as np

    from voicepilot.transcribe import _resample

    source_rate = 48_000
    target_rate = 16_000
    sample_count = source_rate // 4
    timeline = np.arange(sample_count, dtype="float32") / source_rate
    speech_band = np.sin(2 * np.pi * 1_000 * timeline).astype("float32")
    above_nyquist = np.sin(2 * np.pi * 12_000 * timeline).astype("float32")

    speech_result = _resample(speech_band, source_rate, target_rate)
    rejected_result = _resample(above_nyquist, source_rate, target_rate)

    assert len(speech_result) == target_rate // 4
    assert np.sqrt(np.mean(speech_result[100:-100] ** 2)) > 0.6
    assert np.sqrt(np.mean(rejected_result[100:-100] ** 2)) < 0.02


def test_rewrite_facade_exports_only_intended_names():
    import voicepilot.rewrite as rewrite

    assert hasattr(rewrite, "TextRewriter")
    assert hasattr(rewrite, "build_polish_prompt")
    assert not hasattr(rewrite, "re")
    assert not hasattr(rewrite, "ProfileStyle")


def test_degenerate_model_output_detection():
    from voicepilot.rewrite import looks_like_degenerate_output

    assert looks_like_degenerate_output("?" * 100)
    assert looks_like_degenerate_output("error " * 100)
    assert not looks_like_degenerate_output("Please ask Akshay to review this.")


def test_polish_safety_helpers_preserve_commands_formatting_and_numbers():
    assert prepare_polish_input("git commit dash m fixed it", "Command Prompt") == "git commit -m fixed it"
    assert apply_spoken_formatting("- Fix bugs", "make sure bugs is bolded") == "- Fix **bugs**"
    assert preserves_numeric_facts("meet in 5 minutes", "Meet in five minutes.")
    assert not preserves_numeric_facts("meet in 5 minutes", "Meet immediately.")
    assert preserves_numeric_facts(
        "The estimate is 15 lakhs, sorry 18 lakhs.",
        "The estimate is 18 lakhs.",
    )
    assert not preserves_numeric_facts(
        "Revenue increased from 12 lakhs to 18 lakhs.",
        "Revenue increased to 18 lakhs.",
    )
    assert not preserves_numeric_facts(
        "12 users actually need 18 seats.",
        "Users need 18 seats.",
    )
    assert preserves_numeric_facts(
        "The estimate was 15 lakhs, actually 18 lakhs.",
        "The estimate was 18 lakhs.",
    )
    assert apply_cpp_file_aliases("old Whisper C++ module", ["Whisper.cpp"]) == "old Whisper.cpp module"


def test_rewrite_identifier_guard_allows_requested_changes_only():
    source = "result = requests.get(url)\nprint(result.json())"
    changed = source.replace("result", "response")
    assert missing_protected_identifiers(source, "wrap in try except", changed, "VS Code") == ["result"]
    assert missing_protected_identifiers("import os", "remove unused import os", "", "VS Code") == []
    assert (
        missing_protected_identifiers(
            "Revenue rose from 12 lakhs to 18 lakhs in Q2.",
            "Answer this question using the selected text.",
            "Revenue increased.",
            "Email",
        )
        == []
    )


def test_update_manifest_requires_https_and_sha256():
    import json
    import pytest

    payload = json.dumps(
        {
            "version": "0.3.0",
            "installer_url": "https://downloads.winsper.app/WinsperSetup-0.3.0.exe",
            "sha256": "a" * 64,
            "notes": "Faster startup.",
        }
    ).encode()
    info = parse_update_manifest(payload)
    assert info.version == "0.3.0"
    assert version_key("0.3.0") > version_key("0.2.9")
    with pytest.raises(ValueError, match="HTTPS"):
        parse_update_manifest(payload.replace(b"https://", b"http://"))
    with pytest.raises(ValueError, match="official Winsper"):
        parse_update_manifest(payload.replace(b"downloads.winsper.app", b"downloads.example.com"))


def test_update_authenticode_requires_trusted_matching_publisher(tmp_path):
    import json
    from types import SimpleNamespace
    from unittest.mock import patch

    import pytest

    from voicepilot.updates import verify_authenticode_signature

    installer = tmp_path / "WinsperSetup.exe"
    installer.write_bytes(b"signed")
    valid = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"Status": "Valid", "Subject": "CN=Winsper Technologies Private Limited"}),
        stderr="",
    )
    with patch("voicepilot.updates.os.name", "nt"), patch("voicepilot.updates.subprocess.run", return_value=valid):
        assert "Winsper Technologies" in verify_authenticode_signature(installer, "Winsper Technologies")
        with pytest.raises(ValueError, match="publisher"):
            verify_authenticode_signature(installer, "Different Publisher")


def test_text_rewriter_uses_injected_completion_backend():

    calls = []

    class Backend:
        def complete(self, prompt, *, num_predict):
            calls.append((prompt, num_predict))
            return "  Clean result.  "

    rewriter = TextRewriter(AppConfig().rewrite, [], backend=Backend())

    assert rewriter._complete("test prompt", 123) == "Clean result."
    assert calls == [("test prompt", 123)]


def test_text_rewriter_closes_backend():

    class Backend:
        closed = False

        def complete(self, _prompt, *, num_predict):
            return str(num_predict)

        def close(self):
            self.closed = True

    backend = Backend()
    rewriter = TextRewriter(AppConfig().rewrite, [], backend=backend)
    rewriter.close()

    assert backend.closed
    assert rewriter.backend is None
