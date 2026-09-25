import tempfile
from pathlib import Path

from voicepilot.brand import BRAND_NAME, window_title
from voicepilot.config import AppConfig, BrowserSiteStyle, ProfileStyle, config_to_dict, load_config
from voicepilot.app_context import (
    AppContextDetector,
    ForegroundContext,
    browser_label_for_domain,
    domain_from_title,
    domain_from_url,
    domain_matches,
    friendly_process_label,
    is_browser_process,
    is_winsper_window,
)
from voicepilot.__main__ import format_app_awareness_report
from voicepilot.config import Snippet
from voicepilot.corrections import corrections_path_for_config
from voicepilot.history import (
    HistoryEvent,
    HistoryStore,
    history_path_for_config,
)
from voicepilot.models import (
    HardwareSummary,
    cache_dir_name,
    engine_for_model,
    find_speech_model,
    quick_setup_model_for,
    recommended_model_for_hardware,
    recommended_model_for_language,
    recommended_model_policy,
    speech_language_options,
    speech_models_for_language,
)
from voicepilot.writing_style import apply_writing_style
from voicepilot.rewrite import (
    build_polish_prompt,
    looks_like_polish_instruction_echo,
)
from voicepilot.snippets import match_snippet, normalize_trigger
from voicepilot.speed_lab import (
    speed_lab_path_for_config,
)
from voicepilot.transcribe import FasterWhisperTranscriber, normalize_transcript


def test_polish_routes_empty_selection_to_auto_polish_and_selection_to_rewrite():
    from unittest.mock import Mock

    from voicepilot.app_pipeline import DictationPipelineMixin
    from voicepilot.selection import SelectionResult

    class Harness(DictationPipelineMixin):
        @staticmethod
        def _action_cancelled(_action_id):
            return False

        @staticmethod
        def _target_is_current(_context):
            return True

        def _selection_for_polish_action(self, _action_id):
            return self.inserter.read_selection()

        def _process_dictation(self, _clip, _context, *, polish, action_id):
            self.route = ("auto_polish", polish, action_id)

        def _process_rewrite(self, _clip, _context, *, selection, action_id):
            self.route = ("selection_rewrite", selection, action_id)

    context = ForegroundContext("notepad.exe", "Notes", "general", ProfileStyle(label="General"), window_hwnd=100)
    harness = Harness()
    harness.hud = Mock()
    harness.inserter = Mock()
    harness.inserter.read_selection.return_value = SelectionResult.no_selection()
    harness._process_polish(None, context, action_id=7)
    assert harness.route == ("auto_polish", True, 7)

    harness.inserter.read_selection.return_value = SelectionResult.captured("Original selected text")
    harness._process_polish(None, context, action_id=8)
    assert harness.route == ("selection_rewrite", "Original selected text", 8)


def test_polish_uses_selection_snapshot_without_rereading_after_asr():
    from unittest.mock import Mock

    from voicepilot.app_pipeline import DictationPipelineMixin
    from voicepilot.selection import SelectionResult

    class Harness(DictationPipelineMixin):
        @staticmethod
        def _action_cancelled(_action_id):
            return False

        @staticmethod
        def _target_is_current(_context):
            return True

        @staticmethod
        def _selection_for_polish_action(_action_id):
            return SelectionResult.captured("basic")

        def _process_rewrite(self, _clip, _context, *, selection, action_id):
            self.route = (selection, action_id)

    context = ForegroundContext("notepad.exe", "Notes", "general", ProfileStyle(label="General"), window_hwnd=100)
    harness = Harness()
    harness.hud = Mock()
    harness.inserter = Mock()
    harness.inserter.read_selection.side_effect = AssertionError("must not copy selection after ASR")

    harness._process_polish(None, context, action_id=42)

    assert harness.route == ("basic", 42)


def test_polish_does_not_fallback_when_selection_cannot_be_read():
    from unittest.mock import Mock

    from voicepilot.app_pipeline import DictationPipelineMixin
    from voicepilot.selection import SelectionResult

    class Harness(DictationPipelineMixin):
        @staticmethod
        def _action_cancelled(_action_id):
            return False

        @staticmethod
        def _target_is_current(_context):
            return True

        def _process_dictation(self, *_args, **_kwargs):
            raise AssertionError("selection failure must not become no-selection Polish")

    context = ForegroundContext("notepad.exe", "Notes", "general", ProfileStyle(label="General"), window_hwnd=100)
    harness = Harness()
    harness.hud = Mock()
    harness.inserter = Mock()
    harness.inserter.read_selection.return_value = SelectionResult.unavailable("clipboard unavailable")

    harness._process_polish(None, context)

    assert harness.hud.show.call_args.args == (
        "Selection unavailable",
        "Select text again, then hold Polish",
        "warning",
    )


