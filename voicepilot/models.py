"""Compatibility facade for speech model catalog, storage, and hardware."""

from .speech_languages import (  # noqa: F401
    PARAKEET_V3_LANGUAGES,
    SPEECH_LANGUAGE_NAMES,
    model_supports_language,
    speech_language_options,
)
from .speech_model_catalog import *  # noqa: F403
from .model_storage import *  # noqa: F403
from .model_progress import *  # noqa: F403
from .hardware_detection import *  # noqa: F403

__all__ = [
    "PARAKEET_V3_LANGUAGES",
    "SPEECH_LANGUAGE_NAMES",
    "model_supports_language",
    "speech_language_options",
]
