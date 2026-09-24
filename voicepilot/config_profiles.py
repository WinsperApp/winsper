"""Built-in browser and application profile defaults.

These defaults are data, not configuration parsing. Keeping them separate makes
the configuration schema and loader easier to review without changing the
public helpers exposed by :mod:`voicepilot.config`.
"""

from .ai_coding_surfaces import web_ai_domains
from .config import BrowserRule, BrowserSiteStyle, ProfileRule, ProfileStyle, ProfilesConfig


def default_browser_processes() -> list[str]:
    return [
        "arc.exe",
        "avastbrowser.exe",
        "avgbrowser.exe",
        "brave.exe",
        "browser.exe",
        "ccleanerbrowser.exe",
        "chrome.exe",
        "chromium.exe",
        "coc_coc_browser.exe",
        "dragon.exe",
        "duckduckgo.exe",
        "epic.exe",
        "firefox.exe",
        "floorp.exe",
        "iexplore.exe",
        "iridium.exe",
        "librewolf.exe",
        "maxthon.exe",
        "msedge.exe",
        "opera.exe",
        "opera_gx.exe",
        "palemoon.exe",
        "qqbrowser.exe",
        "seamonkey.exe",
        "sidekick.exe",
        "thorium.exe",
        "vivaldi.exe",
        "waterfox.exe",
        "wavebox.exe",
        "whale.exe",
        "yandex.exe",
        "zen.exe",
    ]


def default_browser_rules() -> list[BrowserRule]:
    return [
        BrowserRule(
            profile="email",
            domains=[
                "mail.google.com",
                "outlook.live.com",
                "outlook.office.com",
                "mail.yahoo.com",
                "proton.me",
                "protonmail.com",
                "superhuman.com",
            ],
        ),
        BrowserRule(
            profile="docs",
            domains=[
                "docs.google.com",
                "notion.so",
                "notion.site",
                "coda.io",
                "confluence",
                "sharepoint.com",
                "office.com",
            ],
        ),
        BrowserRule(
            profile="prompt",
            domains=[
                "chatgpt.com",
                "claude.ai",
                "gemini.google.com",
                "perplexity.ai",
                "poe.com",
                "copilot.microsoft.com",
                *web_ai_domains("prompt"),
            ],
        ),
        BrowserRule(
            profile="code",
            domains=[
                "github.com",
                "gitlab.com",
                "bitbucket.org",
                "stackoverflow.com",
                "linear.app",
                "atlassian.net",
                "vercel.com",
                *web_ai_domains("code"),
            ],
        ),
        BrowserRule(
            profile="chat",
            domains=[
                "app.slack.com",
                "teams.microsoft.com",
                "discord.com",
                "web.whatsapp.com",
                "web.telegram.org",
                "messenger.com",
                "youtube.com",
                "youtu.be",
            ],
        ),
    ]


def default_browser_site_styles() -> list[BrowserSiteStyle]:
    return [
        BrowserSiteStyle(
            domains=[
                "mail.google.com",
                "outlook.live.com",
                "outlook.office.com",
                "mail.yahoo.com",
                "proton.me",
                "protonmail.com",
                "superhuman.com",
            ],
            label="Email draft",
            dictation_prompt=(
                "Clean this as an email draft. Prefer complete sentences, clear asks, and a warm direct tone. "
                "Do not add a greeting or signoff unless the user dictated one."
            ),
            rewrite_prompt=(
                "Rewrite as a clear email message with a direct, useful tone. "
                "Keep the user's intent and avoid sounding overly formal."
            ),
        ),
        BrowserSiteStyle(
            domains=[
                "chatgpt.com",
                "claude.ai",
                "gemini.google.com",
                "perplexity.ai",
                "poe.com",
                "copilot.microsoft.com",
                *web_ai_domains("prompt"),
            ],
            label="AI prompt",
            dictation_prompt=(
                "Turn rough dictation into a strong AI-assistant prompt. Preserve task, context, constraints, "
                "desired output, examples, filenames, code identifiers, and quoted text. Do not answer the prompt."
            ),
            rewrite_prompt=(
                "Rewrite as a precise AI-assistant prompt with task, context, constraints, and desired output. "
                "Keep the user's intent and do not add unsupported requirements."
            ),
        ),
        BrowserSiteStyle(
            domains=[
                "github.com",
                "gitlab.com",
                "bitbucket.org",
                "stackoverflow.com",
                "linear.app",
                "atlassian.net",
                "vercel.com",
                *web_ai_domains("code"),
            ],
            label="Technical work",
            dictation_prompt=(
                "Preserve issue IDs, code identifiers, branch names, file paths, CLI flags, and error messages. "
                "Use concise technical phrasing."
            ),
            rewrite_prompt=(
                "Rewrite for technical work. Preserve identifiers exactly, keep concrete steps or acceptance criteria, "
                "and prefer bullets when the content is task-like."
            ),
            vocabulary=["PR", "API", "CLI", "JSON", "YAML", "HTTP", "SDK", "bug", "issue"],
        ),
        BrowserSiteStyle(
            domains=[
                "app.slack.com",
                "teams.microsoft.com",
                "discord.com",
                "web.whatsapp.com",
                "web.telegram.org",
                "messenger.com",
                "youtube.com",
                "youtu.be",
            ],
            label="Chat reply",
            dictation_prompt=(
                "Make this concise, conversational, and easy to send as a chat reply. Avoid unnecessary formality."
            ),
            rewrite_prompt="Rewrite as a short, friendly chat message. Keep it natural and easy to scan.",
        ),
        BrowserSiteStyle(
            domains=[
                "docs.google.com",
                "notion.so",
                "notion.site",
                "coda.io",
                "confluence",
                "sharepoint.com",
                "office.com",
            ],
            label="Document prose",
            dictation_prompt=(
                "Clean this into structured prose suitable for notes or documentation. "
                "Use bullets only when they improve readability."
            ),
            rewrite_prompt=(
                "Rewrite as clear documentation or notes. Improve structure without adding unsupported details."
            ),
        ),
    ]


