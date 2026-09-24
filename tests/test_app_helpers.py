from types import SimpleNamespace
from unittest.mock import patch

from voicepilot.app_helpers import friendly_error_message, polish_setup_issue
from voicepilot.config import AppConfig, SpeechConfig


def test_friendly_error_message_hides_native_allocation_details():
    message = friendly_error_message(RuntimeError("mkl_malloc: failed to allocate memory"))

    assert message == (
        "Not enough memory is available. Close large apps, free space on the Windows drive, then try again."
    )
    assert "mkl" not in message.lower()


def test_friendly_error_message_points_missing_runtime_model_to_settings():
    message = friendly_error_message(
        RuntimeError(
            "Speech model small.en is not installed. "
            "Download it from Settings > Dictation > Advanced."
        )
    )

    assert message == (
        "small.en is not installed. "
        "Download it from Settings > Dictation > Advanced."
    )


def test_polish_setup_issue_reports_missing_speech_model_before_ai_model():
    config = AppConfig()
    config.rewrite.provider = "ollama"
    config.rewrite.model = "qwen3:8b"

    with patch(
        "voicepilot.app_helpers.installed_status",
        return_value=SimpleNamespace(installed=False),
    ):
        issue = polish_setup_issue(config, (SpeechConfig(model="small.en"),))

    assert issue == (
        "Speech model required",
        "Download small.en in Settings > Dictation > Advanced",
    )


def test_polish_setup_issue_reports_missing_embedded_ai_model():
    config = AppConfig()
    config.rewrite.provider = "embedded"
    config.rewrite.llama_model_id = "qwen3-8b-q4km"

    with (
        patch(
            "voicepilot.app_helpers.installed_status",
            return_value=SimpleNamespace(installed=True),
        ),
        patch("voicepilot.app_helpers.model_is_installed", return_value=False),
    ):
        issue = polish_setup_issue(config, (SpeechConfig(model="small.en"),))

    assert issue == (
        "Polish model required",
        "Download or select an AI model in Settings > Polish > Advanced",
    )


def test_polish_setup_issue_accepts_configured_ollama_without_network_probe():
    config = AppConfig()
    config.rewrite.provider = "ollama"
    config.rewrite.model = "qwen3:8b"

    issue = polish_setup_issue(config, (SpeechConfig(model="private-model"),))

    assert issue is None
