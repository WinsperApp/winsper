from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audio_devices import same_physical_device_name
from .config_migrations import CURRENT_SCHEMA_VERSION, migrate_config_data
from .starter_content import STARTER_VOCABULARY, starter_text_shortcut_dicts
from .storage import atomic_write_text
from .writing_style import clean_custom_instruction, normalize_writing_style

_CONFIG_WRITE_LOCK = threading.RLock()
HUD_POSITIONS = ("center", "left", "right", "top")


@dataclass
class HotkeyConfig:
    dictate: str = "ctrl+win+space"
    polish: str = "ctrl+win+p"
    cancel: str = "ctrl+win+esc"
    tap_to_toggle_dictation: bool = True
    toggle_tap_seconds: float = 0.35


@dataclass
class AudioConfig:
    input_device: int | str | None = None
    # Stable endpoint metadata. `input_device` remains backwards compatible,
    # but Windows device indexes are not persisted as the source of truth.
    input_device_fingerprint: str = ""
    input_device_name: str = ""
    input_device_host_api: str = ""
    input_device_channels: int = 0
    input_device_sample_rate: int = 0
    last_successful_input_at: float = 0.0
    sample_rate: int = 16000
    channels: int = 1
    min_record_seconds: float = 0.25


def select_audio_input_device(audio: AudioConfig, selected: int | str | None) -> bool:
    """Apply a user microphone choice and discard facts from the old route."""
    if audio.input_device == selected:
        return False
    audio.input_device = selected
    audio.input_device_fingerprint = ""
    audio.input_device_name = ""
    audio.input_device_host_api = ""
    audio.input_device_channels = 0
    audio.input_device_sample_rate = 0
    audio.last_successful_input_at = 0.0
    return True


@dataclass
class SpeechConfig:
    engine: str = "faster_whisper"
    model: str = "small.en"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "en"
    purpose: str = "dictation"
    beam_size: int = 1
    vad_filter: bool = True
    preload_on_startup: bool = True
    max_cached_models: int = 2


@dataclass
class ModelStorageConfig:
    # Empty means Winsper's platform-appropriate default locations.
    path: str = ""


@dataclass
class RewriteConfig:
    provider: str = "embedded"
    ollama_url: str = "http://127.0.0.1:11434/api/generate"
    model: str = "qwen2.5:1.5b"
    prompt_profile: str = "auto"
    temperature: float = 0.2
    seed: int = 7
    timeout_seconds: int = 45
    preview_before_apply: bool = False
    ollama_keep_alive: int = 300
    llama_server_path: str = ""
    llama_model_id: str = "qwen3-4b-instruct-2507-q4km"
    llama_model_path: str = ""
    llama_server_url: str = ""
    llama_api_key: str = ""
    llama_device: str = ""
    llama_gpu_layers: str = "auto"
    llama_context_size: int = 4096
    llama_threads: int = 0
    llama_start_timeout_seconds: int = 90
    llama_idle_seconds: int = 300


@dataclass
class DictationConfig:
    polish_enabled: bool = True
    ramble_model: str = "small.en"
    polish_model: str = "small.en"
    rewrite_instruction_model: str = "small.en"
    polish_fallback_to_ramble: bool = True
    quality_profile: str = ""  # instant | balanced | precise | custom; empty preserves legacy inference
@dataclass
class PasteConfig:
    restore_clipboard: bool = True
    restore_mode: str = "delayed"  # immediate | delayed | never
    restore_delay_ms: int = 120
    paste_delay_ms: int = 80
    copy_delay_ms: int = 120


@dataclass
class HudConfig:
    enabled: bool = True
    opacity: float = 0.94
    show_idle: bool = False
    auto_hide_seconds: float = 0.35
    theme: str = "system"
    mode: str = "compact"  # compact | standard
    position: str = "center"  # center | left | right | top
    recording_chimes: bool = True


@dataclass
class TrayConfig:
    enabled: bool = True


@dataclass
class StartupConfig:
    start_with_windows: bool = False


@dataclass
class OnboardingConfig:
    completed: bool = False
    completed_at: str = ""
    version: int = 1
    current_step: int = 0
    started_at: str = ""
    dictation_test_passed: bool = False
    polish_skipped: bool = False
    quality_profile: str = "balanced"


@dataclass
class UpdateConfig:
    feed_url: str = ""
    channel: str = "stable"
    auto_check: bool = True
    publisher: str = ""


@dataclass
class HistoryConfig:
    enabled: bool = True
    max_items: int = 200
    retention_days: int = 0


@dataclass
class CorrectionMemoryConfig:
    enabled: bool = True
    max_rules: int = 500


