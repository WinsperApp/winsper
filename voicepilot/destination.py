from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .ai_coding_surfaces import NATIVE_AI_PROCESS_DESTINATIONS


LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".json": "json",
    ".jsonc": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".mdx": "markdown",
    ".toml": "toml",
    ".sql": "sql",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".vue": "vue",
    ".svelte": "svelte",
    ".java": "java",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".dart": "dart",
    ".r": "r",
    ".lua": "lua",
}

LANGUAGE_ALIASES = {
    "python": "python",
    "javascript": "javascript",
    "java script": "javascript",
    "typescript": "typescript",
    "type script": "typescript",
    "json": "json",
    "toml": "toml",
    "yaml": "yaml",
    "yml": "yaml",
    "markdown": "markdown",
    "sql": "sql",
    "power shell": "powershell",
    "powershell": "powershell",
    "bash": "bash",
    "shell": "bash",
    "html": "html",
    "css": "css",
    "java": "java",
    "c sharp": "csharp",
    "c#": "csharp",
    "c plus plus": "cpp",
    "c++": "cpp",
    "go": "go",
    "rust": "rust",
    "ruby": "ruby",
    "php": "php",
    "swift": "swift",
    "kotlin": "kotlin",
    "dart": "dart",
    "r language": "r",
    "lua": "lua",
}

_CODE_PROCESSES = {
    "code.exe", "cursor.exe", "windsurf.exe", "devenv.exe", "rider64.exe",
    "pycharm64.exe", "idea64.exe", "webstorm64.exe", "goland64.exe", "clion64.exe",
    "phpstorm64.exe", "rubymine64.exe", "android-studio.exe", "sublime_text.exe",
}


