"""Pure Windows microphone endpoint selection helpers."""

from __future__ import annotations

import re

from .audio_safety import is_unsafe_microphone_name


def named_selector(device, host_api: str) -> str | None:
    name = str(device.get("name") or "").strip()
    host = host_api.strip()
    return f"{name}, {host}" if name and host else None


def host_api_name_from_device(host_apis, device) -> str:
    try:
        return str(host_apis[int(device.get("hostapi") or 0)].get("name") or "")
    except Exception:
        return ""


def device_family_key(name: str) -> str:
    normalized = name.casefold().replace("’", "'").replace("‘", "'")
    normalized = re.sub(r"\bfind\s+my\b", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def same_physical_device_name(selected: str, candidate: str) -> bool:
    selected_key = device_family_key(selected)
    candidate_key = device_family_key(candidate)
    if selected_key == candidate_key:
        return True
    if min(len(selected_key), len(candidate_key)) >= 12 and (
        selected_key.startswith(candidate_key) or candidate_key.startswith(selected_key)
    ):
        return True
    bluetooth = ("headset" in selected_key or "airpod" in selected_key) and (
        "headset" in candidate_key or "airpod" in candidate_key
    )
    return bluetooth and (
        selected_key.startswith(candidate_key) or candidate_key.startswith(selected_key)
    )


def _windows_default_input_name(sounddevice) -> str:
    try:
        device = sounddevice.query_devices(kind="input")
    except Exception:
        try:
            index = sounddevice.default.device[0]
            device = sounddevice.query_devices(device=index, kind="input")
        except Exception:
            return ""
    return str(device.get("name") or "") if hasattr(device, "get") else ""


def _is_builtin_input(name: str) -> bool:
    key = device_family_key(name)
    return any(token in key for token in ("microphone array", "internal microphone", "realtek"))


def safe_input_candidates(sounddevice) -> list[str]:
    try:
        host_apis = sounddevice.query_hostapis()
        default_input_name = _windows_default_input_name(sounddevice)
        candidates: list[tuple[int, int, str]] = []
        for device in sounddevice.query_devices():
            if int(device.get("max_input_channels") or 0) <= 0:
                continue
            name = str(device.get("name") or "")
            if is_unsafe_microphone_name(name):
                continue
            host = host_api_name_from_device(host_apis, device)
            if host != "Windows WASAPI":
                continue
            selector = named_selector(device, host)
            if selector:
                builtin_priority = 0 if _is_builtin_input(name) else 1
                default_priority = 0 if (
                    default_input_name and same_physical_device_name(default_input_name, name)
                ) else 1
                # Follow a safe Windows default first, then prefer a built-in
                # endpoint as the deterministic fallback.
                candidates.append((default_priority, builtin_priority, selector))
        return [
            selector
            for *_priority, selector in sorted(
                candidates,
                key=lambda item: (*item[:2], item[2].casefold()),
            )
        ]
    except Exception:
        return []


def safe_default_input(sounddevice) -> str | None:
    candidates = safe_input_candidates(sounddevice)
    return candidates[0] if candidates else None
