from __future__ import annotations

import re


def is_bluetooth_microphone_name(value: str) -> bool:
    """Conservatively identify Windows Bluetooth hands-free input endpoints.

    Windows exposes classic Bluetooth microphone routes as headset/hands-free
    endpoints. Opening those routes can switch the radio profile and has caused
    kernel crashes on real customer hardware, so consumer builds never open them.
    """
    name = re.sub(r",\s*Windows\s+(?:WASAPI|DirectSound|MME)\s*$", "", value, flags=re.I).strip()
    folded = name.casefold()
    return (
        folded.startswith("headset (")
        or "hands-free" in folded
        or "hands free" in folded
        or "airpods" in folded
        or "bluetooth" in folded
        or re.search(r"\bbuds?\b", folded) is not None
    )


def is_unsafe_microphone_name(value: str) -> bool:
    """Reject unstable Bluetooth routes and ambiguous Windows aliases."""

    return is_bluetooth_microphone_name(value) or is_ambiguous_microphone_name(value)


def is_ambiguous_microphone_name(value: str) -> bool:
    """Identify aliases that cannot be bound to one stable Windows endpoint."""

    folded = value.casefold().strip()
    return (
        "microsoft sound mapper" in folded
        or "primary sound capture driver" in folded
    )


def is_muted_microphone_error(value: object) -> bool:
    """Recognize actionable Windows input-mute failures without masking silence."""

    folded = str(value).casefold()
    return "microphone" in folded and (
        "muted in windows" in folded
        or "input level is set to zero" in folded
    )