def requested_code_file_extension(text: str) -> str:
    """Return standard extension when speech explicitly names language files."""
    for alias, language in sorted(LANGUAGE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if not re.search(rf"\b{re.escape(alias)}\s+files?\b", text, re.IGNORECASE):
            continue
        return next((extension for extension, mapped in LANGUAGE_BY_EXTENSION.items() if mapped == language), "")
    return ""
_TERMINAL_PROCESSES = {
    "windowsterminal.exe", "wt.exe", "powershell.exe", "pwsh.exe", "cmd.exe", "wezterm.exe", "alacritty.exe",
}
_EMAIL_PROCESSES = {"outlook.exe", "olk.exe", "thunderbird.exe", "emclient.exe", "mailspring.exe"}
_CHAT_PROCESSES = {
    "slack.exe", "teams.exe", "ms-teams.exe", "discord.exe", "zoom.exe", "whatsapp.exe", "telegram.exe", "signal.exe",
}
_NOTES_PROCESSES = {
    "notepad.exe", "notepad++.exe", "onenote.exe", "obsidian.exe", "notion.exe", "evernote.exe", "joplin.exe",
    "simplenote.exe", "standard-notes.exe", "logseq.exe", "upnote.exe", "notesnook.exe", "typora.exe", "zettlr.exe",
}
_DOCS_PROCESSES = {"winword.exe"}
_SPREADSHEET_PROCESSES = {"excel.exe"}
_PRESENTATION_PROCESSES = {"powerpnt.exe"}
_TITLE_FALLBACK_BROWSER_PROCESSES = {
    "arc.exe", "brave.exe", "chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "vivaldi.exe",
}
_TERMINAL_TOKENS = ("terminal", "powershell", "command prompt", "cmd.exe", "pwsh.exe", "wt.exe")
_EMAIL_TOKENS = ("email", "gmail", "outlook", "proton", "yahoo", "superhuman", "thunderbird", "mailspring")
_CHAT_TOKENS = ("chat", "slack", "teams", "discord", "whatsapp", "telegram", "signal", "zoom")
_NOTES_TOKENS = ("notes", "notepad", "onenote", "notion", "obsidian", "evernote", "joplin", "simplenote", "logseq")
_DOCS_TOKENS = ("document", "docs", "word", "onenote", "notion", "obsidian", "confluence", "coda", "sharepoint")
_PROMPT_TOKENS = ("prompt", "chatgpt", "claude", "gemini", "perplexity", "copilot", "poe")
_SPREADSHEET_TOKENS = ("excel", "google sheets", "spreadsheet", "sheets")
_PRESENTATION_TOKENS = ("powerpoint", "google slides", "presentation", "slides")


@dataclass(frozen=True)
class DestinationContext:
    kind: str = "general"
    app_label: str = ""
    language: str = ""
    language_source: str = ""

    @property
    def is_code(self) -> bool:
        return self.kind == "code"


def infer_destination(process_name: str, window_title: str, profile_name: str, app_label: str) -> DestinationContext:
    process = re.split(r"[\\/]", process_name.casefold())[-1]
    language = language_from_window_title(window_title)
    process_kind = _kind_from_process(process, language=language)
    if process_kind:
        return _destination(process_kind, app_label, language)

    profile_kind = _kind_from_identity(profile_name)
    app_kind = None if profile_kind is None and _looks_like_domain(app_label) else _kind_from_identity(app_label)
    specific_surface = _google_workspace_surface(f"{app_label} {window_title}")
    workspace_kinds = {None, "docs", "spreadsheet", "presentation"}
    if specific_surface and profile_kind in workspace_kinds and app_kind in workspace_kinds:
        return DestinationContext(specific_surface, app_label)

    identity_kind = profile_kind or app_kind
    if identity_kind:
        return _destination(identity_kind, app_label, language)

    if _title_fallback_allowed(process, app_label):
        title_kind = _kind_from_title(window_title)
        if title_kind:
            return _destination(title_kind, app_label, language)
    return DestinationContext("general", app_label)


def _destination(kind: str, app_label: str, language: str) -> DestinationContext:
    if kind in {"code", "terminal"}:
        return DestinationContext(kind, app_label, language, "title" if language else "")
    return DestinationContext(kind, app_label)


def _kind_from_process(process: str, *, language: str = "") -> str | None:
    ai_destination = NATIVE_AI_PROCESS_DESTINATIONS.get(process)
    if ai_destination is not None:
        return ai_destination
    if process == "notepad++.exe":
        return "code" if language and language != "markdown" else "notes"
    process_groups = (
        ("terminal", _TERMINAL_PROCESSES),
        ("code", _CODE_PROCESSES),
        ("spreadsheet", _SPREADSHEET_PROCESSES),
        ("presentation", _PRESENTATION_PROCESSES),
        ("email", _EMAIL_PROCESSES),
        ("chat", _CHAT_PROCESSES),
        ("notes", _NOTES_PROCESSES),
        ("docs", _DOCS_PROCESSES),
    )
    return next((kind for kind, processes in process_groups if process in processes), None)


def _kind_from_identity(value: str) -> str | None:
    categories = (
        ("terminal", _TERMINAL_TOKENS),
        ("code", ("code", "code-aware", "vs code", "visual studio code", "cursor", "windsurf")),
        ("spreadsheet", _SPREADSHEET_TOKENS),
        ("presentation", _PRESENTATION_TOKENS),
        ("email", _EMAIL_TOKENS),
        ("prompt", _PROMPT_TOKENS),
        ("chat", _CHAT_TOKENS),
        ("notes", _NOTES_TOKENS),
        ("docs", _DOCS_TOKENS),
    )
    folded = value.casefold()
    return next((kind for kind, tokens in categories if _contains_token(folded, tokens)), None)


def _contains_token(value: str, tokens: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(token)}(?!\w)", value) for token in tokens)


def _google_workspace_surface(value: str) -> str | None:
    folded = value.casefold()
    if _contains_token(folded, ("google sheets",)):
        return "spreadsheet"
    if _contains_token(folded, ("google slides",)):
        return "presentation"
    return None


def _looks_like_domain(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value.strip()))


def _title_fallback_allowed(process: str, app_label: str) -> bool:
    if app_label.strip().casefold() == "unknown app":
        return True
    return process in _TITLE_FALLBACK_BROWSER_PROCESSES and not _looks_like_domain(app_label)


