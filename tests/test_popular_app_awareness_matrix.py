from __future__ import annotations

from dataclasses import dataclass

import pytest

from voicepilot.ai_coding_surfaces import NATIVE_AI_CODING_SURFACES, WEB_AI_CODING_SURFACES
from voicepilot.app_context import (
    BUILTIN_NATIVE_PROFILE_HINTS,
    AppContextDetector,
    BrowserPageContext,
    WindowInfo,
    browser_label_for_domain,
)
from voicepilot.config import AppConfig


@dataclass(frozen=True)
class WebSurface:
    name: str
    rule_pattern: str
    domain: str
    title: str
    profile: str
    destination: str


@dataclass(frozen=True)
class NativeSurface:
    name: str
    process: str
    title: str
    profile: str
    destination: str


WEB_SURFACES = (
    # Email
    WebSurface("gmail", "mail.google.com", "mail.google.com", "Inbox", "email", "email"),
    WebSurface("outlook-live", "outlook.live.com", "outlook.live.com", "Inbox", "email", "email"),
    WebSurface("outlook-365", "outlook.office.com", "outlook.office.com", "Inbox", "email", "email"),
    WebSurface("yahoo-mail", "mail.yahoo.com", "mail.yahoo.com", "Inbox", "email", "email"),
    WebSurface("proton", "proton.me", "proton.me", "Inbox", "email", "email"),
    WebSurface("protonmail", "protonmail.com", "protonmail.com", "Inbox", "email", "email"),
    WebSurface("superhuman", "superhuman.com", "superhuman.com", "Inbox", "email", "email"),
    # Documents and knowledge tools
    WebSurface("google-docs", "docs.google.com", "docs.google.com", "Project brief - Google Docs", "docs", "docs"),
    WebSurface("notion", "notion.so", "notion.so", "Project notes", "docs", "docs"),
    WebSurface("notion-site", "notion.site", "notion.site", "Published notes", "docs", "docs"),
    WebSurface("coda", "coda.io", "coda.io", "Project plan", "docs", "docs"),
    WebSurface("confluence", "confluence", "team.confluence.example", "Project wiki", "docs", "docs"),
    WebSurface("sharepoint", "sharepoint.com", "tenant.sharepoint.com", "Team site", "docs", "docs"),
    WebSurface("microsoft-365", "office.com", "office.com", "Document", "docs", "docs"),
    # AI prompt surfaces
    WebSurface("chatgpt", "chatgpt.com", "chatgpt.com", "New chat", "prompt", "prompt"),
    WebSurface("claude", "claude.ai", "claude.ai", "New chat", "prompt", "prompt"),
    WebSurface("gemini", "gemini.google.com", "gemini.google.com", "New chat", "prompt", "prompt"),
    WebSurface("perplexity", "perplexity.ai", "perplexity.ai", "New thread", "prompt", "prompt"),
    WebSurface("poe", "poe.com", "poe.com", "New chat", "prompt", "prompt"),
    WebSurface("copilot", "copilot.microsoft.com", "copilot.microsoft.com", "New chat", "prompt", "prompt"),
    # Code, development, and issue tracking
    WebSurface("github", "github.com", "github.com", "Pull request", "code", "code"),
    WebSurface("gitlab", "gitlab.com", "gitlab.com", "Merge request", "code", "code"),
    WebSurface("bitbucket", "bitbucket.org", "bitbucket.org", "Pull request", "code", "code"),
    WebSurface("stack-overflow", "stackoverflow.com", "stackoverflow.com", "Question", "code", "code"),
    WebSurface("linear", "linear.app", "linear.app", "Issue", "code", "code"),
    WebSurface("jira", "atlassian.net", "team.atlassian.net", "Issue", "code", "code"),
    WebSurface("vercel", "vercel.com", "vercel.com", "Deployment", "code", "code"),
    # Chat and conversational surfaces
    WebSurface("slack", "app.slack.com", "app.slack.com", "Project channel", "chat", "chat"),
    WebSurface("teams", "teams.microsoft.com", "teams.microsoft.com", "Project channel", "chat", "chat"),
    WebSurface("discord", "discord.com", "discord.com", "Project channel", "chat", "chat"),
    WebSurface("whatsapp", "web.whatsapp.com", "web.whatsapp.com", "Conversation", "chat", "chat"),
    WebSurface("telegram", "web.telegram.org", "web.telegram.org", "Conversation", "chat", "chat"),
    WebSurface("messenger", "messenger.com", "messenger.com", "Conversation", "chat", "chat"),
    WebSurface("youtube", "youtube.com", "youtube.com", "Comment", "chat", "chat"),
    WebSurface("youtu-be", "youtu.be", "youtu.be", "Comment", "chat", "chat"),
    # docs.google.com shares one profile rule; title identifies specialized surfaces.
    WebSurface(
        "google-sheets",
        "docs.google.com",
        "docs.google.com",
        "Quarterly budget - Google Sheets",
        "docs",
        "spreadsheet",
    ),
    WebSurface(
        "google-slides",
        "docs.google.com",
        "docs.google.com",
        "Launch review - Google Slides",
        "docs",
        "presentation",
    ),
    *(
        WebSurface(
            surface.id,
            surface.domain,
            surface.domain,
            surface.label,
            surface.profile,
            surface.destination,
        )
        for surface in WEB_AI_CODING_SURFACES
    ),
)


