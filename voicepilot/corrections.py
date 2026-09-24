from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import parse_bool
from .starter_content import STARTER_CORRECTIONS
from .storage import atomic_write_json


@dataclass(frozen=True)
class CorrectionRule:
    id: str
    heard: str
    replacement: str
    profiles: list[str]
    enabled: bool = True
    created_at: str = ""


class CorrectionStore:
    def __init__(self, path: Path, max_rules: int = 500, enabled: bool = True) -> None:
        self.path = path
        self.max_rules = max(1, int(max_rules))
        self.enabled = enabled
        self._lock = threading.Lock()
        self._cached_rules: list[CorrectionRule] | None = None
        self._compiled_regexes: dict[str, re.Pattern] = {}

    def _get_compiled_pattern(self, phrase: str) -> re.Pattern:
        if phrase not in self._compiled_regexes:
            self._compiled_regexes[phrase] = phrase_pattern(phrase)
        return self._compiled_regexes[phrase]


    @classmethod
    def for_config(cls, config_path: Path, max_rules: int = 500, enabled: bool = True) -> "CorrectionStore":
        return cls(corrections_path_for_config(config_path), max_rules=max_rules, enabled=enabled)

    def list(self) -> list[CorrectionRule]:
        with self._lock:
            return list(self._read_locked())

    def add_rule(self, heard: str, replacement: str, profiles: list[str] | None = None) -> CorrectionRule:
        rule = CorrectionRule(
            id=uuid.uuid4().hex,
            heard=heard.strip(),
            replacement=replacement.strip(),
            profiles=list(profiles or []),
            enabled=True,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        with self._lock:
            rules = [existing for existing in self._read_locked() if existing.id != rule.id]
            rules.append(rule)
            self._write_locked(trim_rules(rules, self.max_rules))
        return rule

    def replace_all(self, rules: list[CorrectionRule]) -> None:
        with self._lock:
            self._write_locked(trim_rules(rules, self.max_rules))

    def reload(self) -> None:
        """Discard process-local caches so the next read reflects disk."""
        with self._lock:
            self._cached_rules = None
            self._compiled_regexes.clear()

    def remove(self, rule_id: str) -> None:
        with self._lock:
            rules = [rule for rule in self._read_locked() if rule.id != rule_id]
            self._write_locked(rules)

    def clear(self) -> None:
        with self._lock:
            self._write_locked([])

    def apply(self, text: str, profile_name: str | None = None) -> str:
        if not self.enabled or not text:
            return text
        output = text
        for rule in self.list():
            output = apply_rule(output, rule, profile_name, store=self)
        return output

    def _read_locked(self) -> list[CorrectionRule]:
        if self._cached_rules is not None:
            return self._cached_rules
        if not self.path.exists():
            self._cached_rules = default_correction_rules()
            return self._cached_rules
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._cached_rules = []
            return self._cached_rules
        raw_rules = payload.get("rules") if isinstance(payload, dict) else payload
        if not isinstance(raw_rules, list):
            self._cached_rules = []
            return self._cached_rules
        rules: list[CorrectionRule] = []
        for item in raw_rules:
            if not isinstance(item, dict):
                continue
            rule = rule_from_dict(item)
            if rule is not None:
                rules.append(rule)
        self._cached_rules = rules
        return rules

    def _write_locked(self, rules: list[CorrectionRule]) -> None:
        self._cached_rules = list(rules)
        self._compiled_regexes.clear()
        payload = {"version": 1, "rules": [asdict(rule) for rule in rules if rule.heard and rule.replacement]}
        atomic_write_json(self.path, payload)



def corrections_path_for_config(config_path: Path) -> Path:
    return config_path.parent / "corrections.json"


def default_correction_rules() -> list[CorrectionRule]:
    return [
        CorrectionRule(
            id=f"starter-{index}",
            heard=correction.heard,
            replacement=correction.replacement,
            profiles=[],
        )
        for index, correction in enumerate(STARTER_CORRECTIONS, start=1)
    ]


def make_rule(
    heard: str,
    replacement: str,
    profiles: list[str] | None = None,
    enabled: bool = True,
    rule_id: str = "",
    created_at: str = "",
) -> CorrectionRule:
    return CorrectionRule(
        id=rule_id or uuid.uuid4().hex,
        heard=heard.strip(),
        replacement=replacement.strip(),
        profiles=list(profiles or []),
        enabled=enabled,
        created_at=created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def apply_corrections(text: str, rules: list[CorrectionRule], profile_name: str | None = None) -> str:
    output = text
    for rule in rules:
        output = apply_rule(output, rule, profile_name)
    return output


def apply_rule(text: str, rule: CorrectionRule, profile_name: str | None = None, store: CorrectionStore | None = None) -> str:
    if not rule.enabled or not rule.heard.strip() or not rule.replacement.strip():
        return text
    if not profile_allows_rule(rule.profiles, profile_name):
        return text
    if store is not None:
        pattern = store._get_compiled_pattern(rule.heard)
    else:
        pattern = phrase_pattern(rule.heard)
    return pattern.sub(lambda _match: rule.replacement, text)



def phrase_pattern(phrase: str) -> re.Pattern:
    parts = [re.escape(part) for part in phrase.strip().split()]
    body = r"\s+".join(parts)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def profile_allows_rule(profiles: list[str], profile_name: str | None) -> bool:
    if not profiles:
        return True
    allowed = {profile.strip().lower() for profile in profiles if profile.strip()}
    if not allowed or allowed.intersection({"*", "all", "any", "general"}):
        return True
    return (profile_name or "").strip().lower() in allowed


def rule_from_dict(data: dict[str, Any]) -> CorrectionRule | None:
    heard = str(data.get("heard") or "").strip()
    replacement = str(data.get("replacement") or "").strip()
    if not heard or not replacement:
        return None
    return CorrectionRule(
        id=str(data.get("id") or uuid.uuid4().hex),
        heard=heard,
        replacement=replacement,
        profiles=list(data.get("profiles") or []),
        enabled=parse_bool(data.get("enabled"), True),
        created_at=str(data.get("created_at") or ""),
    )


def trim_rules(rules: list[CorrectionRule], max_rules: int) -> list[CorrectionRule]:
    if len(rules) <= max_rules:
        return rules
    return rules[-max_rules:]
