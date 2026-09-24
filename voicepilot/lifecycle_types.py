from __future__ import annotations

import threading
from dataclasses import dataclass

from .selection import SelectionResult


@dataclass
class PolishSelectionCapture:
    ready: threading.Event
    result: SelectionResult | None = None
