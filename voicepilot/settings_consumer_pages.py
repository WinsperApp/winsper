from __future__ import annotations

from .settings_dictation_page import SettingsDictationPageMixin
from .settings_personalize_page import SettingsPersonalizePageMixin
from .settings_polish_page import SettingsPolishPageMixin


class SettingsConsumerPagesMixin(
    SettingsDictationPageMixin,
    SettingsPolishPageMixin,
    SettingsPersonalizePageMixin,
):
    """Consumer settings grouped by complete page responsibility."""
