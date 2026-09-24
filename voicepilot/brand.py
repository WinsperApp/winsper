from __future__ import annotations


BRAND_NAME = "Winsper"
BRAND_TAGLINE = "Private dictation everywhere"
APP_USER_MODEL_ID = "Winsper.LocalVoiceLayer"
STARTUP_SCRIPT_NAME = "Winsper.vbs"


def window_title(section: str = "") -> str:
    section = section.strip()
    return f"{BRAND_NAME} {section}" if section else BRAND_NAME


def is_brand_title(title: str) -> bool:
    normalized = title.casefold()
    return any(name in normalized for name in ("winsper", "voicepilot"))
