from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .storage import atomic_write_json

TYPING_WPM = 40
_LOCK = threading.Lock()


@dataclass(frozen=True)
class UsageSummary:
    today_words: int = 0
    today_actions: int = 0
    total_words: int = 0
    total_actions: int = 0
    today_minutes_saved: float = 0.0
    total_minutes_saved: float = 0.0


def usage_path_for_config(config_path: Path) -> Path:
    return config_path.parent / "usage.json"


def record_usage(config_path: Path, words: int, actions: int = 1) -> None:
    word_count = max(0, int(words))
    action_count = max(0, int(actions))
    if word_count <= 0 and action_count <= 0:
        return
    path = usage_path_for_config(config_path)
    today = datetime.now().date().isoformat()
    with _LOCK:
        payload = _read_payload(path)
        payload["total_words"] = int(payload.get("total_words") or 0) + word_count
        payload["total_actions"] = int(payload.get("total_actions") or 0) + action_count
        by_day = payload.setdefault("by_day", {})
        if not isinstance(by_day, dict):
            by_day = {}
            payload["by_day"] = by_day
        day = by_day.setdefault(today, {"words": 0, "actions": 0})
        if not isinstance(day, dict):
            day = {"words": 0, "actions": 0}
            by_day[today] = day
        day["words"] = int(day.get("words") or 0) + word_count
        day["actions"] = int(day.get("actions") or 0) + action_count
        _write_payload(path, payload)


def usage_summary(config_path: Path) -> UsageSummary:
    payload = _read_payload(usage_path_for_config(config_path))
    today = datetime.now().date().isoformat()
    by_day = payload.get("by_day") if isinstance(payload.get("by_day"), dict) else {}
    day = by_day.get(today) if isinstance(by_day, dict) else {}
    if not isinstance(day, dict):
        day = {}
    today_words = int(day.get("words") or 0)
    total_words = int(payload.get("total_words") or 0)
    return UsageSummary(
        today_words=today_words,
        today_actions=int(day.get("actions") or 0),
        total_words=total_words,
        total_actions=int(payload.get("total_actions") or 0),
        today_minutes_saved=minutes_saved(today_words),
        total_minutes_saved=minutes_saved(total_words),
    )


def format_usage_summary(summary: UsageSummary) -> str:
    if summary.today_words <= 0:
        return "No dictation yet today."
    return f"{summary.today_words} words today | about {format_minutes(summary.today_minutes_saved)} saved"


def format_minutes(value: float) -> str:
    minutes = max(0, int(round(value)))
    if value <= 0:
        return "0 min"
    if minutes < 1:
        return "<1 min"
    if minutes == 1:
        return "1 min"
    return f"{minutes} min"


def minutes_saved(words: int) -> float:
    return max(0, int(words)) / TYPING_WPM


def _read_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"total_words": 0, "total_actions": 0, "by_day": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"total_words": 0, "total_actions": 0, "by_day": {}}
    return payload if isinstance(payload, dict) else {"total_words": 0, "total_actions": 0, "by_day": {}}


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)
