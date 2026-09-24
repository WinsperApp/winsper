from __future__ import annotations

import pytest

from voicepilot.destination import format_email_layout, infer_destination


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Quarterly budget - Google Sheets", "spreadsheet"),
        ("Launch review - Google Slides", "presentation"),
    ],
)
def test_google_workspace_surface_beats_shared_docs_profile(title: str, expected: str) -> None:
    destination = infer_destination("chrome.exe", title, "docs", "Google Docs")

    assert destination.kind == expected


@pytest.mark.parametrize(
    ("process", "title", "profile", "label", "expected"),
    [
        ("WINWORD.EXE", "Email strategy.docx - Word", "email", "Word", "docs"),
        ("EXCEL.EXE", "Email campaign.xlsx - Excel", "email", "Excel", "spreadsheet"),
        ("POWERPNT.EXE", "Document plan - PowerPoint", "docs", "PowerPoint", "presentation"),
        ("OUTLOOK.EXE", "Quarterly document review", "docs", "Outlook", "email"),
        ("Code.exe", "outlook_email.py - Visual Studio Code", "email", "VS Code", "code"),
        ("WindowsTerminal.exe", "Team chat deployment", "chat", "Windows Terminal", "terminal"),
    ],
)
def test_native_app_identity_beats_conflicting_profile_or_title(
    process: str,
    title: str,
    profile: str,
    label: str,
    expected: str,
) -> None:
    assert infer_destination(process, title, profile, label).kind == expected


def test_profile_and_app_identity_beat_loose_window_title_tokens() -> None:
    assert infer_destination("chrome.exe", "Email strategy", "docs", "Google Docs").kind == "docs"
    assert infer_destination("chrome.exe", "Document review", "chat", "Slack").kind == "chat"


def test_window_title_remains_bounded_fallback_when_identity_is_unknown() -> None:
    assert infer_destination("unknown.exe", "Inbox - Gmail", "general", "Unknown app").kind == "email"
    assert infer_destination("chrome.exe", "Budget - Google Sheets", "general", "Chrome").kind == "spreadsheet"


@pytest.mark.parametrize(
    "text",
    [
        "This option works best today.",
        "Hi there is a problem.",
        "Thanks everyone for the quick response.",
    ],
)
def test_email_layout_leaves_ordinary_prose_unchanged(text: str) -> None:
    assert format_email_layout(text) == text


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Hi Avery,\nPlease send the report.", "Hi Avery,\n\nPlease send the report."),
        ("Please send the report.\nRegards,\nMorgan", "Please send the report.\n\nRegards,\nMorgan"),
        (
            "Hi Avery what is the status? Regards Morgan",
            "Hi Avery,\n\nwhat is the status?\n\nRegards,\nMorgan",
        ),
    ],
)
def test_email_layout_keeps_explicit_or_paired_layout_repairs(source: str, expected: str) -> None:
    assert format_email_layout(source) == expected
