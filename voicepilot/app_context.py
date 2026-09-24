from __future__ import annotations

import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .ai_coding_surfaces import NATIVE_AI_PROCESS_LABELS, WEB_AI_CODING_SURFACES
from .ai_coding_surfaces import native_ai_profile_hints, web_ai_surface_for_domain
from .config import AppConfig, BrowserContextConfig, BrowserSiteStyle, ProfileStyle, WritingStyleConfig
from .brand import BRAND_NAME, is_brand_title, window_title
from .writing_style import apply_writing_style

BROWSER_SITE_LABELS = [
    ("mail.google.com", "Gmail"),
    ("outlook.live.com", "Outlook"),
    ("outlook.office.com", "Outlook"),
    ("proton.me", "Proton Mail"),
    ("protonmail.com", "Proton Mail"),
    ("mail.yahoo.com", "Yahoo Mail"),
    ("superhuman.com", "Superhuman"),
    ("docs.google.com", "Google Docs"),
    ("notion.so", "Notion"),
    ("notion.site", "Notion"),
    ("coda.io", "Coda"),
    ("confluence", "Confluence"),
    ("sharepoint.com", "SharePoint"),
    ("office.com", "Microsoft 365"),
    ("chatgpt.com", "ChatGPT"),
    ("claude.ai", "Claude"),
    ("gemini.google.com", "Gemini"),
    ("perplexity.ai", "Perplexity"),
    ("poe.com", "Poe"),
    ("copilot.microsoft.com", "Copilot"),
    ("github.com", "GitHub"),
    ("gitlab.com", "GitLab"),
    ("bitbucket.org", "Bitbucket"),
    ("stackoverflow.com", "Stack Overflow"),
    ("linear.app", "Linear"),
    ("atlassian.net", "Jira"),
    ("app.slack.com", "Slack"),
    ("teams.microsoft.com", "Teams"),
    ("discord.com", "Discord"),
    ("web.whatsapp.com", "WhatsApp"),
    ("web.telegram.org", "Telegram"),
    ("youtube.com", "YouTube"),
    ("youtu.be", "YouTube"),
    *((surface.domain, surface.label) for surface in WEB_AI_CODING_SURFACES),
]
BUILTIN_NATIVE_PROFILE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("code", (
        "code.exe", "cursor.exe", "windsurf.exe", "devenv.exe", "rider64.exe", "pycharm64.exe", "idea64.exe",
        "webstorm64.exe", "sublime_text.exe", "goland64.exe", "clion64.exe", "phpstorm64.exe", "rubymine64.exe",
        "android-studio.exe", "windowsterminal.exe", "wt.exe", "powershell.exe", "pwsh.exe", "cmd.exe",
        "wezterm.exe", "alacritty.exe",
    )),
    ("email", ("outlook.exe", "olk.exe", "thunderbird.exe", "emclient.exe", "mailspring.exe")),
    ("chat", ("slack.exe", "teams.exe", "ms-teams.exe", "discord.exe", "zoom.exe", "whatsapp.exe", "telegram.exe", "signal.exe")),
    ("notes", ("notepad.exe", "notepad++.exe", "onenote.exe", "obsidian.exe", "notion.exe", "evernote.exe", "joplin.exe",
               "simplenote.exe", "standard-notes.exe", "logseq.exe", "upnote.exe", "notesnook.exe", "typora.exe", "zettlr.exe")),
    ("docs", ("winword.exe", "libreoffice.exe", "soffice.bin")),
    *native_ai_profile_hints(),
)

ADDRESS_BAR_AUTOMATION_IDS = ["addressEditBox", "urlbar-input", "urlbar", "omnibox"]

ADDRESS_BAR_NAMES = [
    "Address and search bar", "Address bar", "Search or enter web address",
    "Search Google or type a URL", "Search or type web address", "Location",
]

