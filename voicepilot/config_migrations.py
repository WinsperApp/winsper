from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from .starter_content import STARTER_TEXT_SHORTCUTS, STARTER_VOCABULARY

CURRENT_SCHEMA_VERSION = 4
LEGACY_SCHEMA_VERSION = 1


class ConfigMigrationError(ValueError):
    """Raised when a config cannot be migrated without risking user settings."""


@dataclass(frozen=True)
class ConfigMigration:
    data: dict[str, Any]
    source_version: int
    target_version: int

    @property
    def changed(self) -> bool:
        return self.source_version != self.target_version


MigrationStep = Callable[[dict[str, Any]], dict[str, Any]]


def _stamp_version(data: dict[str, Any], version: int) -> dict[str, Any]:
    """Advance a schema whose field layout stayed backwards compatible."""
    migrated = deepcopy(data)
    migrated["schema_version"] = version
    return migrated


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    # V1 was the unversioned public config. V2 formalised the schema without
    # renaming fields; defaults continue to be supplied by the typed loader.
    return _stamp_version(data, 2)


def _v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    # V3 adds migration guarantees. Existing values and unknown extension keys
    # deliberately remain untouched.
    return _stamp_version(data, 3)


def _v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    """Add small, removable starter content without replacing user values."""
    migrated = deepcopy(data)

    snippets = migrated.get("snippets")
    if snippets is None:
        snippets = {"enabled": True, "items": []}
        migrated["snippets"] = snippets
    if isinstance(snippets, dict):
        items = snippets.get("items")
        if items is None:
            items = []
            snippets["items"] = items
        if isinstance(items, list):
            existing_triggers = {
                str(item.get("trigger") or "").strip().casefold()
                for item in items
                if isinstance(item, dict)
            }
            for shortcut in STARTER_TEXT_SHORTCUTS:
                if shortcut.trigger.casefold() in existing_triggers:
                    continue
                items.append(
                    {
                        "name": shortcut.name,
                        "trigger": shortcut.trigger,
                        "text": shortcut.text,
                        "aliases": list(shortcut.aliases),
                        "profiles": [],
                    }
                )

    vocabulary = migrated.get("vocabulary")
    if vocabulary is None:
        vocabulary = []
        migrated["vocabulary"] = vocabulary
    if isinstance(vocabulary, list):
        existing_terms = {str(term).strip().casefold() for term in vocabulary}
        vocabulary.extend(
            term for term in STARTER_VOCABULARY if term.casefold() not in existing_terms
        )

    migrated["schema_version"] = 4
    return migrated


_MIGRATIONS: dict[int, MigrationStep] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
    3: _v3_to_v4,
}


def migrate_config_data(data: dict[str, Any]) -> ConfigMigration:
    if not isinstance(data, dict):
        raise ConfigMigrationError("Config root must be a mapping.")

    raw_version = data.get("schema_version", LEGACY_SCHEMA_VERSION)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise ConfigMigrationError("schema_version must be an integer.")
    if raw_version < LEGACY_SCHEMA_VERSION:
        raise ConfigMigrationError(f"Unsupported config schema version: {raw_version}.")
    if raw_version > CURRENT_SCHEMA_VERSION:
        raise ConfigMigrationError(
            f"Config schema {raw_version} is newer than this Winsper build supports "
            f"({CURRENT_SCHEMA_VERSION})."
        )

    migrated = deepcopy(data)
    version = raw_version
    while version < CURRENT_SCHEMA_VERSION:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise ConfigMigrationError(f"No migration path from config schema {version}.")
        migrated = step(migrated)
        version += 1

    return ConfigMigration(migrated, raw_version, version)
