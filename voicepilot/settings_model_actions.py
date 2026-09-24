from __future__ import annotations

from .settings_model_download_actions import SettingsModelDownloadActionsMixin
from .settings_model_selection_actions import SettingsModelSelectionActionsMixin


class SettingsModelActionsMixin(
    SettingsModelSelectionActionsMixin,
    SettingsModelDownloadActionsMixin,
):
    """Model controls split by selection and download responsibility."""