def default_profiles_config() -> ProfilesConfig:
    return ProfilesConfig(
        enabled=True,
        default_profile="general",
        rules=[
            ProfileRule(
                profile="code",
                processes=["Code.exe", "Cursor.exe", "WindowsTerminal.exe", "wt.exe", "python.exe"],
            ),
            ProfileRule(profile="chat", processes=["Slack.exe", "Teams.exe", "Discord.exe"]),
            ProfileRule(profile="email", processes=["OUTLOOK.EXE"], title_contains=["Gmail", "Outlook", "Mail"]),
            ProfileRule(profile="prompt", title_contains=["ChatGPT", "Claude", "Gemini", "Perplexity"]),
            ProfileRule(
                profile="notes",
                processes=[
                    "notepad.exe", "notepad++.exe", "onenote.exe", "obsidian.exe", "notion.exe",
                    "evernote.exe", "joplin.exe", "simplenote.exe", "standard-notes.exe", "logseq.exe",
                    "upnote.exe", "notesnook.exe", "typora.exe", "zettlr.exe",
                ],
            ),
            ProfileRule(profile="docs", title_contains=["Google Docs", "Notion", "Word"]),
        ],
        styles={
            "general": ProfileStyle(
                label="General",
                dictation_prompt="Clean spoken text into natural writing with punctuation.",
                rewrite_prompt="Keep the rewrite natural, clear, and faithful to the user's intent.",
            ),
            "chat": ProfileStyle(
                label="Chat concise",
                dictation_prompt="Prefer concise conversational phrasing suitable for chat messages.",
                rewrite_prompt="Keep the response short, friendly, and easy to scan.",
            ),
            "email": ProfileStyle(
                label="Polished email",
                dictation_prompt="Prefer complete sentences and a polished professional email tone.",
                rewrite_prompt="Use a polished but direct professional tone suitable for email.",
            ),
            "code": ProfileStyle(
                label="Code-aware",
                dictation_prompt=(
                    "Preserve code identifiers, file names, CLI flags, and technical terms exactly when possible."
                ),
                rewrite_prompt=(
                    "Preserve code identifiers, file paths, API names, and technical terms. "
                    "Avoid smart quotes around code."
                ),
                vocabulary=["API", "CLI", "JSON", "YAML", "PowerShell", "VS Code", "Cursor"],
            ),
            "prompt": ProfileStyle(
                label="Prompt-aware",
                dictation_prompt=(
                    "Transform rough speech into a direct AI-assistant prompt. Preserve constraints, examples, "
                    "desired output, filenames, code identifiers, and quoted text. Do not answer the prompt."
                ),
                rewrite_prompt=(
                    "Make the text a precise AI-assistant prompt with task, context, constraints, and desired output. "
                    "Do not invent missing requirements."
                ),
            ),
            "notes": ProfileStyle(
                label="Notes",
                dictation_prompt=(
                    "Clean spoken notes into compact, scannable text. Preserve intentional fragments, headings, "
                    "checklists, ordering, and line breaks. Add structure only when spoken or clearly list-like; "
                    "never invent tasks, dates, or details."
                ),
                rewrite_prompt=(
                    "Follow the requested edit while preserving note structure, facts, unfinished thoughts, "
                    "checkboxes, ordering, and intentional line breaks. Do not add unsupported details."
                ),
            ),
            "docs": ProfileStyle(
                label="Docs polished",
                dictation_prompt="Prefer structured prose suitable for notes or documentation.",
                rewrite_prompt="Make the text structured, clear, and documentation-friendly.",
            ),
        },
    )