def test_polish_reports_target_change_without_treating_it_as_no_selection():
    from unittest.mock import Mock

    from voicepilot.app_pipeline import DictationPipelineMixin
    from voicepilot.selection import SelectionResult

    class Harness(DictationPipelineMixin):
        @staticmethod
        def _action_cancelled(_action_id):
            return False

        @staticmethod
        def _target_is_current(_context):
            return True

        def _selection_for_polish_action(self, _action_id):
            return SelectionResult.target_changed()

        def _process_dictation(self, *_args, **_kwargs):
            raise AssertionError("target change must not fall through to auto-polish")

        def _process_rewrite(self, *_args, **_kwargs):
            raise AssertionError("target change must not rewrite a stale selection")

    harness = Harness()
    harness.hud = Mock()
    harness.inserter = Mock()
    context = ForegroundContext("notepad.exe", "Notes", "general", ProfileStyle(label="General"), window_hwnd=100)

    harness._process_polish(None, context, action_id=9)

    assert harness.hud.show_action_message.call_args.args == (
        9,
        "Target changed",
        "Return to selected text and hold Polish again",
        "warning",
    )


def test_polish_elevated_target_falls_back_to_speech_polish_without_requesting_app_elevation():
    from unittest.mock import Mock

    from voicepilot.app_pipeline import DictationPipelineMixin
    from voicepilot.selection import SelectionResult

    class Harness(DictationPipelineMixin):
        @staticmethod
        def _action_cancelled(_action_id):
            return False

        @staticmethod
        def _target_is_current(_context):
            return True

        @staticmethod
        def _selection_for_polish_action(_action_id):
            return SelectionResult.target_elevated()

        def _process_dictation(self, clip, context, polish=False, action_id=0):
            self.speech_polish = (clip, context, polish, action_id)

    harness = Harness()
    harness.hud = Mock()
    harness.inserter = Mock()
    context = ForegroundContext("admin.exe", "Administrator", "general", ProfileStyle(label="General"), window_hwnd=100)

    harness._process_polish(None, context, action_id=10)

    assert harness.speech_polish == (None, context, True, 10)
    assert "run winsper as administrator" not in str(harness.hud.mock_calls).lower()


def test_transcript_vocabulary_normalization():
    assert normalize_transcript("hello avery from codex", ["Avery", "Codex"]) == "hello Avery from Codex"


def test_transcript_vocabulary_conservatively_repairs_name_variants():
    assert normalize_transcript("Regards, Samya.", ["Soumya", "JSON"]) == "Regards, Soumya."
    assert normalize_transcript("Ask Samyya to review this.", ["Soumya"]) == "Ask Soumya to review this."
    assert normalize_transcript("Someone should review this.", ["Soumya"]) == "Someone should review this."
    assert normalize_transcript("Regards, Sommenh.", ["Soumya"]) == "Regards, Sommenh."
    assert normalize_transcript("Katubisanahali office", ["Kadubeesanahalli"]) == "Kadubeesanahalli office"
    assert normalize_transcript(
        "Kadu Bisanahali, Marathah Hali, and Whitefield.",
        ["Kadubeesanahalli", "Marathahalli", "Whitefield"],
    ) == "Kadubeesanahalli, Marathahalli, and Whitefield."


def test_mode_config_switches_engine_for_known_model():
    config = AppConfig().speech
    transcriber = FasterWhisperTranscriber(config, [])
    parakeet = transcriber.mode_config("parakeet-tdt-0.6b-v2-int8")
    assert parakeet.engine == "sherpa_onnx"
    whisper = transcriber.mode_config("small.en")
    assert whisper.engine == "faster_whisper"


def test_mode_config_respects_explicit_gpu_class_model_choice():
    config = AppConfig().speech
    config.device = "cpu"
    config.compute_type = "int8"
    transcriber = FasterWhisperTranscriber(config, [])
    explicit = transcriber.mode_config("large-v3")
    assert explicit.model == "large-v3"
    assert explicit.device == "cpu"
    assert explicit.compute_type == "int8"
    assert explicit.engine == "faster_whisper"