@dataclass
class VoiceCommandsConfig:
    enabled: bool = True
    edit_presets_enabled: bool = True
    local_actions_enabled: bool = True


@dataclass
class SpokenActionsConfig:
    enabled: bool = True
    enter_phrase: str = "press enter"


@dataclass
class SpokenFormattingConfig:
    enabled: bool = True


@dataclass
class Snippet:
    name: str
    trigger: str
    text: str
    aliases: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)


def default_text_shortcuts() -> list[Snippet]:
    return [Snippet(**item) for item in starter_text_shortcut_dicts()]


def default_vocabulary() -> list[str]:
    return list(STARTER_VOCABULARY)


@dataclass
class SnippetsConfig:
    enabled: bool = True
    items: list[Snippet] = field(default_factory=default_text_shortcuts)


@dataclass
class ProfileRule:
    profile: str
    processes: list[str] = field(default_factory=list)
    title_contains: list[str] = field(default_factory=list)


@dataclass
class BrowserRule:
    profile: str
    domains: list[str] = field(default_factory=list)


@dataclass
class BrowserSiteStyle:
    domains: list[str] = field(default_factory=list)
    label: str = ""
    dictation_prompt: str = ""
    rewrite_prompt: str = ""
    vocabulary: list[str] = field(default_factory=list)


@dataclass
class ProfileStyle:
    label: str
    dictation_prompt: str = ""
    rewrite_prompt: str = ""
    vocabulary: list[str] = field(default_factory=list)


@dataclass
class ProfilesConfig:
    enabled: bool = True
    default_profile: str = "general"
    rules: list[ProfileRule] = field(default_factory=list)
    styles: dict[str, ProfileStyle] = field(default_factory=dict)

@dataclass
class WritingStyleConfig:
    preset: str = "natural"
    custom_instruction: str = ""

@dataclass
class BrowserContextConfig:
    enabled: bool = True
    timeout_ms: int = 450
    browser_processes: list[str] = field(default_factory=lambda: default_browser_processes())
    rules: list[BrowserRule] = field(default_factory=lambda: default_browser_rules())
    site_styles: list[BrowserSiteStyle] = field(default_factory=lambda: default_browser_site_styles())


