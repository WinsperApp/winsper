from __future__ import annotations

import re

from .config import ProfileStyle
from .destination import DestinationContext
from .speech_languages import SPEECH_LANGUAGE_NAMES, mixed_language_mode


def polish_language_guidance(language: str) -> str:
    code = language.strip().casefold()
    mixed = mixed_language_mode(code)
    if mixed is not None:
        return (
            f"{mixed.label}. {mixed.script_instruction} Preserve every language segment and its writing system. "
            "Do not translate, monolingualize, or normalize code-switched speech into one language."
        )
    if not code:
        return "Auto-detect from RAW_DICTATION. Preserve its language and writing system; never translate it."
    label = SPEECH_LANGUAGE_NAMES.get(code, code)
    correction_guidance = (
        " If the speaker uses 'नहीं' to correct the immediately preceding statement, keep only the replacement "
        "that follows 'नहीं'."
        if code == "hi"
        else ""
    )
    return (
        f"{label}. Use {label} for ambiguous transcription, but preserve every already-present segment in its original "
        f"language and writing system. Never translate or erase code-switching.{correction_guidance}"
    )


def clean_model_output(value: str) -> str:
    output = value.strip()
    fenced = (
        re.fullmatch(r"```[^\n]*\n(?P<body>.*?)\n?```", output, flags=re.DOTALL)
        if output.count("```") == 2
        else None
    )
    if fenced is not None:
        output = fenced.group("body").strip()
    lowered = output.lower()
    for prefix in ("rewritten text:", "polished text:", "final text:"):
        if lowered.startswith(prefix):
            output = output[len(prefix):].lstrip()
            break
    return output


def prompt_block(label: str, value: str) -> str:
    end_marker = f"<<<END_{label}>>>"
    safe_value = re.sub(r"<<<(?P<marker>[A-Z][A-Z0-9_]*)>>>", r"< \g<marker> >", value)
    return f"<<<{label}>>>\n{safe_value}\n{end_marker}"


def polish_destination_example(_app_context: str) -> str:
    """Retained compatibility hook; prompts now use generic capability rules."""
    return ""


def destination_formatting_guidance(
    profile: ProfileStyle | None = None,
    app_label: str = "",
    destination: DestinationContext | None = None,
    *,
    mode: str = "cleanup",
) -> str:
    """Return destination rules shared by raw Polish and selected-text Rewrite."""
    destination_label = destination.app_label if destination is not None else ""
    context = f"{profile.label if profile is not None else ''} {app_label} {destination_label}".casefold()
    kind = destination.kind if destination is not None else legacy_destination_kind(context)
    language = (
        language_display_name(destination.language)
        if kind == "code" and destination is not None and destination.language
        else ""
    )
    if mode == "selection":
        if kind == "code":
            suffix = f" Use {language} when code is requested." if language else " Do not guess a language."
            return "When request edits or produces code, return editor-ready code and preserve required syntax and indentation." + suffix
        if kind == "terminal":
            return "When request asks for a shell command, return command text; otherwise treat selection as ordinary context."
        if kind == "email":
            return "Use email conventions only when request asks for email content; never add greeting, subject, or signoff on app name alone."
        if kind == "chat":
            return "When request asks for a message, keep it concise and sendable; preserve requested tone."
        if kind == "notes":
            return "Treat selection as note content; follow the request and preserve facts, ordering, checkboxes, and intentional line breaks."
        if kind == "docs":
            return "When request edits prose, use clear document structure only as requested."
        if kind == "spreadsheet":
            return "When request asks for cell content or a formula, return cell-ready output."
        if kind == "presentation":
            return "When request asks for slide content, use concise slide-ready output."
        return "Use app conventions only when they help answer the explicit request."

    if kind == "code":
        suffix = f" Use {language} for an explicit generation request." if language else " Never guess a language."
        return "Preserve source-code literals and indentation; generate code only when RAW_DICTATION explicitly requests it." + suffix
    if kind == "terminal":
        return "Return bare command text for an explicit shell action; preserve paths, flags, quotes, and line breaks."
    if kind == "email":
        return "Use readable email prose; add a subject, greeting, recipient, or signoff only when spoken."
    if kind == "prompt":
        return "Turn rough speech into a clear AI request while preserving its task, context, constraints, and desired output; never answer it."
    if kind == "chat":
        return "Keep wording concise, conversational, and sendable; preserve slang and formality."
    if kind == "notes":
        if any(app in context for app in ("obsidian", "logseq", "typora", "zettlr")):
            return "Use Markdown for explicitly requested formatting; otherwise keep notes compact, natural, and faithful."
        return "Keep notes compact and scannable; preserve intentional fragments, headings, checkboxes, ordering, and line breaks. Add structure only when spoken or clearly list-like."
    if kind == "docs":
        if "obsidian" in context:
            return "Use Markdown for explicitly requested formatting; otherwise keep natural document prose and structure."
        return "Use clear document prose; add structure only when spoken or clearly present."
    if kind == "spreadsheet":
        return "Keep output cell-ready and preserve formulas, values, tabs, and line breaks."
    if kind == "presentation":
        return "Use concise slide-ready phrasing; add bullets or headings only when spoken."
    return "Use natural insertion-ready prose and preserve explicit line breaks."


def legacy_destination_kind(context: str) -> str:
    """Map legacy profile/label calls to semantic kinds without affecting runtime contexts."""
    groups = (
        ("terminal", ("terminal", "powershell", "command prompt")),
        ("code", ("code-aware", "vs code", "cursor")),
        ("email", ("polished email", "email", "gmail", "outlook", "proton", "superhuman", "thunderbird")),
        ("prompt", ("prompt-aware", "chatgpt", "claude", "gemini", "perplexity", "copilot", "poe")),
        ("chat", ("chat concise", "slack", "teams", "discord", "whatsapp", "telegram", "signal", "zoom")),
        ("notes", ("notes", "notepad", "onenote", "notion", "obsidian", "evernote", "joplin", "simplenote", "logseq")),
        ("docs", ("docs polished", "document", "google docs", "notion", "onenote", "obsidian", "confluence", "word")),
        ("spreadsheet", ("excel", "google sheets", "spreadsheet")),
        ("presentation", ("powerpoint", "google slides", "presentation")),
    )
    return next((kind for kind, tokens in groups if any(token in context for token in tokens)), "general")


def language_display_name(language: str) -> str:
    return {
        "csharp": "C#",
        "cpp": "C++",
        "javascript": "JavaScript",
        "typescript": "TypeScript",
        "powershell": "PowerShell",
        "json": "JSON",
        "yaml": "YAML",
        "sql": "SQL",
        "html": "HTML",
        "css": "CSS",
        "toml": "TOML",
    }.get(language, language.title())


def dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for term in terms:
        key = term.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(term)
    return output
