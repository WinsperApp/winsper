from __future__ import annotations

from dataclasses import dataclass

from .audio_devices import safe_input_candidates, same_physical_device_name
from .audio_safety import is_unsafe_microphone_name


@dataclass(frozen=True)
class MicrophoneRouteStatus:
    preferred: str | None
    active: str | None
    preferred_available: bool

    @property
    def using_fallback(self) -> bool:
        return self.preferred is not None and not self.preferred_available and self.active is not None


def list_audio_devices() -> list[str]:
    try:
        import sounddevice as sd
    except (ImportError, OSError):
        return []

    values: list[str] = []
    try:
        candidates = safe_input_candidates(sd)
    except (sd.PortAudioError, TypeError, ValueError):
        return []

    seen_selectors: set[str] = set()
    seen_device_names: list[str] = []
    for selector in candidates:
        selector_key = selector.casefold()
        device_name, _separator, _host_api = selector.rpartition(", ")
        if selector_key in seen_selectors or any(
            same_physical_device_name(device_name, existing) for existing in seen_device_names
        ):
            continue
        try:
            sd.query_devices(selector, kind="input")
        except (sd.PortAudioError, TypeError, ValueError):
            # Ambiguous low-level endpoints are not safe persisted choices.
            continue
        seen_selectors.add(selector_key)
        seen_device_names.append(device_name)
        values.append(selector)
    return values


def display_audio_device_name(value: str | None) -> str:
    """Return a consumer-facing endpoint name without the PortAudio host suffix."""

    text = str(value or "").strip()
    name, separator, host_api = text.rpartition(", ")
    if separator and host_api.casefold() in {
        "windows wasapi",
        "windows directsound",
        "mme",
    }:
        return name.strip()
    return text


def resolve_microphone_route(
    preferred: str | int | None,
    available: list[str],
) -> MicrophoneRouteStatus:
    """Mirror the native preference/default/fallback order for Settings copy."""

    available = [device for device in available if not is_unsafe_microphone_name(device)]
    preferred_text = str(preferred).strip() if preferred is not None else ""
    if is_unsafe_microphone_name(preferred_text):
        preferred_text = ""
    if preferred_text.casefold() in {"", "auto", "default", "windows default"}:
        return MicrophoneRouteStatus(None, available[0] if available else None, True)

    active_preference = next(
        (
            candidate
            for candidate in available
            if same_physical_device_name(preferred_text, candidate)
        ),
        None,
    )
    return MicrophoneRouteStatus(
        preferred_text,
        active_preference or (available[0] if available else None),
        active_preference is not None,
    )


def parse_input_device(value: str) -> int | str | None:
    stripped = value.strip()
    if not stripped or stripped.lower() in {"auto", "default", "windows default"}:
        return None
    first, separator, remainder = stripped.partition(":")
    if first.strip().isdigit():
        # Existing settings used "index: name". Keep plain numeric values
        # readable, but persist newly selected devices by stable name/API.
        if separator and remainder.strip():
            return remainder.strip()
        return int(first.strip())
    return stripped
