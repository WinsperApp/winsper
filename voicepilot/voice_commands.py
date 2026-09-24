from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceCommand:
    kind: str
    label: str
    instruction: str
    action: str = ""


BULLET_PRESET_PHRASES = ("bullet", "bullets", "bullet points", "bullet list", "a bullet list")
SHORTER_PRESET_PHRASES = (
    "shorter",
    "more concise",
    "concise",
    "trim this",
    "trim it",
    "summarize this",
    "summarise this",
)
EXPAND_PRESET_PHRASES = ("expand this", "expand it", "more detailed", "add more detail", "elaborate")
CLEANUP_PRESET_PHRASES = (
    "fix grammar",
    "fix punctuation",
    "clean this up",
    "clean it up",
    "proofread",
    "remove filler",
)
PROFESSIONAL_PRESET_PHRASES = ("formal", "professional", "more polished", "polish this", "polish it")
FRIENDLY_PRESET_PHRASES = ("casual", "friendly", "warmer", "less formal", "more human")
CHAT_PRESET_PHRASES = ("slack", "teams message", "chat message")
EMAIL_PRESET_PHRASES = ("email", "mail format", "email format")
SIMPLIFY_PRESET_PHRASES = ("simplify", "simpler", "plain english", "plain language")
EDIT_PRESET_PHRASE_GROUPS = (
    BULLET_PRESET_PHRASES,
    SHORTER_PRESET_PHRASES,
    EXPAND_PRESET_PHRASES,
    CLEANUP_PRESET_PHRASES,
    PROFESSIONAL_PRESET_PHRASES,
    FRIENDLY_PRESET_PHRASES,
    CHAT_PRESET_PHRASES,
    EMAIL_PRESET_PHRASES,
    SIMPLIFY_PRESET_PHRASES,
)


def edit_command_hotwords() -> tuple[str, ...]:
    """Speech hints for registered selected-text edit commands."""
    phrases = (phrase for group in EDIT_PRESET_PHRASE_GROUPS for phrase in group)
    return tuple(dict.fromkeys(("replace last sentence", "translate to", *phrases)))


def parse_voice_command(
    spoken: str,
    edit_presets_enabled: bool = True,
    local_actions_enabled: bool = True,
) -> VoiceCommand:
    cleaned = normalize_command(spoken)
    if not cleaned:
        return VoiceCommand(kind="raw", label="Empty", instruction="")

    if local_actions_enabled:
        action = parse_local_action(cleaned)
        if action is not None:
            return action

    if edit_presets_enabled:
        preset = parse_edit_preset(spoken, cleaned)
        if preset is not None:
            return preset

    return VoiceCommand(kind="raw", label="Custom", instruction=spoken.strip())


def split_trailing_enter_action(text: str, phrase: str, enabled: bool = True) -> tuple[str, str]:
    cleaned_text = text.strip(" \t")
    if not enabled:
        return cleaned_text, ""
    trigger = normalize_action_phrase(phrase)
    if not trigger:
        return cleaned_text, ""
    tokens = word_spans(cleaned_text)
    if not tokens:
        return cleaned_text, ""
    effective_tokens = trim_trailing_action_suffixes(tokens)
    if not effective_tokens:
        return cleaned_text, ""
    for trigger_words in enter_action_triggers(trigger):
        if tokens_end_with(effective_tokens, trigger_words):
            start = effective_tokens[-len(trigger_words)][1]
            return cleaned_text[:start].rstrip(" \t"), "enter"
    return cleaned_text, ""