def test_config_serializes():
    data = config_to_dict(AppConfig())
    assert data["speech"]["model"] == "small.en"
    assert data["speech"]["preload_on_startup"] is True
    assert data["hotkeys"]["dictate"] == "ctrl+space"
    assert data["hotkeys"]["polish"] == "ctrl+alt+p"
    assert data["hotkeys"]["cancel"] == "ctrl+win+esc"
    assert data["dictation"]["polish_enabled"] is True
    assert data["dictation"]["ramble_model"] == "small.en"
    assert data["dictation"]["polish_fallback_to_ramble"] is True
    assert data["hud"]["theme"] == "system"
    assert data["hud"]["recording_chimes"] is False
    assert data["startup"]["start_with_windows"] is False
    assert data["onboarding"]["completed"] is False
    assert data["history"]["enabled"] is True
    assert data["history"]["max_items"] == 200
    assert data["correction_memory"]["enabled"] is True
    assert data["correction_memory"]["max_rules"] == 500
    assert data["voice_commands"]["enabled"] is True
    assert data["voice_commands"]["edit_presets_enabled"] is True
    assert data["voice_commands"]["local_actions_enabled"] is True
    assert data["spoken_actions"]["enabled"] is True
    assert data["spoken_actions"]["enter_phrase"] == "press enter"
    assert data["spoken_formatting"]["enabled"] is True
    assert data["rewrite"]["preview_before_apply"] is False
    assert data["browser_context"]["enabled"] is True
    assert data["browser_context"]["timeout_ms"] == 450
    assert "chrome.exe" in data["browser_context"]["browser_processes"]
    assert "firefox.exe" in data["browser_context"]["browser_processes"]
    assert "arc.exe" in data["browser_context"]["browser_processes"]
    assert "duckduckgo.exe" in data["browser_context"]["browser_processes"]
    assert data["browser_context"]["site_styles"]


def test_brand_is_winsper():
    assert BRAND_NAME == "Winsper"
    assert window_title("Settings") == "Winsper Settings"


def test_language_catalog_filters_and_recommends_compatible_models():
    cpu = HardwareSummary("CPU", 16, (), False, False)

    assert len(speech_language_options()) >= 111
    assert speech_language_options()[0] == ("", "Auto / Mixed languages")
    assert recommended_model_for_language("en", cpu).model == "small.en"
    assert recommended_model_for_language("fr", cpu).model == "small"
    assert recommended_model_for_language("hi", cpu).model == "small"
    assert "parakeet-tdt-0.6b-v2-int8" not in {preset.model for preset in speech_models_for_language("fr")}
    assert "parakeet-tdt-0.6b-v3-int8" not in {preset.model for preset in speech_models_for_language("hi")}
    assert "small" in {preset.model for preset in speech_models_for_language("hi")}
    assert recommended_model_for_language("mix-hi-en", cpu).model == "small"
    mixed_models = {preset.model for preset in speech_models_for_language("mix-hi-en")}
    assert "small" in mixed_models
    assert "parakeet-tdt-0.6b-v3-int8" not in mixed_models
    policy = recommended_model_policy("en", cpu)
    assert policy.dictation.model == "small.en"
    assert policy.polish.model == "small.en"
    assert policy.instruction.model == "small.en"
    assert policy.speed_option.model == "parakeet-tdt-0.6b-v2-int8"
    assert recommended_model_policy("fr", cpu).speed_option.model == "parakeet-tdt-0.6b-v3-int8"
    assert recommended_model_policy("hi", cpu).speed_option.model == "small"
    assert recommended_model_policy("mix-fr-en", cpu).speed_option.model == "small"


