from __future__ import annotations

from enum import Enum


class DeliveryStatus(str, Enum):
    """Truthful outcome of a cross-application delivery attempt."""

    SENT = "sent"  # Input was dispatched; target receipt cannot be proven.
    VERIFIED = "verified"
    COPIED = "copied"
    TARGET_CHANGED = "target_changed"
    TARGET_ELEVATED = "target_elevated"
    BLOCKED = "blocked"
    FAILED = "failed"


ELEVATED_TARGET_REASON = "Press Ctrl+V in the administrator window"
