from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ProfileStyle


WRITING_STYLE_CHOICES: tuple[tuple[str, str], ...] = (
    ("Natural", "natural"),
    ("Concise", "concise"),
    ("Professional", "professional"),
    ("Custom", "custom"),
)

WRITING_STYLE_DESCRIPTIONS = {
    "natural": "Keeps your voice while adapting to the app you are using.",
    "concise": "Tightens wording and removes repetition without losing meaning.",
    "professional": "Sounds polished and clear without becoming stiff or robotic.",
    "custom": "Follows one writing preference you define across Winsper.",
}

_PRESET_INSTRUCTIONS = {
    "concise": "Prefer concise wording. Remove repetition and unnecessary filler without dropping meaning.",
    "professional": "Use clear, polished professional wording without sounding formal, stiff, or robotic.",
}


def normalize_writing_style(value: object) -> str:
    normalized = str(value or "").strip().lower()
    valid = {key for _label, key in WRITING_STYLE_CHOICES}
    return normalized if normalized in valid else "natural"


def clean_custom_instruction(value: object) -> str:
    return " ".join(str(value or "").split())[:500]


def writing_style_instruction(preset: object, custom_instruction: object = "") -> str:
    normalized = normalize_writing_style(preset)
    if normalized == "custom":
        return clean_custom_instruction(custom_instruction)
    return _PRESET_INSTRUCTIONS.get(normalized, "")


def apply_writing_style(
    profile: ProfileStyle,
    preset: object,
    custom_instruction: object = "",
) -> ProfileStyle:
    """Layer one global preference onto an app-aware profile.

    Explicit selected-text instructions remain authoritative; this preference is
    only a default when it does not conflict with what the user asked for.
    """
    instruction = writing_style_instruction(preset, custom_instruction)
    if not instruction:
        return profile

    from .config import ProfileStyle

    preference = (
        "Default writing preference (follow only when compatible with the user's "
        f"explicit request): {instruction}"
    )
    return ProfileStyle(
        label=profile.label,
        dictation_prompt=_append_once(profile.dictation_prompt, preference),
        rewrite_prompt=_append_once(profile.rewrite_prompt, preference),
        vocabulary=list(profile.vocabulary),
    )


def _append_once(base: str, addition: str) -> str:
    clean_base = base.strip()
    if addition in clean_base:
        return clean_base
    return " ".join(part for part in (clean_base, addition) if part)