NATIVE_SURFACES = (
    # Email clients
    NativeSurface("outlook-classic", "outlook.exe", "Inbox", "email", "email"),
    NativeSurface("outlook-new", "olk.exe", "Inbox", "email", "email"),
    NativeSurface("thunderbird", "thunderbird.exe", "Inbox", "email", "email"),
    NativeSurface("em-client", "emclient.exe", "Inbox", "email", "email"),
    NativeSurface("mailspring", "mailspring.exe", "Inbox", "email", "email"),
    # Chat clients
    NativeSurface("slack", "slack.exe", "Project channel", "chat", "chat"),
    NativeSurface("teams", "teams.exe", "Project channel", "chat", "chat"),
    NativeSurface("new-teams", "ms-teams.exe", "Project channel", "chat", "chat"),
    NativeSurface("discord", "discord.exe", "Project channel", "chat", "chat"),
    NativeSurface("zoom", "zoom.exe", "Meeting chat", "chat", "chat"),
    NativeSurface("whatsapp", "whatsapp.exe", "Conversation", "chat", "chat"),
    NativeSurface("telegram", "telegram.exe", "Conversation", "chat", "chat"),
    NativeSurface("signal", "signal.exe", "Conversation", "chat", "chat"),
    # Document editors
    NativeSurface("word", "winword.exe", "Project brief", "docs", "docs"),
    NativeSurface("onenote", "onenote.exe", "Project notes", "notes", "notes"),
    NativeSurface("obsidian", "obsidian.exe", "Project notes", "notes", "notes"),
    NativeSurface("notion", "notion.exe", "Project notes", "notes", "notes"),
    NativeSurface("evernote", "evernote.exe", "Project notes", "notes", "notes"),
    NativeSurface("joplin", "joplin.exe", "Project notes", "notes", "notes"),
    NativeSurface("simplenote", "simplenote.exe", "Project notes", "notes", "notes"),
    NativeSurface("standard-notes", "standard-notes.exe", "Project notes", "notes", "notes"),
    NativeSurface("logseq", "logseq.exe", "Project notes", "notes", "notes"),
    NativeSurface("upnote", "upnote.exe", "Project notes", "notes", "notes"),
    NativeSurface("notesnook", "notesnook.exe", "Project notes", "notes", "notes"),
    NativeSurface("typora", "typora.exe", "Project notes", "notes", "notes"),
    NativeSurface("zettlr", "zettlr.exe", "Project notes", "notes", "notes"),
    NativeSurface("libreoffice", "libreoffice.exe", "Project brief", "docs", "docs"),
    NativeSurface("soffice", "soffice.bin", "Project brief", "docs", "docs"),
    # Code editors and IDEs
    NativeSurface("vs-code", "code.exe", "main.py", "code", "code"),
    NativeSurface("cursor", "cursor.exe", "main.py", "code", "code"),
    NativeSurface("windsurf", "windsurf.exe", "main.py", "code", "code"),
    NativeSurface("visual-studio", "devenv.exe", "Project", "code", "code"),
    NativeSurface("rider", "rider64.exe", "Project", "code", "code"),
    NativeSurface("pycharm", "pycharm64.exe", "main.py", "code", "code"),
    NativeSurface("intellij", "idea64.exe", "Main.java", "code", "code"),
    NativeSurface("webstorm", "webstorm64.exe", "main.ts", "code", "code"),
    NativeSurface("goland", "goland64.exe", "main.go", "code", "code"),
    NativeSurface("clion", "clion64.exe", "main.cpp", "code", "code"),
    NativeSurface("phpstorm", "phpstorm64.exe", "index.php", "code", "code"),
    NativeSurface("rubymine", "rubymine64.exe", "main.rb", "code", "code"),
    NativeSurface("android-studio", "android-studio.exe", "Main.kt", "code", "code"),
    NativeSurface("sublime", "sublime_text.exe", "main.py", "code", "code"),
    NativeSurface("notepad-plus-plus", "notepad++.exe", "main.py", "notes", "code"),
    # Terminals use code-aware writing profile but retain terminal output semantics.
    NativeSurface("windows-terminal", "windowsterminal.exe", "Shell", "code", "terminal"),
    NativeSurface("wt", "wt.exe", "Shell", "code", "terminal"),
    NativeSurface("powershell", "powershell.exe", "Shell", "code", "terminal"),
    NativeSurface("pwsh", "pwsh.exe", "Shell", "code", "terminal"),
    NativeSurface("cmd", "cmd.exe", "Shell", "code", "terminal"),
    NativeSurface("wezterm", "wezterm.exe", "Shell", "code", "terminal"),
    NativeSurface("alacritty", "alacritty.exe", "Shell", "code", "terminal"),
    # Specialized Office destinations currently inherit general writing profile.
    NativeSurface("excel", "excel.exe", "Quarterly budget", "general", "spreadsheet"),
    NativeSurface("powerpoint", "powerpnt.exe", "Launch review", "general", "presentation"),
    NativeSurface("notepad", "notepad.exe", "Untitled", "notes", "notes"),
    *(
        NativeSurface(surface.id, process, surface.label, surface.profile, surface.destination)
        for surface in NATIVE_AI_CODING_SURFACES
        for process in surface.processes
    ),
)


