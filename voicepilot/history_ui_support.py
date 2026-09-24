from __future__ import annotations

from datetime import datetime

from .app_context import friendly_process_label
from .history import HistoryEvent


def history_count_text(match_count: int, total_count: int, max_items: int) -> str:
    if total_count <= 0:
        return "No transcripts"

    at_limit = total_count >= max(1, max_items)
    if match_count == total_count:
        if at_limit:
            return f"Latest {total_count} transcripts"
        noun = "transcript" if total_count == 1 else "transcripts"
        return f"{total_count} {noun}"

    if at_limit:
        noun = "match" if match_count == 1 else "matches"
        return f"{match_count} {noun} · Latest {total_count} stored"
    return f"{match_count} of {total_count} transcripts"


def history_visible_count_text(
    visible_count: int,
    match_count: int,
    total_count: int,
    max_items: int,
) -> str:
    visible_count = max(0, min(visible_count, match_count))
    if visible_count < match_count:
        noun = "transcript" if match_count == 1 else "transcripts"
        if match_count != total_count:
            noun = "match" if match_count == 1 else "matches"
        return f"Showing {visible_count} of {match_count} {noun}"
    return history_count_text(match_count, total_count, max_items)


def event_matches(event: HistoryEvent, query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        [
            event.mode,
            event.input_text,
            event.output_text,
            event.instruction,
            event.profile_name,
            event.profile_label,
            event.process_name,
            event.window_title,
            event.browser_domain,
            event.browser_label,
            event.snippet_name,
            event.snippet_trigger,
        ]
    ).lower()
    return query in haystack


def app_label(event: HistoryEvent) -> str:
    if event.browser_label and event.browser_domain and event.browser_label != event.browser_domain:
        return f"{event.browser_label} - {event.browser_domain}"
    if event.browser_domain:
        return event.browser_domain
    if event.process_name:
        return friendly_process_label(event.process_name, event.window_title)
    return "Unknown"


def mode_label(event: HistoryEvent) -> str:
    return {
        "ramble": "Dictate",
        "polish": "Polish",
        "rewrite": "Rewrite",
        "polish_selection": "Polish Selection",
        "snippet": "Snippet",
        "snippet_inline": "Snippet Inline",
    }.get(event.mode, event.mode.title() or "Entry")


def format_time(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.astimezone().strftime("%d %b, %H:%M")


def selected_text(text_edit) -> str:
    text = text_edit.textCursor().selectedText().replace("\u2029", "\n").strip()
    return text[:160]


def infer_correction_candidate(before: str, after: str) -> tuple[str, str] | None:
    import difflib
    import re

    before_tokens = re.findall(r"\S+", before)
    after_tokens = re.findall(r"\S+", after)
    if not before_tokens or not after_tokens:
        return None
    matcher = difflib.SequenceMatcher(a=before_tokens, b=after_tokens, autojunk=False)
    candidates: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        heard = clean_correction_phrase(" ".join(before_tokens[i1:i2]))
        replacement = clean_correction_phrase(" ".join(after_tokens[j1:j2]))
        if not heard or not replacement:
            continue
        if len(heard) > 80 or len(replacement) > 80:
            continue
        if len(heard.split()) > 6 or len(replacement.split()) > 6:
            continue
        candidates.append((heard, replacement))
    if len(candidates) != 1:
        return None
    heard, replacement = candidates[0]
    if heard.casefold() == replacement.casefold():
        return None
    return heard, replacement


def clean_correction_phrase(value: str) -> str:
    return value.strip().strip(".,;:!?\"'“”‘’()[]{}")
