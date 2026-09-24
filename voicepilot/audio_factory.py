from __future__ import annotations

from .config import AudioConfig
from .isolated_audio import IsolatedAudioRecorder


def create_audio_recorder(config: AudioConfig):
    """Create the platform recorder used by user-facing capture flows."""
    return IsolatedAudioRecorder(config)
