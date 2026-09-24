"""Explicit selected-text capture outcomes for Polish and rewrite flows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SelectionStatus(str, Enum):
    CAPTURED = "captured"
    NO_SELECTION = "no_selection"
    UNAVAILABLE = "unavailable"
    TARGET_CHANGED = "target_changed"
    TARGET_ELEVATED = "target_elevated"


@dataclass(frozen=True)
class SelectionResult:
    status: SelectionStatus
    text: str = ""
    reason: str = ""
    method: str = ""

    @classmethod
    def captured(cls, text: str, method: str = "") -> "SelectionResult":
        return cls(SelectionStatus.CAPTURED, text=text, method=method)

    @classmethod
    def no_selection(cls, method: str = "") -> "SelectionResult":
        return cls(SelectionStatus.NO_SELECTION, method=method)

    @classmethod
    def unavailable(cls, reason: str, method: str = "") -> "SelectionResult":
        return cls(SelectionStatus.UNAVAILABLE, reason=reason, method=method)

    @classmethod
    def target_changed(cls, reason: str = "Target app changed before selection could be read.") -> "SelectionResult":
        return cls(SelectionStatus.TARGET_CHANGED, reason=reason)

    @classmethod
    def target_elevated(
        cls,
        reason: str = "Windows does not allow Winsper to read selected text from an administrator window.",
    ) -> "SelectionResult":
        return cls(SelectionStatus.TARGET_ELEVATED, reason=reason)
