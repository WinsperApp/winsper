from __future__ import annotations

from .settings_empty_state import SettingsEmptyStateMixin
from .settings_memory import SettingsMemoryMixin
from .settings_rewrite_pages import SettingsRewritePagesMixin
from .settings_snippets import SettingsSnippetsMixin
from .settings_surface_pages import SettingsSurfacePagesMixin
from .settings_system_pages import SettingsSystemPagesMixin


class SettingsPagesMixin(
    SettingsEmptyStateMixin,
    SettingsSnippetsMixin,
    SettingsMemoryMixin,
    SettingsSurfacePagesMixin,
    SettingsRewritePagesMixin,
    SettingsSystemPagesMixin,
):
    pass