def normalize_action_phrase(text: str) -> str:
    normalized = text.strip().lower()
    normalized = re.sub(r"[^\w\s-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def word_spans(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0).lower(), match.start(), match.end()) for match in re.finditer(r"\b[\w-]+\b", text)]


def trim_trailing_action_suffixes(tokens: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    output = list(tokens)
    while output and output[-1][0] in {"please"}:
        output.pop()
    return output


def enter_action_triggers(trigger: str) -> list[list[str]]:
    base = trigger.split()
    triggers = [base]
    if base == ["press", "enter"]:
        triggers.extend(
            [
                ["press", "the", "enter"],
                ["press", "enter", "key"],
                ["press", "the", "enter", "key"],
                ["pressed", "enter"],
                ["hit", "enter"],
                ["hit", "the", "enter", "key"],
                ["tap", "enter"],
                ["tap", "the", "enter", "key"],
            ]
        )
    return sorted(dedupe_word_lists(triggers), key=len, reverse=True)


def tokens_end_with(tokens: list[tuple[str, int, int]], trigger_words: list[str]) -> bool:
    if not trigger_words or len(trigger_words) > len(tokens):
        return False
    return [token[0] for token in tokens[-len(trigger_words) :]] == trigger_words


def dedupe_word_lists(values: list[list[str]]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    output: list[list[str]] = []
    for value in values:
        key = tuple(value)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def parse_local_action(cleaned: str) -> VoiceCommand | None:
    if any(phrase in cleaned for phrase in ["undo last paste", "undo last dictation", "undo last insertion"]):
        return VoiceCommand(kind="action", label="Undo last paste", instruction="Undo the last paste.", action="undo_last")
    if cleaned in {"undo", "undo that", "undo it", "remove that", "remove last one"}:
        return VoiceCommand(kind="action", label="Undo last paste", instruction="Undo the last paste.", action="undo_last")

    if any(phrase in cleaned for phrase in ["copy last dictation", "copy last output", "copy last paste", "copy that"]):
        return VoiceCommand(kind="action", label="Copy last output", instruction="Copy the last inserted text.", action="copy_last")

    if cleaned in {"open history", "show history", "voicepilot history", "history"}:
        return VoiceCommand(kind="action", label="Open history", instruction="Open the local history window.", action="open_history")

    if cleaned in {"open settings", "show settings", "voicepilot settings", "settings"}:
        return VoiceCommand(kind="action", label="Open settings", instruction="Open Winsper settings.", action="open_settings")

    return None


def parse_edit_preset(spoken: str, cleaned: str) -> VoiceCommand | None:
    language = extract_translate_language(spoken)
    if language:
        return VoiceCommand(
            kind="edit",
            label=f"Translate to {language}",
            instruction=f"Translate the text to {language}. Preserve names, code identifiers, URLs, numbers, and formatting where possible.",
        )

    replacement = extract_last_sentence_replacement(spoken)
    if replacement:
        return VoiceCommand(
            kind="edit",
            label="Replace last sentence",
            instruction=f"Replace only the last sentence with this text, preserving the rest exactly: {replacement}",
        )

    if matches_standalone_preset(cleaned, BULLET_PRESET_PHRASES):
        return VoiceCommand(
            kind="edit",
            label="Bullets",
            instruction=(
                "Convert the text into a concise bullet list. Use the visible bullet character • for ordinary plain "
                "text; use Markdown list markers only when the destination is Markdown or code. Keep the original "
                "meaning and do not add new facts."
            ),
        )

    if matches_standalone_preset(
        cleaned,
        SHORTER_PRESET_PHRASES,
    ):
        return VoiceCommand(
            kind="edit",
            label="Shorter",
            instruction="Rewrite the text to be shorter and more concise while preserving the meaning and useful details.",
        )

    if matches_standalone_preset(cleaned, EXPAND_PRESET_PHRASES):
        return VoiceCommand(
            kind="edit",
            label="Expand",
            instruction="Expand the text with clearer detail while staying faithful to the original meaning. Do not invent facts.",
        )

    if matches_standalone_preset(
        cleaned,
        CLEANUP_PRESET_PHRASES,
    ):
        return VoiceCommand(
            kind="edit",
            label="Clean up",
            instruction="Fix grammar, punctuation, capitalization, spacing, filler words, and obvious speech artifacts. Preserve meaning and tone.",
        )

    if matches_standalone_preset(cleaned, PROFESSIONAL_PRESET_PHRASES):
        return VoiceCommand(
            kind="edit",
            label="Professional",
            instruction="Rewrite the text in a polished professional tone. Keep it clear, direct, and faithful to the original meaning.",
        )

    if matches_standalone_preset(cleaned, FRIENDLY_PRESET_PHRASES):
        return VoiceCommand(
            kind="edit",
            label="Friendly",
            instruction="Rewrite the text in a friendly, natural, conversational tone without changing the meaning.",
        )

    if matches_standalone_preset(cleaned, CHAT_PRESET_PHRASES):
        return VoiceCommand(
            kind="edit",
            label="Chat message",
            instruction="Rewrite the text as a concise chat message. Make it easy to scan and natural for Slack or Teams.",
        )

    if matches_standalone_preset(cleaned, EMAIL_PRESET_PHRASES):
        return VoiceCommand(
            kind="edit",
            label="Email",
            instruction="Rewrite the text as a clear email. Add a suitable greeting or sign-off only if the original text implies one.",
        )

    if matches_standalone_preset(cleaned, SIMPLIFY_PRESET_PHRASES):
        return VoiceCommand(
            kind="edit",
            label="Simplify",
            instruction="Rewrite the text in plain, simple language while preserving the original meaning.",
        )

    return None


def normalize_command(text: str) -> str:
    normalized = text.strip().lower()
    normalized = normalized.replace("voice pilot", "voicepilot")
    normalized = re.sub(r"[^\w\s-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    words = normalized.strip().split()
    words = strip_wrappers(words)
    return " ".join(words)


def strip_wrappers(words: list[str]) -> list[str]:
    changed = True
    while changed:
        changed = False
        for prefix in COMMAND_PREFIXES:
            if words[: len(prefix)] == prefix:
                words = words[len(prefix) :]
                changed = True
        for target in TARGET_WORDS:
            if words[:1] == [target]:
                words = words[1:]
                changed = True
        for suffix in COMMAND_SUFFIXES:
            if words[-len(suffix) :] == suffix:
                words = words[: -len(suffix)]
                changed = True
    return words


def matches_standalone_preset(text: str, phrases: list[str]) -> bool:
    """Match a complete preset command, never one clause inside a custom instruction."""
    return text in phrases


def extract_translate_language(text: str) -> str:
    if re.search(r"[,;:]", text):
        return ""
    normalized = normalize_command(text)
    patterns = [
        r"translate(?:\s+(?:this|that|it|text))?\s+to\s+([a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,3})",
        r"in\s+([a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,3})\s+translate",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        language = clean_language(match.group(1))
        if language and not looks_like_compound_translation_target(language):
            return language
    return ""


def clean_language(value: str) -> str:
    language = value.strip()
    words = language.split()
    if len(words) > 4:
        language = " ".join(words[:4])
    return language.title() if language else ""


def looks_like_compound_translation_target(value: str) -> bool:
    """Reject targets that contain another instruction clause instead of a language."""
    words = value.casefold().split()
    if any(word in TRANSLATION_CLAUSE_CONNECTORS for word in words):
        return True
    return any(word in TRANSLATION_ACTION_WORDS for word in words[1:])


def extract_last_sentence_replacement(text: str) -> str:
    patterns = [
        r"^(?:please\s+|(?:can|could|would)\s+you\s+)?replace(?:\s+(?:the\s+)?)last sentence(?:\s+with)?\s+(.+)$",
        r"^(?:please\s+|(?:can|could|would)\s+you\s+)?change(?:\s+(?:the\s+)?)last sentence(?:\s+to)?\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.strip(), flags=re.IGNORECASE)
        if not match:
            continue
        replacement = match.group(1).strip(" .")
        if replacement:
            return replacement
    return ""


COMMAND_PREFIXES = [
    ["please"],
    ["can", "you"],
    ["could", "you"],
    ["would", "you"],
    ["winsper"],
    ["hey", "winsper"],
    ["voicepilot"],
    ["hey", "voicepilot"],
    ["make", "this"],
    ["make", "that"],
    ["make", "it"],
    ["make", "these"],
    ["make", "those"],
    ["turn", "this", "into"],
    ["turn", "that", "into"],
    ["turn", "it", "into"],
    ["turn", "these", "into"],
    ["turn", "those", "into"],
    ["convert", "this", "to"],
    ["convert", "that", "to"],
    ["convert", "it", "to"],
    ["convert", "these", "to"],
    ["convert", "those", "to"],
    ["convert", "this", "into"],
    ["convert", "that", "into"],
    ["convert", "it", "into"],
    ["convert", "these", "into"],
    ["convert", "those", "into"],
]

COMMAND_SUFFIXES = [
    ["please"],
    ["for", "me"],
]

TARGET_WORDS = ["this", "that", "it", "these", "those", "text"]

TRANSLATION_CLAUSE_CONNECTORS = frozenset({"also", "and", "but", "or", "plus", "then", "while"})
TRANSLATION_ACTION_WORDS = frozenset(
    {
        "add",
        "answer",
        "change",
        "convert",
        "delete",
        "expand",
        "explain",
        "extract",
        "fix",
        "format",
        "identify",
        "keep",
        "list",
        "make",
        "polish",
        "preserve",
        "remove",
        "rewrite",
        "shorten",
        "simplify",
        "summarise",
        "summarize",
        "turn",
    }
)
