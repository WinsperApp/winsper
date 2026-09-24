from __future__ import annotations

from .app_speech_backend import SpeechBackendLifecycleMixin
from .lifecycle_capture import CaptureLifecycleMixin
from .lifecycle_context import ActionContextMixin
from .lifecycle_control import LifecycleControlMixin
from .lifecycle_types import PolishSelectionCapture


class ListenerLifecycleMixin(
    LifecycleControlMixin,
    CaptureLifecycleMixin,
    ActionContextMixin,
    SpeechBackendLifecycleMixin,
):
    pass


__all__ = ["ListenerLifecycleMixin", "PolishSelectionCapture"]
