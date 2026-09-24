from unittest.mock import Mock

import pytest

from voicepilot.models import SpeechModelNotInstalled, find_speech_model, resolve_model_path


def test_runtime_model_resolution_never_starts_a_download(monkeypatch):
    preset = find_speech_model("small.en")
    assert preset is not None
    download = Mock()
    monkeypatch.setattr("voicepilot.model_storage.find_cached_model_path", lambda _repo: None)
    monkeypatch.setattr("voicepilot.model_storage.download_model", download)

    with pytest.raises(SpeechModelNotInstalled, match="Settings > Dictation > Advanced"):
        resolve_model_path(preset)

    download.assert_not_called()
