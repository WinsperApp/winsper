from __future__ import annotations


from .settings_style import settings_stylesheet


class SettingsRegistryMixin:
    def _page_for_widget(self, key: str) -> str:
        if key in {
            "hotkeys.dictate",
            "hotkeys.cancel",
            "hotkeys.tap_to_toggle_dictation",
            "hotkeys.toggle_tap_seconds",
        }:
            return "Dictation"
        if key == "hotkeys.polish":
            return "Polish"
        if key.startswith("dictation."):
            return "Polish" if key == "dictation.polish_enabled" else "Dictation"
        if key.startswith("spoken_formatting."):
            return "Dictation"
        if key.startswith("spoken_actions."):
            return "Dictation"
        if key.startswith("snippets."):
            return "Personalize"
        if key.startswith("correction_memory."):
            return "Personalize"
        if key.startswith("writing_style."):
            return "Personalize"
        if key.startswith("history."):
            return "History"
        if key.startswith("hud.") or key.startswith("tray.") or key.startswith("startup."):
            return "General"
        return "Hidden Fields"

    def _hidden_widget_keys(self) -> list[str]:
        return [
            "speech.engine",
            "speech.model",
            "speech.device",
            "speech.compute_type",
            "speech.language",
            "speech.beam_size",
            "speech.preload_on_startup",
            "speech.max_cached_models",
            "audio.input_device",
            "speech.vad_filter",
            "paste.restore_clipboard",
            "rewrite.provider",
            "rewrite.ollama_url",
            "rewrite.model",
            "rewrite.temperature",
            "rewrite.timeout_seconds",
            "rewrite.preview_before_apply",
            "rewrite.ollama_keep_alive",
            "rewrite.llama_server_path",
            "rewrite.llama_model_id",
            "rewrite.llama_model_path",
            "rewrite.llama_device",
            "rewrite.llama_gpu_layers",
            "voice_commands.enabled",
            "voice_commands.edit_presets_enabled",
            "voice_commands.local_actions_enabled",
            "vocabulary",
            "profiles.enabled",
            "browser_context.enabled",
            "profiles.default_profile",
        ]

    def stylesheet(self) -> str:
        return settings_stylesheet(self.palette)
