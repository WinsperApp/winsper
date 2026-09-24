from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AppConfig


def effective_vocabulary(config: AppConfig) -> list[str]:
    """Return spelling terms speech and rewrite should recognize in any app."""
    terms = list(config.vocabulary)
    for style in config.profiles.styles.values():
        terms.extend(style.vocabulary)
    for style in config.browser_context.site_styles:
        terms.extend(style.vocabulary)

    seen: set[str] = set()
    result: list[str] = []
    for value in terms:
        term = str(value).strip()
        key = term.casefold()
        if not term or key in seen:
            continue
        seen.add(key)
        result.append(term)
    return result
