from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StarterTextShortcut:
    name: str
    trigger: str
    text: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class StarterCorrection:
    heard: str
    replacement: str


STARTER_TEXT_SHORTCUTS = (
    StarterTextShortcut("Today's date", "today's date", "{date}", ("today date",)),
    StarterTextShortcut("Current time", "current time", "{time}", ("the current time",)),
    StarterTextShortcut(
        "Date and time",
        "date and time",
        "{datetime}",
        ("current date and time", "today's date and time"),
    ),
)

STARTER_VOCABULARY = ("Winsper",)

STARTER_CORRECTIONS = (
    StarterCorrection("win spur", "Winsper"),
)


def starter_text_shortcut_dicts() -> list[dict[str, object]]:
    return [
        {
            "name": shortcut.name,
            "trigger": shortcut.trigger,
            "text": shortcut.text,
            "aliases": list(shortcut.aliases),
            "profiles": [],
        }
        for shortcut in STARTER_TEXT_SHORTCUTS
    ]
