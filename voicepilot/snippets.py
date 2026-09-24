from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from .config import Snippet


@dataclass(frozen=True)
class SnippetMatch:
    snippet: Snippet
    text: str
    mode: str = "command"


@dataclass(frozen=True)
class TriggerToken:
    word: str
    start: int
    end: int


def match_snippet(transcript: str, snippets: list[Snippet], profile_name: str | None = None) -> SnippetMatch | None:
    normalized = normalize_trigger(transcript)
    if not normalized:
        return None

    candidates: list[tuple[int, int, Snippet, str]] = []
    for snippet_index, snippet in enumerate(snippets):
        if not snippet.trigger or not snippet.text:
            continue
        if not profile_allows_snippet(snippet.profiles, profile_name):
            continue
        triggers = [snippet.trigger, *snippet.aliases]
        replacement = expand_snippet_text(snippet.text)
        normalized_triggers = [normalize_trigger(trigger) for trigger in triggers]
        for normalized_trigger in normalized_triggers:
            if triggers_match(normalized, normalized_trigger):
                candidates.append((len(normalized_trigger.split()), -snippet_index, snippet, replacement))
    if candidates:
        _length, _order, snippet, replacement = max(candidates, key=lambda item: (item[0], item[1]))
        return SnippetMatch(snippet=snippet, text=replacement, mode="command")

    for snippet in snippets:
        if not snippet.trigger or not snippet.text or not profile_allows_snippet(snippet.profiles, profile_name):
            continue
        replacement = expand_snippet_text(snippet.text)
        normalized_triggers = sorted(
            (normalize_trigger(trigger) for trigger in [snippet.trigger, *snippet.aliases]),
            key=lambda value: len(value.split()),
            reverse=True,
        )
        for normalized_trigger in normalized_triggers:
            span = find_inline_trigger_span(transcript, normalized_trigger)
            if span is not None:
                return SnippetMatch(snippet=snippet, text=replace_span(transcript, span, replacement), mode="inline")
    return None


def normalize_trigger(text: str) -> str:
    normalized = text.strip().lower()
    normalized = normalized.replace("e-mail", "email")
    normalized = re.sub(r"[^\w\s']", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    words = [normalize_trigger_word(word) for word in normalized.strip().split()]
    return " ".join(words)


def triggers_match(transcript: str, trigger: str) -> bool:
    if transcript == trigger:
        return True
    if not transcript or not trigger:
        return False
    command = strip_command_wrappers(transcript)
    if command == trigger:
        return True
    if len(command.split()) == len(trigger.split()) and max(len(command), len(trigger)) >= 10:
        return SequenceMatcher(None, command, trigger).ratio() >= 0.88
    return False


def strip_command_wrappers(text: str) -> str:
    words = text.split()
    changed = True
    while changed:
        changed = False
        for prefix in COMMAND_PREFIXES:
            if words[: len(prefix)] == prefix:
                words = words[len(prefix) :]
                changed = True
        for suffix in COMMAND_SUFFIXES:
            if words[-len(suffix) :] == suffix:
                words = words[: -len(suffix)]
                changed = True
    return " ".join(words)


def find_inline_trigger_span(text: str, normalized_trigger: str) -> tuple[int, int] | None:
    trigger_words = normalized_trigger.split()
    if not trigger_words:
        return None
    tokens = trigger_tokens(text)
    if len(trigger_words) > len(tokens):
        return None
    for index in range(0, len(tokens) - len(trigger_words) + 1):
        candidate = [token.word for token in tokens[index : index + len(trigger_words)]]
        if candidate == trigger_words:
            return tokens[index].start, tokens[index + len(trigger_words) - 1].end
    return None


def trigger_tokens(text: str) -> list[TriggerToken]:
    tokens: list[TriggerToken] = []
    for match in re.finditer(r"[\w']+", text.lower()):
        normalized = normalize_trigger_word(match.group(0))
        for word in normalized.split():
            tokens.append(TriggerToken(word=word, start=match.start(), end=match.end()))
    return tokens


def replace_span(text: str, span: tuple[int, int], replacement: str) -> str:
    start, end = span
    return text[:start] + replacement + text[end:]


def profile_allows_snippet(profiles: list[str], profile_name: str | None) -> bool:
    if not profiles:
        return True
    allowed = {profile.strip().lower() for profile in profiles if profile.strip()}
    if not allowed or allowed.intersection({"*", "all", "any", "general"}):
        return True
    return (profile_name or "").strip().lower() in allowed


def normalize_trigger_word(word: str) -> str:
    return TRIGGER_WORD_ALIASES.get(word, word)


def expand_snippet_text(text: str) -> str:
    now = datetime.now()
    replacements = {
        "{date}": now.strftime("%Y-%m-%d"),
        "{time}": now.strftime("%H:%M"),
        "{datetime}": now.strftime("%Y-%m-%d %H:%M"),
    }
    expanded = text
    for placeholder, value in replacements.items():
        expanded = expanded.replace(placeholder, value)
    return expanded


TRIGGER_WORD_ALIASES = {
    "email": "mail",
    "mailid": "mail id",
    "e-mail": "mail",
    "i'd": "id",
    "idea": "id",
}

COMMAND_PREFIXES = [
    ["please"],
    ["voicepilot"],
    ["hey", "voicepilot"],
    ["can", "you"],
    ["could", "you"],
    ["would", "you"],
]

COMMAND_SUFFIXES = [
    ["please"],
]
