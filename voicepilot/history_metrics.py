from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


def measure_ms(function: Callable[..., T], *args: Any, **kwargs: Any) -> tuple[T, int]:
    started = time.perf_counter()
    result = function(*args, **kwargs)
    return result, max(1, int(round((time.perf_counter() - started) * 1000)))


def measure_text_ms(function: Callable[..., str], *args: Any, **kwargs: Any) -> tuple[str, int]:
    result, elapsed_ms = measure_ms(function, *args, **kwargs)
    return result.strip(), elapsed_ms


def performance_fields(transcription_ms: int, polish_ms: int, speech_config: Any, active_config: Any) -> dict[str, Any]:
    return {
        "transcription_ms": transcription_ms,
        "polish_ms": polish_ms,
        "speech_engine": speech_config.engine,
        "speech_device": active_config.device,
        "speech_compute_type": active_config.compute_type,
    }