FRIENDLY_PROCESS_LABELS = {
    "applicationframehost.exe": "Windows app",
    "brave.exe": "Brave",
    "chrome.exe": "Chrome",
    "code.exe": "VS Code",
    "cursor.exe": "Cursor",
    "discord.exe": "Discord",
    "duckduckgo.exe": "DuckDuckGo",
    "excel.exe": "Excel",
    "firefox.exe": "Firefox",
    "msedge.exe": "Edge",
    "notepad.exe": "Notepad",
    "notepad++.exe": "Notepad++",
    "notion.exe": "Notion",
    "obsidian.exe": "Obsidian",
    "olk.exe": "Outlook",
    "onenote.exe": "OneNote",
    "opera.exe": "Opera",
    "outlook.exe": "Outlook",
    "powerpnt.exe": "PowerPoint",
    "slack.exe": "Slack",
    "teams.exe": "Teams",
    "winword.exe": "Word",
    "windowsterminal.exe": "Windows Terminal",
    "wt.exe": "Windows Terminal",
    **NATIVE_AI_PROCESS_LABELS,
}

WINSPER_PROCESSES = {"python.exe", "pythonw.exe", "voicepilot.exe", "winsper.exe"}
_BROWSER_LOOKUP_LOCK = threading.Lock()
_BROWSER_LOOKUP_THREAD: threading.Thread | None = None


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    process_name: str
    window_title: str


@dataclass(frozen=True)
class BrowserPageContext:
    domain: str = ""
    label: str = ""


@dataclass
class ForegroundContext:
    process_name: str
    window_title: str
    profile_name: str
    profile: ProfileStyle
    browser_domain: str = ""
    browser_label: str = ""
    site_style: BrowserSiteStyle | None = None
    window_hwnd: int = 0
    writing_style: WritingStyleConfig | None = None

    @property
    def hud_label(self) -> str:
        app = self.app_label
        if self.browser_domain and self.browser_domain != self.browser_label:
            app = f"{app} - {self.browser_domain}"
        title = self.window_title.strip()
        if title and not self.browser_domain and not is_winsper_window(self.process_name, self.window_title):
            app = f"{app} - {title[:36]}"
        return f"{self.profile.label} - {app}"

    @property
    def app_label(self) -> str:
        if self.browser_label:
            return self.browser_label
        if self.browser_domain:
            return self.browser_domain
        if self.process_name:
            return friendly_process_label(self.process_name, self.window_title)
        return "Unknown app"

    @property
    def hud_context_label(self) -> str:
        app = self.app_label
        if app == "Unknown app":
            return self.profile.label
        return app

    @property
    def writing_profile(self) -> ProfileStyle:
        profile = self.profile if self.site_style is None else merge_profile_with_site_style(self.profile, self.site_style)
        if self.writing_style is None:
            return profile
        return apply_writing_style(profile, self.writing_style.preset, self.writing_style.custom_instruction)

    @property
    def destination(self):
        from .destination import infer_destination

        return infer_destination(self.process_name, self.window_title, self.profile_name, self.app_label)


