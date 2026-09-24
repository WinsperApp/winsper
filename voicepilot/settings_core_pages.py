from __future__ import annotations

from .models import speech_engine_values, speech_model_values


class SettingsCorePagesMixin:
    def _build_hidden_fields_page(self):
        page, layout = self._page("Hidden Fields", "Internal Settings storage.")
        layout.addWidget(self._combo("speech.engine", self.config.speech.engine, speech_engine_values()))
        layout.addWidget(self._combo("speech.model", self.config.speech.model, speech_model_values()))
        layout.addWidget(self._combo("speech.device", self.config.speech.device, ["cpu", "cuda", "auto"]))
        layout.addWidget(
            self._combo(
                "speech.compute_type",
                self.config.speech.compute_type,
                ["int8", "int8_float16", "float16", "float32"],
            )
        )
        layout.addWidget(self._line("speech.language", self.config.speech.language))
        layout.addWidget(self._line("speech.beam_size", str(self.config.speech.beam_size)))
        layout.addWidget(self._check("speech.preload_on_startup", self.config.speech.preload_on_startup))
        layout.addWidget(self._line("speech.max_cached_models", str(self.config.speech.max_cached_models)))
        selected_input = "" if self.config.audio.input_device is None else str(self.config.audio.input_device)
        input_options = [""] if not selected_input else ["", selected_input]
        layout.addWidget(self._combo("audio.input_device", selected_input, input_options))
        layout.addWidget(self._check("speech.vad_filter", self.config.speech.vad_filter))
        layout.addWidget(self._line("rewrite.ollama_url", self.config.rewrite.ollama_url))
        layout.addWidget(self._line("rewrite.model", self.config.rewrite.model))
        layout.addWidget(self._line("rewrite.temperature", str(self.config.rewrite.temperature)))
        layout.addWidget(self._line("rewrite.timeout_seconds", str(self.config.rewrite.timeout_seconds)))
        layout.addWidget(self._check("rewrite.preview_before_apply", self.config.rewrite.preview_before_apply))
        layout.addWidget(self._line("rewrite.ollama_keep_alive", str(self.config.rewrite.ollama_keep_alive)))
        layout.addWidget(self._check("voice_commands.enabled", self.config.voice_commands.enabled))
        layout.addWidget(self._check("voice_commands.edit_presets_enabled", self.config.voice_commands.edit_presets_enabled))
        layout.addWidget(self._check("voice_commands.local_actions_enabled", self.config.voice_commands.local_actions_enabled))
        if "vocabulary" not in self.widgets:
            vocab = self._hidden_list_widget()
            vocab.addItems(self.config.vocabulary)
            self.widgets["vocabulary"] = vocab
            layout.addWidget(vocab)
        layout.addWidget(self._check("profiles.enabled", self.config.profiles.enabled))
        layout.addWidget(self._check("browser_context.enabled", self.config.browser_context.enabled))
        layout.addWidget(
            self._combo(
                "profiles.default_profile",
                self.config.profiles.default_profile,
                list(self.profile_styles.keys()),
            )
        )
        return page

    @staticmethod
    def _hidden_list_widget():
        from PySide6.QtWidgets import QListWidget

        widget = QListWidget()
        widget.hide()
        return widget
