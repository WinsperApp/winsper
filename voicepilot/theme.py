from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    mode: str
    bg: str
    surface: str
    surface_2: str
    surface_3: str
    sidebar: str
    sidebar_active: str
    field: str
    border: str
    border_soft: str
    text: str
    muted: str
    subtle: str
    accent: str
    accent_2: str
    amber: str
    coral: str
    success: str
    on_accent: str
    shadow: str


DARK = ThemePalette(
    mode="dark",
    bg="#0c0d10",
    surface="#15171b",
    surface_2="#1d2025",
    surface_3="#282c33",
    sidebar="#111318",
    sidebar_active="#1b1f26",
    field="#0a0c0f",
    border="#363b44",
    border_soft="#252a31",
    text="#f5f7fa",
    muted="#a7afb9",
    subtle="#727c88",
    accent="#007fd4",
    accent_2="#5b43f2",
    amber="#e9b44c",
    coral="#f27663",
    success="#78d67b",
    on_accent="#ffffff",
    shadow="#030405",
)


LIGHT = ThemePalette(
    mode="light",
    bg="#f5f7fa",
    surface="#ffffff",
    surface_2="#f4f6f9",
    surface_3="#e9edf3",
    sidebar="#f0f3f7",
    sidebar_active="#ffffff",
    field="#ffffff",
    border="#cbd5e1",
    border_soft="#e1e6ed",
    text="#172033",
    muted="#64748b",
    subtle="#8b98aa",
    accent="#007fd4",
    accent_2="#5b43f2",
    amber="#b67808",
    coral="#d84e3f",
    success="#238b45",
    on_accent="#ffffff",
    shadow="#b8c9de",
)


HIGH_CONTRAST_DARK = ThemePalette(
    mode="dark",
    bg="#000000",
    surface="#000000",
    surface_2="#0a0a0a",
    surface_3="#171717",
    sidebar="#000000",
    sidebar_active="#171717",
    field="#000000",
    border="#ffffff",
    border_soft="#9b9b9b",
    text="#ffffff",
    muted="#e6e6e6",
    subtle="#c8c8c8",
    accent="#00ffff",
    accent_2="#00ffff",
    amber="#ffff00",
    coral="#ff6b6b",
    success="#55ff7f",
    on_accent="#000000",
    shadow="#000000",
)


HIGH_CONTRAST_LIGHT = ThemePalette(
    mode="light",
    bg="#ffffff",
    surface="#ffffff",
    surface_2="#f2f2f2",
    surface_3="#e3e3e3",
    sidebar="#ffffff",
    sidebar_active="#e3e3e3",
    field="#ffffff",
    border="#000000",
    border_soft="#555555",
    text="#000000",
    muted="#202020",
    subtle="#383838",
    accent="#005fcc",
    accent_2="#005fcc",
    amber="#6b4e00",
    coral="#a40000",
    success="#006b2e",
    on_accent="#ffffff",
    shadow="#ffffff",
)


def theme_values() -> list[str]:
    return ["system", "dark", "light"]


def get_palette(theme: str | None) -> ThemePalette:
    resolved = resolve_theme(theme)
    from .windows_ui import prefers_high_contrast

    if prefers_high_contrast():
        return HIGH_CONTRAST_LIGHT if resolved == "light" else HIGH_CONTRAST_DARK
    return LIGHT if resolved == "light" else DARK


def resolve_theme(theme: str | None) -> str:
    requested = (theme or "system").strip().lower()
    if requested in {"dark", "light"}:
        return requested
    return system_theme()


def system_theme() -> str:
    if not sys.platform.startswith("win"):
        return "dark"
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(value) else "dark"
    except (ImportError, OSError, TypeError, ValueError):
        return "dark"