def test_mixed_hinglish_uses_hindi_decoder_and_preserves_scripts():
    from types import SimpleNamespace

    import numpy as np

    from voicepilot.audio import AudioClip
    from voicepilot.transcribe import FasterWhisperTranscriber

    class Model:
        def __init__(self):
            self.kwargs = None

        def transcribe(self, _audio, **kwargs):
            self.kwargs = kwargs
            return iter([SimpleNamespace(text=" नमस्ते team ")]), None

    config = AppConfig().speech
    config.language = "mix-hi-en"
    model = Model()
    transcriber = FasterWhisperTranscriber(config, [])
    transcriber.load_model = lambda *_args, **_kwargs: model
    clip = AudioClip(np.zeros(16_000, dtype="float32"), 16_000, 1.0)

    assert transcriber.transcribe(clip) == "नमस्ते team"
    assert model.kwargs["language"] == "hi"
    assert model.kwargs["beam_size"] == 3
    assert "अनुवाद बिल्कुल न करें" in model.kwargs["initial_prompt"]
    assert "देवनागरी" in model.kwargs["initial_prompt"]


def test_config_ignores_removed_legacy_fields():
    import yaml

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "hotkeys": {"dictate": "ctrl+space", "rewrite": "ctrl+r"},
                    "dictation": {"polish_prompt": "Legacy custom prompt."},
                    "rewrite": {"model": "qwen3:8b", "no_selection_strategy": "undo_then_paste"},
                }
            ),
            encoding="utf-8",
        )
        config = load_config(path)
        assert config.hotkeys.dictate == "ctrl+space"
        assert not hasattr(config.hotkeys, "rewrite")
        assert not hasattr(config.dictation, "polish_prompt")
        assert config.rewrite.model == "qwen3:8b"
        assert not hasattr(config.rewrite, "no_selection_strategy")


def test_browser_domain_helpers():
    assert domain_from_url("https://mail.google.com/mail/u/0/#inbox") == "mail.google.com"
    assert domain_matches("docs.google.com", "google.com")
    assert domain_matches("averyjena.atlassian.net", "atlassian.net")
    assert browser_label_for_domain("chatgpt.com") == "ChatGPT"
    assert browser_label_for_domain("youtube.com") == "YouTube"
    assert domain_from_title("YouTube - Microsoft Edge") == "youtube.com"
    assert is_browser_process("DuckDuckGo.exe", AppConfig().browser_context.browser_processes)
    assert is_browser_process("custom-browser.exe", ["custom-browser.exe"])


def test_browser_domain_profile_routing():
    detector = AppContextDetector(AppConfig())
    assert detector._match_profile("chrome.exe", "Inbox", "mail.google.com") == "email"
    assert detector._match_profile("msedge.exe", "ChatGPT", "chatgpt.com") == "prompt"
    assert detector._match_profile("python.exe", "Winsper Settings") == "general"


def test_browser_cache_refreshes_when_tab_title_changes():
    import voicepilot.app_context as app_context
    from voicepilot.app_context import BrowserPageContext, WindowInfo

    original_window = app_context.get_foreground_window_details
    original_browser = app_context.detect_browser_page
    titles = iter(["First tab", "Second tab"])
    domains = iter(["first.example", "second.example"])
    try:
        app_context.get_foreground_window_details = lambda: WindowInfo(42, "firefox.exe", next(titles))
        app_context.detect_browser_page = lambda _window, _config: BrowserPageContext(next(domains), "")
        detector = AppContextDetector(AppConfig())
        assert detector.detect().browser_domain == "first.example"
        assert detector.detect().browser_domain == "second.example"
    finally:
        app_context.get_foreground_window_details = original_window
        app_context.detect_browser_page = original_browser


def test_browser_context_hud_label_and_report():
    context = ForegroundContext(
        process_name="chrome.exe",
        window_title="Inbox - Gmail",
        profile_name="email",
        profile=ProfileStyle(label="Polished email"),
        browser_domain="mail.google.com",
        browser_label="Gmail",
        site_style=BrowserSiteStyle(
            domains=["mail.google.com"],
            label="Email draft",
            dictation_prompt="Email-specific polish.",
            rewrite_prompt="Email-specific rewrite.",
        ),
    )
    assert context.hud_context_label == "Gmail"
    assert "Email-specific polish." in context.writing_profile.dictation_prompt
    report = format_app_awareness_report(context, AppConfig())
    assert "Detected site: Gmail" in report
    assert "Site behavior: Email draft" in report
    assert "Matched by: browser domain" in report


def test_app_context_uses_friendly_process_labels():
    context = ForegroundContext(
        process_name="Code.exe",
        window_title="main.py - Winsper",
        profile_name="code",
        profile=ProfileStyle(label="Code-aware"),
    )
    assert context.app_label == "VS Code"
    assert context.hud_context_label == "VS Code"
    assert friendly_process_label("python.exe", "Winsper Settings") == "Winsper Settings"