class AppContextDetector:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._cache_lock = threading.Lock()
        self._last_hwnd: int = 0
        self._last_window_title = ""
        self._cached_browser: BrowserPageContext = BrowserPageContext()

    def detect(self) -> ForegroundContext:
        window = get_foreground_window_details()
        return self.detect_window(window, allow_browser_lookup=True)

    def detect_fast(self, window: WindowInfo | None = None) -> ForegroundContext:
        current = window or get_foreground_window_details()
        return self.detect_window(current, allow_browser_lookup=False)

    def detect_window(self, window: WindowInfo, *, allow_browser_lookup: bool) -> ForegroundContext:
        with self._cache_lock:
            cache_matches = (
                bool(window.hwnd)
                and window.hwnd == self._last_hwnd
                and window.window_title == self._last_window_title
            )
            browser = self._cached_browser if cache_matches else BrowserPageContext()

        if not cache_matches and allow_browser_lookup:
            browser = detect_browser_page(window, self.config.browser_context)
            with self._cache_lock:
                self._last_hwnd = window.hwnd
                self._last_window_title = window.window_title
                self._cached_browser = browser
        elif not cache_matches:
            domain = (
                domain_from_title(window.window_title)
                if is_browser_process(window.process_name, self.config.browser_context.browser_processes)
                else ""
            )
            browser = BrowserPageContext(
                domain=domain,
                label=browser_label_for_domain(domain) if domain else "",
            )

        return self._build_context(window, browser)

    def refresh_window(self, window: WindowInfo) -> ForegroundContext:
        browser = detect_browser_page(window, self.config.browser_context)
        with self._cache_lock:
            self._last_hwnd = window.hwnd
            self._last_window_title = window.window_title
            self._cached_browser = browser
        return self._build_context(window, browser)

    def _build_context(self, window: WindowInfo, browser: BrowserPageContext) -> ForegroundContext:
        profile_name = self._match_profile(window.process_name, window.window_title, browser.domain)
        profile = self.config.profiles.styles.get(profile_name) or self.config.profiles.styles.get(self.config.profiles.default_profile)
        if profile is None:
            profile = ProfileStyle(label="General")
            profile_name = "general"
        return ForegroundContext(
            process_name=window.process_name,
            window_title=window.window_title,
            profile_name=profile_name,
            profile=profile,
            browser_domain=browser.domain,
            browser_label=browser.label,
            site_style=self._match_site_style(browser.domain),
            window_hwnd=window.hwnd,
            writing_style=self.config.writing_style,
        )

    def _match_profile(self, process_name: str, window_title: str, browser_domain: str = "") -> str:
        if not self.config.profiles.enabled:
            return self.config.profiles.default_profile
        if is_winsper_window(process_name, window_title):
            return self.config.profiles.default_profile

        if self.config.browser_context.enabled and browser_domain:
            for rule in self.config.browser_context.rules:
                if any(domain_matches(browser_domain, pattern) for pattern in rule.domains):
                    return rule.profile
            builtin_surface = web_ai_surface_for_domain(browser_domain)
            if builtin_surface is not None and builtin_surface.profile in self.config.profiles.styles:
                return builtin_surface.profile

        process_lower = process_name.casefold()
        for rule in self.config.profiles.rules:
            process_match = any(matches_process(process_lower, pattern) for pattern in rule.processes)
            if process_match:
                return rule.profile

        for profile_name, processes in BUILTIN_NATIVE_PROFILE_HINTS:
            if profile_name in self.config.profiles.styles and any(matches_process(process_lower, process) for process in processes):
                return profile_name

        if is_browser_process(process_name, self.config.browser_context.browser_processes):
            for rule in self.config.profiles.rules:
                if any(matches_title_identity(window_title, pattern) for pattern in rule.title_contains):
                    return rule.profile
        return self.config.profiles.default_profile

    def _match_site_style(self, browser_domain: str) -> BrowserSiteStyle | None:
        if not self.config.browser_context.enabled or not browser_domain:
            return None
        for style in self.config.browser_context.site_styles:
            if any(domain_matches(browser_domain, pattern) for pattern in style.domains):
                return style
        return None


def matches_process(process_name: str, pattern: str) -> bool:
    process = normalized_process_name(process_name)
    candidate = normalized_process_name(pattern)
    return bool(process and candidate and process == candidate)


def normalized_process_name(value: str) -> str:
    return value.strip().strip('"').replace("\\", "/").rsplit("/", 1)[-1].casefold()


