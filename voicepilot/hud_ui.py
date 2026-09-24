from __future__ import annotations

from .config import HudConfig
from .hud_core import ConsoleHUD


def create_status_hud(config: HudConfig):
    from .hud_qt import QtStatusHUD
    return QtStatusHUD(config)


__all__ = ["ConsoleHUD", "create_status_hud"]