def test_app_context_applies_builtin_native_formatting_profiles_to_existing_configs():
    from voicepilot.app_context import WindowInfo

    detector = AppContextDetector(AppConfig())
    assert detector.detect_fast(WindowInfo(1, "thunderbird.exe", "Inbox")).profile_name == "email"
    assert detector.detect_fast(WindowInfo(2, "onenote.exe", "Project notes")).profile_name == "notes"
    assert detector.detect_fast(WindowInfo(3, "zoom.exe", "Team meeting chat")).profile_name == "chat"
    assert detector.detect_fast(WindowInfo(4, "pycharm64.exe", "main.py")).profile_name == "code"
    assert is_winsper_window("python.exe", "Winsper Settings")
    own_context = ForegroundContext(
        process_name="python.exe",
        window_title="Winsper Settings",
        profile_name="code",
        profile=ProfileStyle(label="Code-aware"),
    )
    assert own_context.app_label == "Winsper Settings"
    assert own_context.hud_label == "Code-aware - Winsper Settings"


def test_browser_site_style_defaults_apply_to_writing_profile():
    detector = AppContextDetector(AppConfig())
    style = detector._match_site_style("claude.ai")
    assert style is not None
    context = ForegroundContext(
        process_name="chrome.exe",
        window_title="Claude",
        profile_name="prompt",
        profile=AppConfig().profiles.styles["prompt"],
        browser_domain="claude.ai",
        browser_label="Claude",
        site_style=style,
    )
    assert "AI-assistant prompt" in context.writing_profile.dictation_prompt


def test_writing_style_presets_are_safe_defaults_not_a_second_profile_engine():
    base = ProfileStyle(label="Email", dictation_prompt="Format as an email.", rewrite_prompt="Keep an email tone.")
    assert apply_writing_style(base, "natural") is base
    assert apply_writing_style(base, "custom", "") is base

    concise = apply_writing_style(base, "concise")
    professional = apply_writing_style(base, "professional")
    custom = apply_writing_style(base, "custom", "Keep sentences short and warm.")

    for styled in (concise, professional, custom):
        assert styled.label == "Email"
        assert "Format as an email." in styled.dictation_prompt
        assert "Keep an email tone." in styled.rewrite_prompt
        assert "explicit request" in styled.rewrite_prompt
    assert "concise wording" in concise.dictation_prompt
    assert "professional wording" in professional.dictation_prompt
    assert "Keep sentences short and warm." in custom.dictation_prompt


def test_writing_style_composes_with_email_chat_docs_and_code_awareness():
    from voicepilot.app_context import WindowInfo

    config = AppConfig()
    config.writing_style.preset = "concise"
    detector = AppContextDetector(config)
    cases = (
        ("outlook.exe", "New message", "email"),
        ("slack.exe", "Project chat", "chat"),
        ("winword.exe", "Draft", "docs"),
        ("code.exe", "main.py", "code"),
    )
    for index, (process, title, expected_profile) in enumerate(cases, start=1):
        context = detector.detect_fast(WindowInfo(index, process, title))
        assert context.profile_name == expected_profile
        assert context.writing_profile.label == context.profile.label
        assert "concise wording" in context.writing_profile.dictation_prompt
        assert "concise wording" in context.writing_profile.rewrite_prompt


def test_writing_style_layers_after_browser_site_behavior():
    from voicepilot.app_context import BrowserPageContext, WindowInfo

    config = AppConfig()
    config.writing_style.preset = "custom"
    config.writing_style.custom_instruction = "Prefer short paragraphs."
    detector = AppContextDetector(config)
    context = detector._build_context(
        WindowInfo(9, "chrome.exe", "Inbox - Gmail"),
        BrowserPageContext("mail.google.com", "Gmail"),
    )

    assert "email" in context.writing_profile.dictation_prompt.lower()
    assert "Prefer short paragraphs." in context.writing_profile.dictation_prompt


def test_model_repo_cache_dir_name():
    assert cache_dir_name("Systran/faster-whisper-small.en") == "models--Systran--faster-whisper-small.en"


def test_find_gpu_model_preset():
    preset = find_speech_model("large-v3-turbo")
    assert preset is not None
    assert preset.device_hint == "cuda"