def _kind_from_title(value: str) -> str | None:
    """Infer only explicit product surfaces from titles, never document-topic words."""
    specific_surface = _google_workspace_surface(value)
    if specific_surface:
        return specific_surface
    categories = (
        ("terminal", ("Windows Terminal", "PowerShell", "Command Prompt")),
        ("code", ("Visual Studio Code", "VS Code", "Cursor", "Windsurf")),
        ("email", ("Gmail", "Outlook", "Proton Mail", "Yahoo Mail", "Superhuman", "Thunderbird", "Mailspring")),
        ("prompt", ("ChatGPT", "Claude", "Gemini", "Perplexity", "Microsoft Copilot", "Poe")),
        ("chat", ("Slack", "Microsoft Teams", "Discord", "WhatsApp", "Telegram", "Signal")),
        ("notes", ("OneNote", "Notion", "Obsidian", "Evernote", "Joplin", "Simplenote", "Logseq")),
        ("docs", ("Google Docs", "Microsoft Word", "Confluence")),
        ("spreadsheet", ("Microsoft Excel",)),
        ("presentation", ("Microsoft PowerPoint", "PowerPoint")),
    )
    return next((kind for kind, tokens in categories if _contains_token(value.casefold(), tuple(token.casefold() for token in tokens))), None)


def language_from_window_title(window_title: str) -> str:
    for match in re.finditer(r"(?<![\w.])[^\\/\s|:]+(?P<extension>\.[A-Za-z0-9+#]+)\b", window_title):
        language = LANGUAGE_BY_EXTENSION.get(match.group("extension").casefold())
        if language:
            return language
    return ""


def extract_explicit_language(text: str, destination: DestinationContext) -> tuple[str, DestinationContext]:
    """Honor a leading 'in Python' only in a code destination."""
    if not destination.is_code:
        return text, destination
    aliases = "|".join(re.escape(alias) for alias in sorted(LANGUAGE_ALIASES, key=len, reverse=True))
    match = re.match(rf"^\s*(?:in|using|write\s+in)\s+(?P<language>{aliases})(?:\s*[:,\-]\s*|\s+)(?P<rest>.+)$", text, re.IGNORECASE)
    if not match:
        return text, destination
    language = LANGUAGE_ALIASES[match.group("language").casefold()]
    return match.group("rest").strip(), replace(destination, language=language, language_source="spoken")


def infer_language_from_selection(text: str, destination: DestinationContext) -> DestinationContext:
    """Use selected code only when editor title did not already identify a language."""
    if not destination.is_code or destination.language:
        return destination
    value = text.strip()
    if not value:
        return destination
    if _looks_like_json(value):
        return replace(destination, language="json", language_source="selection")
    patterns = (
        ("python", r"(?m)^\s*(?:def|class|import|from)\s+"),
        ("typescript", r"(?m)^\s*(?:interface|type|enum)\s+"),
        ("javascript", r"(?m)^\s*(?:const|let|var|function|export)\s+"),
        ("sql", r"(?is)^\s*(?:select|insert|update|delete|with)\b"),
        ("powershell", r"(?m)^\s*(?:Get|Set|New|Remove|Invoke)-[A-Za-z]+\b"),
        ("markdown", r"(?m)^\s*(?:#{1,6}\s|[-*+]\s|```)") ,
    )
    for language, pattern in patterns:
        if re.search(pattern, value):
            return replace(destination, language=language, language_source="selection")
    return destination


def apply_destination_postprocessing(text: str, destination: DestinationContext) -> str:
    """Apply only high-confidence layout repairs; never invent meaning."""
    text = normalize_destination_surface(text, destination)
    if destination.kind == "email":
        return format_email_layout(text)
    if destination.kind == "code" and destination.language == "python":
        return format_python_definition(text)
    if destination.kind == "terminal":
        return strip_terminal_preamble(text)
    return text


