from __future__ import annotations


from .autostart import set_start_with_windows
from .config import save_config, select_audio_input_device
from .control import request_control_command
from .models import (
    engine_for_model,
    find_speech_model,
)
from .hotkeys import validate_hotkey_bindings
from .history import retention_days_from_label
from .parsing import parse_float, parse_int
from .settings_helpers import (
    bool_value,
    combo_value,
    list_items,
    text_value,
)
from .settings_microphone import microphone_preference_value
from .system_audio import parse_input_device
from .writing_style import clean_custom_instruction, normalize_writing_style


class SettingsPersistenceMixin:
    def _auto_save(self) -> None:
        """Called automatically when any widget changes. Saves silently."""
        self._save(silent=True)

    def _save(self, silent: bool = False) -> None:
        from PySide6.QtWidgets import QMessageBox

        c = self.config

        def get_val(key, fallback_val, extractor=text_value):
            if key in self.widgets:
                try:
                    return extractor(self.widgets[key])
                except Exception:
                    pass
            return fallback_val

        dictate = get_val("hotkeys.dictate", c.hotkeys.dictate)
        polish = get_val("hotkeys.polish", c.hotkeys.polish)
        cancel = get_val("hotkeys.cancel", c.hotkeys.cancel)
        hotkey_errors = validate_hotkey_bindings(dictate, polish, cancel)
        if hotkey_errors:
            message = hotkey_errors[0]
            self.status.setText(message)
            self._show_toast("Invalid shortcut", "bad")
            if not silent:
                QMessageBox.warning(self.window, "Winsper", message)
            return

        c.hotkeys.dictate = dictate
        c.hotkeys.polish = polish
        c.hotkeys.cancel = cancel
        c.hotkeys.tap_to_toggle_dictation = get_val("hotkeys.tap_to_toggle_dictation", c.hotkeys.tap_to_toggle_dictation, bool_value)
        c.hotkeys.toggle_tap_seconds = parse_float(
            get_val("hotkeys.toggle_tap_seconds", str(c.hotkeys.toggle_tap_seconds)), c.hotkeys.toggle_tap_seconds
        )
        selected_default_model = get_val("speech.model", c.speech.model, combo_value)
        selected_speech_model = get_val("dictation.ramble_model", selected_default_model, combo_value)
        if selected_speech_model != c.speech.model:
            c.speech.engine = engine_for_model(selected_speech_model, c.speech.engine)
            preset = find_speech_model(selected_speech_model)
            if preset is not None:
                c.speech.device = preset.device_hint
                c.speech.compute_type = preset.compute_hint
            self._sync_model_widgets()
        c.speech.model = selected_speech_model
        c.dictation.ramble_model = selected_speech_model
        c.dictation.polish_model = selected_speech_model
        c.dictation.rewrite_instruction_model = selected_speech_model
        c.dictation.polish_enabled = get_val("dictation.polish_enabled", c.dictation.polish_enabled, bool_value)
        c.dictation.polish_fallback_to_ramble = get_val(
            "dictation.polish_fallback_to_ramble", c.dictation.polish_fallback_to_ramble, bool_value
        )
        c.speech.engine = get_val("speech.engine", c.speech.engine, combo_value)
        c.speech.device = get_val("speech.device", c.speech.device, combo_value)
        c.speech.compute_type = get_val("speech.compute_type", c.speech.compute_type, combo_value)
        # float16 is a CUDA precision.  A stale Settings widget used to create
        # an invalid cpu/float16 pair after choosing a GPU-oriented model.
        if c.speech.device == "cpu" and c.speech.compute_type == "float16":
            c.speech.compute_type = "int8"
            self._sync_model_widgets()
        c.speech.language = get_val("speech.language", c.speech.language)
        c.speech.beam_size = parse_int(get_val("speech.beam_size", str(c.speech.beam_size)), c.speech.beam_size)
        c.speech.preload_on_startup = get_val("speech.preload_on_startup", c.speech.preload_on_startup, bool_value)
        c.speech.max_cached_models = max(
            1,
            min(
                3,
                parse_int(
                    get_val("speech.max_cached_models", str(c.speech.max_cached_models)),
                    c.speech.max_cached_models,
                ),
            ),
        )

        if "audio.input_device" in self.widgets:
            select_audio_input_device(
                c.audio,
                parse_input_device(microphone_preference_value(self.widgets["audio.input_device"])),
            )

        c.speech.vad_filter = get_val("speech.vad_filter", c.speech.vad_filter, bool_value)
        c.paste.restore_clipboard = get_val("paste.restore_clipboard", c.paste.restore_clipboard, bool_value)
        c.rewrite.provider = get_val("rewrite.provider", c.rewrite.provider, combo_value)
        c.rewrite.ollama_url = get_val("rewrite.ollama_url", c.rewrite.ollama_url)
        c.rewrite.model = get_val("rewrite.model", c.rewrite.model)
        c.rewrite.temperature = parse_float(get_val("rewrite.temperature", str(c.rewrite.temperature)), c.rewrite.temperature)
        c.rewrite.timeout_seconds = parse_int(get_val("rewrite.timeout_seconds", str(c.rewrite.timeout_seconds)), c.rewrite.timeout_seconds)
        c.rewrite.preview_before_apply = get_val("rewrite.preview_before_apply", c.rewrite.preview_before_apply, bool_value)
        c.rewrite.ollama_keep_alive = parse_int(
            get_val("rewrite.ollama_keep_alive", str(c.rewrite.ollama_keep_alive)), c.rewrite.ollama_keep_alive
        )
        c.rewrite.llama_server_path = get_val("rewrite.llama_server_path", c.rewrite.llama_server_path)
        c.rewrite.llama_model_id = get_val("rewrite.llama_model_id", c.rewrite.llama_model_id, combo_value)
        c.rewrite.llama_model_path = get_val("rewrite.llama_model_path", c.rewrite.llama_model_path)
        c.rewrite.llama_device = get_val("rewrite.llama_device", c.rewrite.llama_device)
        c.rewrite.llama_gpu_layers = get_val("rewrite.llama_gpu_layers", c.rewrite.llama_gpu_layers)
        c.voice_commands.enabled = get_val("voice_commands.enabled", c.voice_commands.enabled, bool_value)
        c.voice_commands.edit_presets_enabled = get_val(
            "voice_commands.edit_presets_enabled", c.voice_commands.edit_presets_enabled, bool_value
        )
        c.voice_commands.local_actions_enabled = get_val(
            "voice_commands.local_actions_enabled", c.voice_commands.local_actions_enabled, bool_value
        )
        c.spoken_formatting.enabled = get_val("spoken_formatting.enabled", c.spoken_formatting.enabled, bool_value)
        c.spoken_actions.enabled = get_val("spoken_actions.enabled", c.spoken_actions.enabled, bool_value)
        c.spoken_actions.enter_phrase = (
            get_val("spoken_actions.enter_phrase", c.spoken_actions.enter_phrase) or c.spoken_actions.enter_phrase
        )
        c.snippets.enabled = get_val("snippets.enabled", c.snippets.enabled, bool_value)
        c.writing_style.preset = normalize_writing_style(
            get_val(
                "writing_style.preset",
                c.writing_style.preset,
                lambda widget: str(widget.currentData() or ""),
            )
        )
        c.writing_style.custom_instruction = clean_custom_instruction(
            get_val("writing_style.custom_instruction", c.writing_style.custom_instruction)
        )

        if hasattr(self, "snippets"):
            c.snippets.items = list(self.snippets)

        c.correction_memory.enabled = get_val("correction_memory.enabled", c.correction_memory.enabled, bool_value)
        c.correction_memory.max_rules = parse_int(
            get_val("correction_memory.max_rules", str(c.correction_memory.max_rules)), c.correction_memory.max_rules
        )

        if "vocabulary" in self.widgets:
            c.vocabulary = list_items(self.widgets["vocabulary"])

        c.hud.theme = get_val(
            "hud.theme",
            c.hud.theme,
            lambda widget: str(widget.currentData() or widget.currentText()).strip().lower(),
        )
        c.hud.mode = get_val(
            "hud.mode",
            c.hud.mode,
            lambda widget: str(widget.currentData() or widget.currentText()).strip().lower(),
        )
        if c.hud.mode not in {"standard", "compact"}:
            c.hud.mode = "compact"
        c.hud.position = get_val(
            "hud.position",
            c.hud.position,
            lambda widget: str(widget.currentData() or widget.currentText()).strip().lower(),
        )
        if c.hud.position not in {"center", "left", "right", "top"}:
            c.hud.position = "center"
        c.hud.enabled = get_val("hud.enabled", c.hud.enabled, bool_value)
        c.hud.recording_chimes = get_val(
            "hud.recording_chimes",
            c.hud.recording_chimes,
            bool_value,
        )
        c.tray.enabled = get_val("tray.enabled", c.tray.enabled, bool_value)
        c.startup.start_with_windows = get_val("startup.start_with_windows", c.startup.start_with_windows, bool_value)
        c.hud.show_idle = get_val("hud.show_idle", c.hud.show_idle, bool_value)
        c.hud.opacity = parse_float(get_val("hud.opacity", str(c.hud.opacity)), c.hud.opacity)
        c.hud.auto_hide_seconds = parse_float(get_val("hud.auto_hide_seconds", str(c.hud.auto_hide_seconds)), c.hud.auto_hide_seconds)
        c.history.enabled = get_val("history.enabled", c.history.enabled, bool_value)
        c.history.max_items = parse_int(get_val("history.max_items", str(c.history.max_items)), c.history.max_items)
        c.history.retention_days = retention_days_from_label(
            get_val("history.retention_days", "", combo_value),
            c.history.retention_days,
        )
        c.profiles.enabled = get_val("profiles.enabled", c.profiles.enabled, bool_value)
        c.browser_context.enabled = get_val("browser_context.enabled", c.browser_context.enabled, bool_value)
        c.profiles.default_profile = get_val("profiles.default_profile", c.profiles.default_profile, combo_value)

        if hasattr(self, "profile_styles"):
            c.profiles.styles = dict(self.profile_styles)
        if hasattr(self, "profile_rules"):
            c.profiles.rules = list(self.profile_rules)

        if c.profiles.styles and c.profiles.default_profile not in c.profiles.styles:
            c.profiles.default_profile = next(iter(c.profiles.styles))

        try:
            save_config(c, self.config_path)
            set_start_with_windows(self.config_path, c.startup.start_with_windows)
            correction_policy_changed = (
                self.correction_store.max_rules != c.correction_memory.max_rules
                or self.correction_store.enabled != c.correction_memory.enabled
            )
            self.correction_store.max_rules = c.correction_memory.max_rules
            self.correction_store.enabled = c.correction_memory.enabled
            if correction_policy_changed or tuple(self.corrections) != self._saved_corrections:
                self.correction_store.replace_all(self.corrections)
                self._saved_corrections = tuple(self.correction_store.list())
            request_control_command(self.config_path, "reload_silent")
            self._refresh_model_status_label()
        except Exception as exc:
            self.status.setText(f"Unable to save settings: {exc}")
            self._show_toast(
                "Save failed",
                "bad",
                persistent=True,
                action_label="Retry",
                action_callback=lambda: self._save(silent=False),
            )
            if not silent:
                QMessageBox.critical(self.window, "Winsper", f"Unable to save your settings:\n{exc}")
            return
        # Briefly confirm successful auto-save.
        self._flash_saved_indicator()
        self.status.setText("All changes applied — no restart needed.")