def test_find_parakeet_model_preset_uses_sherpa_engine():
    preset = find_speech_model("parakeet-tdt-0.6b-v2-int8")
    assert preset is not None
    assert preset.engine == "sherpa_onnx"
    assert engine_for_model(preset.model) == "sherpa_onnx"


def test_cached_model_resolution_is_silent(tmp_path, monkeypatch):
    from voicepilot.models import resolve_model_path

    preset = find_speech_model("parakeet-tdt-0.6b-v2-int8")
    assert preset is not None
    for filename in ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"):
        (tmp_path / filename).write_bytes(b"ready")
    monkeypatch.setattr("voicepilot.model_storage.find_cached_model_path", lambda _repo_id: tmp_path)
    assert resolve_model_path(preset) == tmp_path


def test_completed_model_progress_is_not_labeled_as_downloading():
    from voicepilot.app_helpers import speech_progress_detail, speech_progress_title
    from voicepilot.models import DownloadProgress

    progress = DownloadProgress(
        model="parakeet-tdt-0.6b-v2-int8",
        repo_id="example/parakeet",
        status="Already downloaded",
        downloaded_bytes=1,
        total_bytes=1,
        done=True,
    )

    assert speech_progress_title(progress) == "Model ready"
    assert speech_progress_detail(progress) == "parakeet-tdt-0.6b-v2-int8"


def test_cached_preload_does_not_leave_processing_hud_visible():
    import threading
    from types import SimpleNamespace
    from unittest.mock import Mock

    from voicepilot.app_lifecycle import ListenerLifecycleMixin
    from voicepilot.models import DownloadProgress

    harness = SimpleNamespace(_stop_event=threading.Event(), hud=Mock())
    cached_load = DownloadProgress(
        model="small.en",
        repo_id="Systran/faster-whisper-small.en",
        status="Loading model into memory",
    )
    ListenerLifecycleMixin._show_preload_progress(harness, cached_load)
    harness.hud.show.assert_not_called()

    downloading = DownloadProgress(
        model="small.en",
        repo_id="Systran/faster-whisper-small.en",
        status="Downloading 4 files",
        total_bytes=100,
    )
    ListenerLifecycleMixin._show_preload_progress(harness, downloading)
    harness.hud.show.assert_called_once_with(
        "Downloading small.en",
        "Starting download. 100 B total.",
        "process",
    )

    completed = DownloadProgress(
        model="small.en",
        repo_id="Systran/faster-whisper-small.en",
        status="Download complete",
        downloaded_bytes=100,
        total_bytes=100,
        done=True,
    )
    ListenerLifecycleMixin._show_preload_progress(harness, completed)
    assert harness.hud.show.call_args_list[-1].args == ("Model ready", "small.en", "success")


def test_quick_setup_model_avoids_uncached_large_models():
    with tempfile.TemporaryDirectory() as temp_dir:
        assert quick_setup_model_for("medium.en", cache_root=Path(temp_dir)) == "base.en"
        assert quick_setup_model_for("large-v3-turbo", cache_root=Path(temp_dir)) == "base.en"
        assert quick_setup_model_for("base.en", cache_root=Path(temp_dir)) == "base.en"


def test_recommend_cpu_default():
    hardware = HardwareSummary(cpu="CPU", ram_gb=16.0, gpus=("Intel Arc",), has_nvidia=False, has_intel_arc=True)
    assert recommended_model_for_hardware(hardware).model == "small.en"


def test_snippet_trigger_matches_clean_transcript():
    snippet = Snippet(name="Signature", trigger="signature", text="Best,\nAvery", aliases=["my signature"], profiles=[])
    match = match_snippet("My signature.", [snippet], profile_name="email")
    assert match is not None
    assert match.text == "Best,\nAvery"
    assert match.mode == "command"


def test_snippet_profile_scope():
    snippet = Snippet(name="Email only", trigger="signature", text="Best", profiles=["email"])
    assert match_snippet("signature", [snippet], profile_name="chat") is None


def test_snippet_normalizes_punctuation():
    assert normalize_trigger("  Today's date! ") == "today's date"


def test_snippet_general_scope_matches_any_profile():
    snippet = Snippet(name="Mail", trigger="Insert mail id here", text="avery@example.com", profiles=["general"])
    match = match_snippet("insert mail id here", [snippet], profile_name="prompt")
    assert match is not None
    assert match.text == "avery@example.com"


