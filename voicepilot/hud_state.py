"""Pure HUD presentation rules, independent from the Qt window and painter."""

from __future__ import annotations

from .hud_core import HudMessage


def display_title(message: HudMessage) -> str:
    title = message.title.strip()
    lowered = title.lower()
    if lowered == "live transcript":
        return "Transcribing"
    if lowered == "live instruction":
        return "Instruction"
    if lowered == "inserted":
        return "Done"
    return title


def status_label_for_kind(kind: str) -> str:
    return {
        "record": "Live",
        "rewrite": "Polish",
        "process": "Working",
        "preparing": "Preparing",
        "success": "Done",
        "warning": "Note",
        "error": "Error",
        "idle": "Ready",
    }.get(kind, kind.title())


def should_show_status_pill(message: HudMessage) -> bool:
    return message.kind in {"warning", "error"}


def should_restart_animation(previous: HudMessage, current: HudMessage, was_hidden: bool) -> bool:
    if was_hidden:
        return True
    if current.kind in {"success", "warning", "error"} and previous.kind != current.kind:
        return True
    return should_restart_timer(previous, current, was_hidden)


def should_restart_timer(previous: HudMessage, current: HudMessage, was_hidden: bool) -> bool:
    if was_hidden and is_timed_message(current):
        return True
    return is_timed_message(current) and not is_timed_message(previous)


def split_subtitle(message: HudMessage) -> tuple[str, str]:
    subtitle = message.subtitle.strip()
    if not subtitle:
        return "", ""
    if is_live_transcript_message(message):
        return transcript_meta(message.title), subtitle
    if message.kind in {"process", "rewrite"} and looks_like_transcript(message.title, subtitle):
        return transcript_meta(message.title), subtitle
    return subtitle, ""


def clean_hud_text(text: str) -> str:
    return (
        text.replace("local AI cleanup", "cleaning up")
        .replace("Local models", "Models")
        .replace("Ramble", "Dictation")
    )


def looks_like_transcript(title: str, subtitle: str) -> bool:
    if title.lower() in {"live transcript", "live instruction"}:
        return bool(subtitle.strip())
    if " - " in subtitle or " | " in subtitle:
        return len(subtitle) >= 72
    if len(subtitle) >= 42:
        return True
    return title.lower() in {"transcribing", "instruction"} and len(subtitle.split()) >= 3


def transcript_meta(title: str) -> str:
    return {
        "live transcript": "Live preview",
        "live instruction": "Heard instruction",
        "instruction": "Heard instruction",
        "transcribing": "Live preview",
    }.get(title.lower(), "Preview")


def is_live_transcript_message(message: HudMessage) -> bool:
    return message.title.lower() in {"live transcript", "live instruction"}


def is_listening_message(message: HudMessage) -> bool:
    title = message.title.lower()
    return (
        message.kind == "record"
        or title in {"polish mode", "rewrite instruction", "dictation locked", "polish listening", "rewrite listening", "listening locked"}
        or "release" in message.subtitle.lower()
        or "tap hotkey" in message.subtitle.lower()
    )


def should_use_compact_hud(message: HudMessage, mode: str) -> bool:
    """Compact mode never expands into the standard HUD."""

    return mode == "compact"


def should_hide_compact_hud(message: HudMessage, mode: str) -> bool:
    """Hide compact feedback after release; processing and paste stay quiet."""

    if mode != "compact":
        return False
    return not is_listening_message(message) and message.title.casefold() != "preparing winsper"


def is_timed_message(message: HudMessage) -> bool:
    return is_listening_message(message) or message.title.lower() in {
        "polishing text",
        "structuring prompt",
        "applying instruction",
    }


def format_elapsed(elapsed: float) -> str:
    seconds = max(0, int(elapsed))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}"