def matches_title_identity(window_title: str, pattern: str) -> bool:
    candidate = pattern.strip()
    return bool(candidate and re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", window_title, re.IGNORECASE))


def friendly_process_label(process_name: str, window_title: str = "") -> str:
    if is_winsper_window(process_name, window_title):
        return voicepilot_window_label(window_title)
    process = Path(process_name).name.lower().strip()
    if process in FRIENDLY_PROCESS_LABELS:
        return FRIENDLY_PROCESS_LABELS[process]
    stem = Path(process_name).stem.strip()
    if not stem:
        return "Unknown app"
    return stem.replace("_", " ").replace("-", " ").title()


def is_winsper_window(process_name: str, window_title: str = "") -> bool:
    process = Path(process_name).name.lower().strip()
    title = window_title.lower()
    if process == "voicepilot.exe":
        return True
    return process in WINSPER_PROCESSES and is_brand_title(title)


# Compatibility for integrations importing the pre-brand-cleanup helper.
is_voicepilot_window = is_winsper_window


def voicepilot_window_label(window_title: str = "") -> str:
    title = window_title.lower()
    if "settings" in title:
        return window_title_for("Settings")
    if "history" in title:
        return window_title_for("History")
    if "setup" in title or "wizard" in title:
        return window_title_for("Setup")
    return BRAND_NAME


def window_title_for(section: str) -> str:
    return window_title(section)


def domain_matches(domain: str, pattern: str) -> bool:
    clean_domain = normalize_domain(domain)
    clean_pattern = normalize_domain(pattern.replace("*.", ""))
    if not clean_domain or not clean_pattern:
        return False
    if "." not in clean_pattern:
        return clean_pattern in clean_domain.split(".")
    return clean_domain == clean_pattern or clean_domain.endswith(f".{clean_pattern}")


def merge_profile_with_site_style(profile: ProfileStyle, site_style: BrowserSiteStyle) -> ProfileStyle:
    dictation_parts = [profile.dictation_prompt.strip(), site_style.dictation_prompt.strip()]
    rewrite_parts = [profile.rewrite_prompt.strip(), site_style.rewrite_prompt.strip()]
    return ProfileStyle(
        label=profile.label,
        dictation_prompt="\n".join(part for part in dictation_parts if part),
        rewrite_prompt="\n".join(part for part in rewrite_parts if part),
        vocabulary=dedupe_terms([*profile.vocabulary, *site_style.vocabulary]),
    )


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


def detect_browser_page(window: WindowInfo, config: BrowserContextConfig) -> BrowserPageContext:
    if not config.enabled or not is_browser_process(window.process_name, config.browser_processes) or not window.hwnd:
        return BrowserPageContext()
    url = read_browser_url_with_timeout(window.hwnd, config.timeout_ms)
    domain = domain_from_url(url) or domain_from_title(window.window_title)
    if not domain:
        return BrowserPageContext()
    return BrowserPageContext(domain=domain, label=browser_label_for_domain(domain))


def is_browser_process(process_name: str, browser_processes: list[str]) -> bool:
    process = Path(process_name).name.lower().strip()
    return bool(process and process in {name.lower().strip() for name in browser_processes if name.strip()})


def read_browser_url_with_timeout(hwnd: int, timeout_ms: int) -> str:
    global _BROWSER_LOOKUP_THREAD

    timeout_seconds = max(0.05, min(timeout_ms / 1000.0, 1.0))
    result: dict[str, str] = {}

    def worker() -> None:
        result["url"] = read_browser_url_from_uia(hwnd)

    with _BROWSER_LOOKUP_LOCK:
        if _BROWSER_LOOKUP_THREAD is not None and _BROWSER_LOOKUP_THREAD.is_alive():
            return ""
        thread = threading.Thread(target=worker, name="WinsperBrowserContext", daemon=True)
        _BROWSER_LOOKUP_THREAD = thread
    thread.start()
    thread.join(timeout_seconds)
    return result.get("url", "")


def read_browser_url_from_uia(hwnd: int) -> str:
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            from pywinauto import Desktop
    except Exception:
        return ""

    try:
        window = Desktop(backend="uia").window(handle=hwnd)
    except Exception:
        return ""

    for control in sorted(address_bar_controls(window), key=address_bar_score, reverse=True):
        for value in control_text_candidates(control):
            url = normalize_url_candidate(value)
            if url:
                return url
    return ""


def address_bar_controls(window) -> list[object]:
    controls: list[object] = []
    seen: set[int] = set()

    def add(control) -> None:
        identifier = id(control)
        if identifier in seen:
            return
        seen.add(identifier)
        controls.append(control)

    for automation_id in ADDRESS_BAR_AUTOMATION_IDS:
        try:
            add(window.child_window(auto_id=automation_id, control_type="Edit").wrapper_object())
        except Exception:
            pass

    for name in ADDRESS_BAR_NAMES:
        try:
            add(window.child_window(title=name, control_type="Edit").wrapper_object())
        except Exception:
            pass

    for control_type in ["Edit", "ComboBox"]:
        try:
            for control in window.descendants(control_type=control_type):
                add(control)
        except Exception:
            pass
    return controls


def address_bar_score(control) -> int:
    text = " ".join(control_metadata(control) + control_text_candidates(control)).lower()
    score = 0
    for keyword in ["address", "location", "search", "url"]:
        if keyword in text:
            score += 2
    for automation_id in ADDRESS_BAR_AUTOMATION_IDS:
        if automation_id.lower() in text:
            score += 4
    if "http" in text or "." in text:
        score += 1
    return score


def control_metadata(control) -> list[str]:
    candidates: list[str] = []
    info = getattr(control, "element_info", None)
    for attr in ["name", "automation_id", "class_name", "control_type"]:
        try:
            value = getattr(info, attr)
        except Exception:
            value = ""
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    return candidates


def control_text_candidates(control) -> list[str]:
    candidates: list[str] = []
    getters = [
        lambda: control.get_value(),
        lambda: control.window_text(),
        lambda: control.element_info.name,
    ]
    for getter in getters:
        try:
            value = getter()
        except Exception:
            continue
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    return candidates


def normalize_url_candidate(value: str) -> str:
    import re

    text = value.strip()
    if not text or text.lower() in {"search", "address and search bar", "search google or type a url"}:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    matches = re.findall(r"(?:https?://[^\s]+)|(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s]*)?", text)
    for match in matches:
        candidate = match.strip(" \t\r\n<>[](){}'\"")
        if "." in candidate and not candidate.startswith("."):
            return candidate if candidate.startswith(("http://", "https://")) else f"https://{candidate}"
    return ""


def domain_from_url(url: str) -> str:
    if not url:
        return ""
    candidate = url if "://" in url else f"https://{url}"
    try:
        host = urlsplit(candidate).hostname or ""
    except ValueError:
        return ""
    return normalize_domain(host)


def normalize_domain(value: str) -> str:
    domain = value.strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def domain_from_title(title: str) -> str:
    lowered = title.lower()
    if not lowered:
        return ""
    for domain, label in BROWSER_SITE_LABELS:
        if label.lower() in lowered:
            return domain
    return ""


def browser_label_for_domain(domain: str) -> str:
    for pattern, label in BROWSER_SITE_LABELS:
        if domain_matches(domain, pattern):
            return label
    return normalize_domain(domain)


def get_foreground_window_info() -> tuple[str, str]:
    details = get_foreground_window_details()
    return details.process_name, details.window_title


def focus_window(hwnd: int) -> bool:
    if not sys.platform.startswith("win") or not hwnd:
        return False

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        target = wintypes.HWND(hwnd)
        if not user32.IsWindow(target):
            return False
        if user32.IsIconic(target):
            user32.ShowWindow(target, 9)
        return bool(user32.SetForegroundWindow(target))
    except Exception:
        return False


def get_foreground_window_details() -> WindowInfo:
    if not sys.platform.startswith("win"):
        return WindowInfo(hwnd=0, process_name="", window_title="")

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return WindowInfo(hwnd=0, process_name="", window_title="")

        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        window_title = title_buffer.value

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_name = process_name_from_pid(int(pid.value), kernel32)
        return WindowInfo(hwnd=int(hwnd), process_name=process_name, window_title=window_title)
    except Exception:
        return WindowInfo(hwnd=0, process_name="", window_title="")


def process_name_from_pid(pid: int, kernel32) -> str:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return Path(buffer.value).name
    finally:
        kernel32.CloseHandle(handle)