def test_snippet_matches_email_variant():
    snippet = Snippet(name="Mail", trigger="Insert mail id here", text="avery@example.com")
    match = match_snippet("insert email ID here.", [snippet], profile_name="general")
    assert match is not None
    assert match.text == "avery@example.com"


def test_snippet_allows_polite_command_prefix():
    snippet = Snippet(name="Mail", trigger="Insert mail id here", text="avery@example.com")
    match = match_snippet("please insert email ID here.", [snippet], profile_name="general")
    assert match is not None
    assert match.text == "avery@example.com"


def test_snippet_replaces_embedded_phrase_inline():
    snippet = Snippet(name="Mail", trigger="Insert mail id here", text="avery@example.com")
    match = match_snippet("my mail id is insert mail id here", [snippet], profile_name="general")
    assert match is not None
    assert match.mode == "inline"
    assert match.text == "my mail id is avery@example.com"


def test_snippet_replaces_trigger_before_suffix_inline():
    snippet = Snippet(name="Mail", trigger="Insert mail id here", text="avery@example.com")
    match = match_snippet("insert mail id here today", [snippet], profile_name="general")
    assert match is not None
    assert match.mode == "inline"
    assert match.text == "avery@example.com today"


def test_snippet_replaces_sentence_inline():
    snippet = Snippet(name="Mail", trigger="Insert mail id here", text="avery@example.com")
    match = match_snippet(
        "So I heard that you wanted my mail id right? So my mail id is insert mail id here.",
        [snippet],
        profile_name="general",
    )
    assert match is not None
    assert match.mode == "inline"
    assert match.text == "So I heard that you wanted my mail id right? So my mail id is avery@example.com."


def test_snippet_prefers_longest_exact_trigger():
    short = Snippet(name="Short", trigger="status", text="short")
    long = Snippet(name="Long", trigger="project status", text="long")
    match = match_snippet("project status", [short, long])
    assert match is not None
    assert match.snippet.name == "Long"


def test_polish_prompt_returns_only_text():
    prompt = build_polish_prompt("um hello there", ["Avery"])
    assert "Return only insertion-ready final text" in prompt
    assert "Remove genuine fillers" in prompt
    assert "Preserve the speaker's intended meaning" in prompt
    assert "um hello there" in prompt


def test_polish_instruction_echo_is_rejected_without_custom_instruction():
    assert looks_like_polish_instruction_echo("Cleanup rules: remove filler words.")
    assert looks_like_polish_instruction_echo("Return only the polished text.")
    assert not looks_like_polish_instruction_echo("Please clean the kitchen tomorrow.")


def test_history_store_appends_newest_first_and_trims():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp:
        store = HistoryStore(Path(temp) / "history.jsonl", max_items=2)
        for index in range(3):
            store.append(
                HistoryEvent(
                    id=str(index),
                    created_at=f"2026-05-14T00:00:0{index}+00:00",
                    mode="ramble",
                    input_text=f"input {index}",
                    output_text=f"output {index}",
                    profile_name="general",
                    profile_label="General",
                    process_name="app.exe",
                    window_title="App",
                    speech_model="small.en",
                    word_count=2,
                )
            )
        events = store.list()
        assert [event.id for event in events] == ["2", "1"]


def test_history_store_updates_checkpoint_delivery_source():
    with tempfile.TemporaryDirectory() as temp:
        store = HistoryStore(Path(temp) / "history.jsonl")
        event = HistoryEvent(
            id="checkpoint",
            created_at="2026-05-14T00:00:00+00:00",
            mode="ramble",
            input_text="input",
            output_text="output",
            profile_name="general",
            profile_label="General",
            process_name="app.exe",
            window_title="App",
            speech_model="small.en",
            source="dictation:pending",
        )
        store.append(event)

        updated = store.update_source(event.id, "dictation:paste_copied")

        assert updated is not None
        assert updated.source == "dictation:paste_copied"
        assert store.latest() is not None
        assert store.latest().source == "dictation:paste_copied"


def test_history_path_lives_next_to_config():
    from pathlib import Path

    assert history_path_for_config(Path("C:/tmp/config.yaml")).name == "history.enc"
    assert corrections_path_for_config(Path("C:/tmp/config.yaml")).name == "corrections.json"
    assert speed_lab_path_for_config(Path("C:/tmp/config.yaml")).name == "speed_benchmarks.json"