@dataclass
class AppConfig:
    schema_version: int = CURRENT_SCHEMA_VERSION
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    speech: SpeechConfig = field(default_factory=SpeechConfig)
    model_storage: ModelStorageConfig = field(default_factory=ModelStorageConfig)
    dictation: DictationConfig = field(default_factory=DictationConfig)
    rewrite: RewriteConfig = field(default_factory=RewriteConfig)
    paste: PasteConfig = field(default_factory=PasteConfig)
    hud: HudConfig = field(default_factory=HudConfig)
    tray: TrayConfig = field(default_factory=TrayConfig)
    startup: StartupConfig = field(default_factory=StartupConfig)
    onboarding: OnboardingConfig = field(default_factory=OnboardingConfig)
    updates: UpdateConfig = field(default_factory=UpdateConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    correction_memory: CorrectionMemoryConfig = field(default_factory=CorrectionMemoryConfig)
    voice_commands: VoiceCommandsConfig = field(default_factory=VoiceCommandsConfig)
    spoken_actions: SpokenActionsConfig = field(default_factory=SpokenActionsConfig)
    spoken_formatting: SpokenFormattingConfig = field(default_factory=SpokenFormattingConfig)
    snippets: SnippetsConfig = field(default_factory=SnippetsConfig)
    profiles: ProfilesConfig = field(default_factory=lambda: default_profiles_config())
    writing_style: WritingStyleConfig = field(default_factory=WritingStyleConfig)
    browser_context: BrowserContextConfig = field(default_factory=BrowserContextConfig)
    vocabulary: list[str] = field(default_factory=default_vocabulary)


def default_config_path() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        branded = Path(base) / "Winsper" / "config.yaml"
        legacy = Path(base) / "VoicePilot" / "config.yaml"
        return legacy if legacy.exists() and not branded.exists() else branded
    return Path.home() / ".voicepilot" / "config.yaml"


def resolve_config_path(path: Path | None = None) -> Path:
    return path or default_config_path()


def load_config(path: Path | None = None) -> AppConfig:
    config_path = resolve_config_path(path)
    if not config_path.exists():
        return AppConfig()

    with _CONFIG_WRITE_LOCK:
        data = _load_yaml(config_path)
        if data is None:
            return AppConfig()
        if not isinstance(data, dict):
            raise ValueError(f"Config must be a mapping: {config_path}")

        migration = migrate_config_data(data)
        config = _from_dict(migration.data)
        if migration.changed:
            _backup_and_write_migrated_config(config_path, data, migration.data, migration.source_version)
        return config


def config_to_dict(config: AppConfig) -> dict[str, Any]:
    return asdict(config)


def save_config(config: AppConfig, path: Path) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to write config files. Install requirements.txt.") from exc

    with _CONFIG_WRITE_LOCK:
        serialized = yaml.safe_dump(config_to_dict(config), sort_keys=False, allow_unicode=False)
        atomic_write_text(path, serialized)


def _backup_and_write_migrated_config(
    path: Path,
    original: dict[str, Any],
    migrated: dict[str, Any],
    source_version: int,
) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to migrate config files. Install requirements.txt.") from exc

    backup = path.with_name(f"{path.name}.schema-v{source_version}.bak")
    if not backup.exists():
        atomic_write_text(
            backup,
            yaml.safe_dump(original, sort_keys=False, allow_unicode=False),
        )
    atomic_write_text(
        path,
        yaml.safe_dump(migrated, sort_keys=False, allow_unicode=False),
    )


def persist_audio_device_identity(
    path: Path,
    *,
    name: str,
    host_api: str,
    fingerprint: str,
    channels: int,
    sample_rate: int,
    successful_at: float,
) -> None:
    """Persist only endpoint facts discovered after a healthy recording start."""
    with _CONFIG_WRITE_LOCK:
        latest = load_config(path)
        selected = latest.audio.input_device
        if isinstance(selected, str):
            selected_name, separator, selected_host = selected.rpartition(", ")
            if separator and (selected_host.casefold() != host_api.casefold() or not same_physical_device_name(selected_name, name)):
                # Settings may have changed while the audio worker was
                # finishing. Never let a stale result replace the new route.
                return
        latest.audio.input_device_name = name
        latest.audio.input_device_host_api = host_api
        latest.audio.input_device_fingerprint = fingerprint
        latest.audio.input_device_channels = max(0, int(channels))
        latest.audio.input_device_sample_rate = max(0, int(sample_rate))
        latest.audio.last_successful_input_at = max(0.0, float(successful_at))
        save_config(latest, path)


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read config files. Install requirements.txt.") from exc

    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    return default


def _normalize_speech_language(value: Any) -> str:
    from .models import SPEECH_LANGUAGE_NAMES

    code = str(value or "").strip().casefold()
    return code if code in SPEECH_LANGUAGE_NAMES else SpeechConfig().language


def _from_dict(data: dict[str, Any]) -> AppConfig:
    speech = _merge_dataclass(SpeechConfig, data.get("speech"))
    speech.language = _normalize_speech_language(speech.language)
    writing_style = _merge_dataclass(WritingStyleConfig, data.get("writing_style"))
    writing_style.preset = normalize_writing_style(writing_style.preset)
    writing_style.custom_instruction = clean_custom_instruction(writing_style.custom_instruction)
    hud = _merge_dataclass(HudConfig, data.get("hud"))
    hud.mode = hud.mode if hud.mode in {"standard", "compact"} else HudConfig().mode
    hud.position = hud.position if hud.position in HUD_POSITIONS else HudConfig().position
    return AppConfig(
        schema_version=int(data.get("schema_version", CURRENT_SCHEMA_VERSION)),
        hotkeys=_merge_dataclass(HotkeyConfig, data.get("hotkeys")),
        audio=_merge_dataclass(AudioConfig, data.get("audio")),
        speech=speech,
        model_storage=_merge_dataclass(ModelStorageConfig, data.get("model_storage")),
        dictation=_merge_dataclass(DictationConfig, data.get("dictation")),
        rewrite=_merge_dataclass(RewriteConfig, data.get("rewrite")),
        paste=_merge_dataclass(PasteConfig, data.get("paste")),
        hud=hud,
        tray=_merge_dataclass(TrayConfig, data.get("tray")),
        startup=_merge_dataclass(StartupConfig, data.get("startup")),
        onboarding=_merge_dataclass(OnboardingConfig, data.get("onboarding")),
        updates=_merge_dataclass(UpdateConfig, data.get("updates")),
        history=_merge_dataclass(HistoryConfig, data.get("history")),
        correction_memory=_merge_dataclass(CorrectionMemoryConfig, data.get("correction_memory")),
        voice_commands=_merge_dataclass(VoiceCommandsConfig, data.get("voice_commands")),
        spoken_actions=_merge_dataclass(SpokenActionsConfig, data.get("spoken_actions")),
        spoken_formatting=_merge_dataclass(SpokenFormattingConfig, data.get("spoken_formatting")),
        snippets=_snippets_from_dict(data.get("snippets")),
        profiles=_profiles_from_dict(data.get("profiles")),
        writing_style=writing_style,
        browser_context=_browser_context_from_dict(data.get("browser_context")),
        vocabulary=list(data.get("vocabulary") or []) if "vocabulary" in data else default_vocabulary(),
    )


def _merge_dataclass(cls, data: Any):
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ValueError(f"{cls.__name__} config must be a mapping.")
    defaults = asdict(cls())
    for key, value in data.items():
        if key not in defaults:
            continue
        default = defaults[key]
        if isinstance(default, bool):
            defaults[key] = parse_bool(value, default)
        else:
            defaults[key] = value
    return cls(**defaults)


def _profiles_from_dict(data: Any) -> ProfilesConfig:
    defaults = default_profiles_config()
    if data is None:
        return defaults
    if not isinstance(data, dict):
        raise ValueError("ProfilesConfig config must be a mapping.")

    raw_rules = data.get("rules", asdict(defaults)["rules"])
    default_styles = asdict(defaults)["styles"]
    configured_styles = data.get("styles") or {}
    if not isinstance(configured_styles, dict):
        raise ValueError("ProfilesConfig styles must be a mapping.")
    # New product profiles must reach existing configs without overwriting any
    # user-customized profile of the same name.
    raw_styles = {**default_styles, **configured_styles}

    rules = [
        ProfileRule(
            profile=str(rule.get("profile", "")),
            processes=list(rule.get("processes") or []),
            title_contains=list(rule.get("title_contains") or []),
        )
        for rule in raw_rules
        if isinstance(rule, dict)
    ]
    styles = {
        str(name): ProfileStyle(
            label=str(style.get("label", name)),
            dictation_prompt=str(style.get("dictation_prompt", "")),
            rewrite_prompt=str(style.get("rewrite_prompt", "")),
            vocabulary=list(style.get("vocabulary") or []),
        )
        for name, style in raw_styles.items()
        if isinstance(style, dict)
    }

    return ProfilesConfig(
        enabled=parse_bool(data.get("enabled"), defaults.enabled),
        default_profile=str(data.get("default_profile", defaults.default_profile)),
        rules=rules,
        styles=styles,
    )


def _snippets_from_dict(data: Any) -> SnippetsConfig:
    if data is None:
        return SnippetsConfig()
    if not isinstance(data, dict):
        raise ValueError("SnippetsConfig config must be a mapping.")

    raw_items = data.get("items", starter_text_shortcut_dicts()) or []
    items = [
        Snippet(
            name=str(item.get("name", item.get("trigger", ""))),
            trigger=str(item.get("trigger", "")),
            text=str(item.get("text", "")),
            aliases=list(item.get("aliases") or []),
            profiles=list(item.get("profiles") or []),
        )
        for item in raw_items
        if isinstance(item, dict)
    ]
    return SnippetsConfig(enabled=parse_bool(data.get("enabled"), True), items=items)


def _browser_context_from_dict(data: Any) -> BrowserContextConfig:
    defaults = BrowserContextConfig()
    if data is None:
        return defaults
    if not isinstance(data, dict):
        raise ValueError("BrowserContextConfig config must be a mapping.")

    raw_rules = data.get("rules", asdict(defaults)["rules"])
    raw_site_styles = data.get("site_styles", asdict(defaults)["site_styles"])
    raw_browser_processes = data.get("browser_processes", defaults.browser_processes)
    rules = [
        BrowserRule(
            profile=str(rule.get("profile", "")),
            domains=list(rule.get("domains") or []),
        )
        for rule in raw_rules
        if isinstance(rule, dict)
    ]
    site_styles = [
        BrowserSiteStyle(
            domains=list(style.get("domains") or []),
            label=str(style.get("label", "")),
            dictation_prompt=str(style.get("dictation_prompt", "")),
            rewrite_prompt=str(style.get("rewrite_prompt", "")),
            vocabulary=list(style.get("vocabulary") or []),
        )
        for style in raw_site_styles
        if isinstance(style, dict)
    ]
    return BrowserContextConfig(
        enabled=parse_bool(data.get("enabled"), defaults.enabled),
        timeout_ms=int(data.get("timeout_ms", defaults.timeout_ms)),
        browser_processes=list(raw_browser_processes or []),
        rules=rules,
        site_styles=site_styles,
    )


def default_browser_processes() -> list[str]:
    from .config_profiles import default_browser_processes as build_defaults

    return build_defaults()


def default_browser_rules() -> list[BrowserRule]:
    from .config_profiles import default_browser_rules as build_defaults

    return build_defaults()


def default_browser_site_styles() -> list[BrowserSiteStyle]:
    from .config_profiles import default_browser_site_styles as build_defaults

    return build_defaults()


def default_profiles_config() -> ProfilesConfig:
    from .config_profiles import default_profiles_config as build_defaults

    return build_defaults()