def _web_context(detector: AppContextDetector, case: WebSurface, hwnd: int = 1):
    label = browser_label_for_domain(case.domain)
    return detector._build_context(
        WindowInfo(hwnd, "chrome.exe", case.title),
        BrowserPageContext(case.domain, label),
    )


@pytest.mark.parametrize("case", WEB_SURFACES, ids=lambda case: case.name)
def test_configured_web_surface_profile_and_destination(case: WebSurface) -> None:
    context = _web_context(AppContextDetector(AppConfig()), case)

    assert context.profile_name == case.profile
    assert context.destination.kind == case.destination


@pytest.mark.parametrize("case", NATIVE_SURFACES, ids=lambda case: case.name)
def test_native_surface_profile_and_destination(case: NativeSurface) -> None:
    detector = AppContextDetector(AppConfig())
    context = detector.detect_fast(WindowInfo(1, case.process, case.title))

    assert context.profile_name == case.profile
    assert context.destination.kind == case.destination


def test_matrix_covers_every_configured_browser_rule() -> None:
    configured = {
        (rule.profile, pattern)
        for rule in AppConfig().browser_context.rules
        for pattern in rule.domains
    }
    covered = {(case.profile, case.rule_pattern) for case in WEB_SURFACES}

    assert configured <= covered


def test_matrix_covers_every_builtin_native_profile_hint() -> None:
    configured = {
        (profile, process.casefold())
        for profile, processes in BUILTIN_NATIVE_PROFILE_HINTS
        for process in processes
    }
    covered = {(case.profile, case.process.casefold()) for case in NATIVE_SURFACES}

    assert configured <= covered


@pytest.mark.parametrize(
    ("name", "native", "web", "expected"),
    (
        (
            "email",
            NativeSurface("outlook", "outlook.exe", "Inbox", "email", "email"),
            WebSurface("gmail", "mail.google.com", "mail.google.com", "Inbox", "email", "email"),
            "email",
        ),
        (
            "chat",
            NativeSurface("slack", "slack.exe", "Channel", "chat", "chat"),
            WebSurface("slack-web", "app.slack.com", "app.slack.com", "Channel", "chat", "chat"),
            "chat",
        ),
        (
            "docs",
            NativeSurface("word", "winword.exe", "Brief", "docs", "docs"),
            WebSurface("google-docs", "docs.google.com", "docs.google.com", "Brief - Google Docs", "docs", "docs"),
            "docs",
        ),
        (
            "code",
            NativeSurface("vs-code", "code.exe", "main.py", "code", "code"),
            WebSurface("github", "github.com", "github.com", "Pull request", "code", "code"),
            "code",
        ),
        (
            "spreadsheet",
            NativeSurface("excel", "excel.exe", "Budget", "general", "spreadsheet"),
            WebSurface(
                "google-sheets",
                "docs.google.com",
                "docs.google.com",
                "Budget - Google Sheets",
                "docs",
                "spreadsheet",
            ),
            "spreadsheet",
        ),
        (
            "presentation",
            NativeSurface("powerpoint", "powerpnt.exe", "Review", "general", "presentation"),
            WebSurface(
                "google-slides",
                "docs.google.com",
                "docs.google.com",
                "Review - Google Slides",
                "docs",
                "presentation",
            ),
            "presentation",
        ),
    ),
)
def test_native_and_web_apps_share_semantic_destination(
    name: str,
    native: NativeSurface,
    web: WebSurface,
    expected: str,
) -> None:
    detector = AppContextDetector(AppConfig())
    native_context = detector.detect_fast(WindowInfo(1, native.process, native.title))
    web_context = _web_context(detector, web, hwnd=2)

    assert {native_context.destination.kind, web_context.destination.kind} == {expected}, name