def normalize_destination_surface(text: str, destination: DestinationContext) -> str:
    """Remove model-only whitespace artifacts without changing prose structure."""
    if destination.kind not in {"email", "chat", "docs", "prompt", "spreadsheet", "presentation", "general"}:
        return text
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def _looks_like_json(value: str) -> bool:
    if not (value.startswith(("{", "[")) and value.endswith(("}", "]"))):
        return False
    try:
        import json

        json.loads(value)
    except (ValueError, TypeError):
        return False
    return True


def format_email_layout(text: str) -> str:
    value = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    if not value:
        return value

    closing = ""
    closing_match = re.search(
        r"(?is)(?P<body>.*?)(?P<before>\n+|[ \t]+)"
        r"(?P<closing>kind regards|best regards|many thanks|thank you|regards|thanks|sincerely|best)"
        r"(?P<comma>,)?(?P<after>[ \t]*\n+[ \t]*|[ \t]+)"
        r"(?P<name>[A-Za-z][A-Za-z'\-]{0,48})[.!]?\s*$",
        value,
    )
    if closing_match:
        paired_flat_greeting = bool(re.match(r"^\s*(?:Hi|Hello|Dear)\s+[A-Z][A-Za-z'\-]{0,48}\s+\S", value))
        closing_name = closing_match.group("closing").casefold()
        unambiguous_flat_closing = closing_name in {"kind regards", "best regards", "many thanks", "regards", "sincerely"}
        explicit_layout = bool(
            "\n" in closing_match.group("before")
            or closing_match.group("comma")
            or "\n" in closing_match.group("after")
        )
        if explicit_layout or (paired_flat_greeting and unambiguous_flat_closing):
            value = closing_match.group("body").strip()
            closing = f"{closing_match.group('closing').strip().capitalize()},\n{closing_match.group('name').strip()}"

    greeting = ""
    first_line, separator, remainder = value.partition("\n")
    greeting_match = re.match(
        r"^\s*(?P<salutation>hi|hello|dear)\s+(?P<recipient>[A-Za-z][A-Za-z'\-]{0,48})"
        r"(?P<comma>,)?(?P<tail>.*)$",
        first_line,
        re.IGNORECASE,
    )
    if greeting_match:
        candidate_remainder = greeting_match.group("tail").strip()
        explicit_greeting = bool(greeting_match.group("comma") or (separator and not candidate_remainder))
        if explicit_greeting or closing:
            greeting = f"{greeting_match.group('salutation').capitalize()} {greeting_match.group('recipient')},"
            value = f"{candidate_remainder}\n{remainder}".strip() if separator else candidate_remainder

    parts = [part.strip() for part in (greeting, value, closing) if part.strip()]
    return "\n\n".join(parts)


def format_python_definition(text: str) -> str:
    """Turn only an unambiguous spoken Python function header into syntax."""
    value = text.strip()
    match = re.fullmatch(
        r"def\s+(?P<name>[A-Za-z_]\w*)(?:\s*\((?P<arguments>[^()]*)\))?(?:\s+(?:takes|with)\s+(?P<spoken_arguments>[A-Za-z_][\w\s,]*(?:\s+and\s+[A-Za-z_]\w*)?))?\s*[:.]?",
        value,
        re.IGNORECASE,
    )
    if not match:
        return text
    arguments = (match.group("arguments") or match.group("spoken_arguments") or "").strip()
    if arguments:
        arguments = re.sub(r"\s+and\s+", ", ", arguments, flags=re.IGNORECASE)
        arguments = re.sub(r"\s*,\s*", ", ", arguments)
        if not all(re.fullmatch(r"[A-Za-z_]\w*", argument.strip()) for argument in arguments.split(",")):
            return text
    return f"def {match.group('name')}({arguments}):"


def strip_terminal_preamble(text: str) -> str:
    """Remove only obvious model labels; preserve command text and line breaks."""
    return re.sub(r"^\s*(?:command|powershell command|terminal command)\s*:\s*", "", text, flags=re.IGNORECASE)
