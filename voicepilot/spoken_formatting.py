from __future__ import annotations

import os
import re
from pathlib import Path


_LAYOUT_TARGET = r"(?:(?:new|next)\s+(?:line|paragraph)|insert(?:\s+a)?\s+tab)"
_LAYOUT_PATTERN = re.compile(
    rf"(?P<literal>\btype\s+the\s+words?\s+(?P<literal_value>{_LAYOUT_TARGET})\b)"
    r"|(?P<paragraph>\b(?:new|next)\s+paragraph\b)[,.!?;:]?"
    r"|(?P<line>\b(?:new|next)\s+line\b)[,.!?;:]?"
    r"|(?P<tab>\binsert(?:\s+a)?\s+tab\b)[,.!?;:]?",
    re.IGNORECASE,
)

_TERMINAL_CD_PATTERN = re.compile(
    r"^\s*c\s*d(?:\s*(?:into|to|2|and\s+2))?\s+(?P<path>.+?)"
    r"(?:\s+please)?[.!]?\s*$",
    re.IGNORECASE,
)

_SPOKEN_WWW_URL = re.compile(
    r"\b(?P<prefix>www|w\s+w\s+w)\s+dot\s+"
    r"(?P<body>[a-z0-9]+(?:\s+(?:dot\s+)?[a-z0-9]+)*?)\s+dot\s+"
    r"(?P<tld>com|org|net|edu|gov|io|ai|co|in|dev|app|me|info|biz|xyz)\b",
    re.IGNORECASE,
)


def apply_spoken_layout(text: str, enabled: bool = True) -> str:
    """Convert explicit spoken layout commands without touching punctuation."""
    if not enabled or not text:
        return text

    def replace(match: re.Match[str]) -> str:
        literal = match.group("literal_value")
        if literal is not None:
            return literal
        if match.group("paragraph") is not None:
            return "\n\n"
        if match.group("line") is not None:
            return "\n"
        return "\t"

    formatted = _LAYOUT_PATTERN.sub(replace, text)
    formatted = re.sub(r"[ \t]*\n[ \t]*", "\n", formatted)
    formatted = re.sub(r" *\t *", "\t", formatted)
    return formatted


def normalize_spoken_terminal_command(text: str, *, home: str | Path | None = None) -> str:
    """Normalize an unambiguous spoken ``cd`` command using local user-folder context."""
    if re.search(r"\band\s+(?:run|execute)\b", text, flags=re.IGNORECASE):
        return text
    match = _TERMINAL_CD_PATTERN.fullmatch(text)
    if match is None:
        return text
    path = match.group("path").strip().strip('"')
    if not path or re.search(r"[;&|<>`]", path):
        return text
    common_folder = {
        "desktop": "Desktop",
        "documents": "Documents",
        "downloads": "Downloads",
        "music": "Music",
        "pictures": "Pictures",
        "videos": "Videos",
    }.get(path.casefold())
    if common_folder is not None:
        user_home = Path(home or os.environ.get("USERPROFILE") or Path.home())
        path = str(user_home / common_folder)
    rendered_path = f'"{path}"' if any(character.isspace() for character in path) else path
    return f"cd {rendered_path}"


def normalize_spoken_urls(text: str) -> str:
    """Normalize high-confidence spoken ``www dot … dot TLD`` sequences only."""
    def replace(match: re.Match[str]) -> str:
        labels = re.split(r"\s+dot\s+", match.group("body"), flags=re.IGNORECASE)
        normalized_labels = [re.sub(r"\s+", "", label) for label in labels]
        if not all(normalized_labels):
            return match.group(0)
        return ".".join(("www", *normalized_labels, match.group("tld").casefold()))

    return _SPOKEN_WWW_URL.sub(replace, text)
