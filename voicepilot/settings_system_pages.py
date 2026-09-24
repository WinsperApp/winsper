from __future__ import annotations

from .settings_about_page import SettingsAboutPageMixin
from .settings_history_page import SettingsHistoryPageMixin


class SettingsSystemPagesMixin(
    SettingsAboutPageMixin,
    SettingsHistoryPageMixin,
):
    """System-facing settings grouped by complete page responsibility."""
