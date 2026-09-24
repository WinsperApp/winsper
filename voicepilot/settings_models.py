from __future__ import annotations

from .settings_model_actions import SettingsModelActionsMixin
from .settings_model_pages import SettingsModelPagesMixin


class SettingsModelsMixin(SettingsModelPagesMixin, SettingsModelActionsMixin):
    pass