@pytest.mark.parametrize(
    ("domain", "title"),
    (
        ("google.com", "Search"),
        ("forms.example", "Customer feedback form"),
        ("support.example", "Support request"),
        ("intranet.example", "Status update"),
    ),
)
def test_unconfigured_browser_search_and_forms_stay_general(domain: str, title: str) -> None:
    context = AppContextDetector(AppConfig())._build_context(
        WindowInfo(1, "msedge.exe", title),
        BrowserPageContext(domain, domain),
    )

    assert context.profile_name == "general"
    assert context.destination.kind == "general"


@pytest.mark.parametrize(
    "domain",
    (
        "notgithub.com",
        "github.com.evil.example",
        "chatgpt.com.evil.example",
        "slack.com.evil.example",
        "docsgoogle.com",
        "notconfluence.example",
        "mail-google.com",
    ),
)
def test_domain_lookalikes_stay_general(domain: str) -> None:
    context = AppContextDetector(AppConfig())._build_context(
        WindowInfo(1, "chrome.exe", "Neutral page"),
        BrowserPageContext(domain, browser_label_for_domain(domain)),
    )

    assert context.profile_name == "general"
    assert context.destination.kind == "general"


@pytest.mark.parametrize(
    "process",
    (
        "mycode.exe",
        "notoutlook.exe",
        "fakeslack.exe",
        "excelviewer.exe",
        "powerpntviewer.exe",
        "notioncalendar.exe",
        "windowsterminalpreview.exe",
    ),
)
def test_process_lookalikes_stay_general(process: str) -> None:
    context = AppContextDetector(AppConfig()).detect_fast(WindowInfo(1, process, "Neutral page"))

    assert context.profile_name == "general"
    assert context.destination.kind == "general"


@pytest.mark.parametrize(
    ("process", "title", "expected_profile", "expected_destination"),
    (
        ("winword.exe", "Email strategy", "docs", "docs"),
        ("excel.exe", "Email campaign", "general", "spreadsheet"),
        ("powerpnt.exe", "Document plan", "general", "presentation"),
        ("outlook.exe", "Project documentation", "email", "email"),
        ("code.exe", "Outlook integration", "code", "code"),
        ("windowsterminal.exe", "Team chat deployment", "code", "terminal"),
        ("slack.exe", "Quarterly document", "chat", "chat"),
    ),
)
def test_native_identity_beats_title_collision(
    process: str,
    title: str,
    expected_profile: str,
    expected_destination: str,
) -> None:
    context = AppContextDetector(AppConfig()).detect_fast(WindowInfo(1, process, title))

    assert context.profile_name == expected_profile
    assert context.destination.kind == expected_destination


@pytest.mark.parametrize(
    ("domain", "title", "expected"),
    (
        ("mail.google.com", "Source code review", "email"),
        ("app.slack.com", "Quarterly document", "chat"),
        ("docs.google.com", "Email strategy - Google Docs", "docs"),
        ("github.com", "Gmail migration", "code"),
        ("chatgpt.com", "Draft email", "prompt"),
    ),
)
def test_verified_web_identity_beats_title_collision(domain: str, title: str, expected: str) -> None:
    context = AppContextDetector(AppConfig())._build_context(
        WindowInfo(1, "firefox.exe", title),
        BrowserPageContext(domain, browser_label_for_domain(domain)),
    )

    assert context.destination.kind == expected


@pytest.mark.parametrize(
    ("process", "title"),
    (
        ("notepad.exe", "Email strategy"),
        ("notepad.exe", "Team chat notes"),
        ("chrome.exe", "Email strategy"),
        ("firefox.exe", "Quarterly document"),
    ),
)
def test_generic_app_content_title_does_not_impersonate_a_surface(process: str, title: str) -> None:
    context = AppContextDetector(AppConfig()).detect_fast(WindowInfo(1, process, title))

    expected = "notes" if process == "notepad.exe" else "general"
    assert context.profile_name == expected
    assert context.destination.kind == expected


def test_notepad_plus_plus_plain_text_uses_notes_but_code_files_keep_code_destination() -> None:
    detector = AppContextDetector(AppConfig())

    plain = detector.detect_fast(WindowInfo(70, "notepad++.exe", "Meeting notes.txt"))
    code = detector.detect_fast(WindowInfo(71, "notepad++.exe", "main.py"))
    markdown = detector.detect_fast(WindowInfo(72, "notepad++.exe", "Daily notes.md"))

    assert plain.profile_name == "notes"
    assert plain.destination.kind == "notes"
    assert code.profile_name == "notes"
    assert code.destination.kind == "code"
    assert markdown.profile_name == "notes"
    assert markdown.destination.kind == "notes"
