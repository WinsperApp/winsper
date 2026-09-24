from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from voicepilot.config import AppConfig, config_to_dict, load_config, save_config
from voicepilot.config_migrations import (
    CURRENT_SCHEMA_VERSION,
    ConfigMigrationError,
    migrate_config_data,
)


@pytest.mark.parametrize("source_version", [1, 2, 3])
def test_every_previous_schema_migrates_without_changing_user_values(source_version: int):
    source = {
        "schema_version": source_version,
        "speech": {"model": "large-v3-turbo", "language": "fr"},
        "extension_owned": {"keep": "exactly"},
    }

    result = migrate_config_data(source)

    assert result.target_version == CURRENT_SCHEMA_VERSION
    assert result.data["speech"] == source["speech"]
    assert result.data["extension_owned"] == source["extension_owned"]
    assert source["schema_version"] == source_version


def test_unversioned_public_config_is_treated_as_legacy_v1():
    result = migrate_config_data({"hud": {"theme": "dark"}})

    assert result.source_version == 1
    assert result.data["schema_version"] == 4
    assert result.data["hud"] == {"theme": "dark"}
    assert result.data["vocabulary"] == ["Winsper"]
    assert {item["trigger"] for item in result.data["snippets"]["items"]} == {
        "today's date",
        "current time",
        "date and time",
    }


def test_current_schema_is_not_rewritten_or_aliased():
    source = {"schema_version": CURRENT_SCHEMA_VERSION, "vocabulary": ["Winsper"]}
    result = migrate_config_data(source)

    assert not result.changed
    assert result.data == source
    assert result.data is not source


@pytest.mark.parametrize("version", [0, 5, "4", True])
def test_invalid_or_future_schema_fails_closed(version):
    with pytest.raises(ConfigMigrationError):
        migrate_config_data({"schema_version": version})


def test_load_migrates_atomically_and_keeps_one_exact_backup(tmp_path: Path):
    path = tmp_path / "config.yaml"
    original = {"speech": {"model": "small", "language": "de"}, "custom": {"x": 1}}
    path.write_text(yaml.safe_dump(original, sort_keys=False), encoding="utf-8")

    loaded = load_config(path)

    assert loaded.schema_version == CURRENT_SCHEMA_VERSION
    assert loaded.speech.model == "small"
    assert loaded.speech.language == "de"
    migrated = yaml.safe_load(path.read_text(encoding="utf-8"))
    backup = yaml.safe_load((tmp_path / "config.yaml.schema-v1.bak").read_text(encoding="utf-8"))
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    assert migrated["custom"] == {"x": 1}
    assert backup == original

    path.write_text(
        yaml.safe_dump({"schema_version": 4, "speech": {"model": "small.en"}}),
        encoding="utf-8",
    )
    load_config(path)
    assert yaml.safe_load((tmp_path / "config.yaml.schema-v1.bak").read_text(encoding="utf-8")) == original


def test_malformed_config_is_not_replaced_or_backed_up(tmp_path: Path):
    path = tmp_path / "config.yaml"
    original = "schema_version: future\nspeech: []\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ConfigMigrationError):
        load_config(path)

    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("*.bak")) == []


def test_new_saves_are_schema_v4_with_generic_starter_content(tmp_path: Path):
    path = tmp_path / "config.yaml"
    save_config(AppConfig(), path)

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 4
    assert saved["vocabulary"] == ["Winsper"]
    assert [item["trigger"] for item in saved["snippets"]["items"]] == [
        "today's date",
        "current time",
        "date and time",
    ]
    assert config_to_dict(AppConfig())["schema_version"] == 4


def test_v3_starter_migration_is_additive_and_does_not_replace_trigger_collisions():
    source = {
        "schema_version": 3,
        "vocabulary": ["Custom term", "winsper"],
        "snippets": {
            "enabled": False,
            "items": [
                {"name": "Personal date", "trigger": "Today's Date", "text": "mine"},
                {"name": "Email", "trigger": "my email", "text": "me@example.com"},
            ],
        },
    }

    result = migrate_config_data(source)

    assert result.data["snippets"]["enabled"] is False
    items = result.data["snippets"]["items"]
    assert next(item for item in items if item["trigger"] == "Today's Date")["text"] == "mine"
    assert sum(item["trigger"].casefold() == "today's date" for item in items) == 1
    assert {item["trigger"] for item in items} >= {
        "my email",
        "current time",
        "date and time",
    }
    assert result.data["vocabulary"] == ["Custom term", "winsper"]


def test_interrupted_migration_keeps_original_and_backup(tmp_path: Path, monkeypatch):
    import voicepilot.config as config_module

    path = tmp_path / "config.yaml"
    original = "speech:\n  model: small\n"
    path.write_text(original, encoding="utf-8")
    real_atomic_write = config_module.atomic_write_text
    writes = 0

    def fail_migrated_write(target: Path, text: str, encoding: str = "utf-8") -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("simulated interrupted replacement")
        real_atomic_write(target, text, encoding)

    monkeypatch.setattr(config_module, "atomic_write_text", fail_migrated_write)

    with pytest.raises(OSError, match="interrupted"):
        load_config(path)

    assert path.read_text(encoding="utf-8") == original
    assert (tmp_path / "config.yaml.schema-v1.bak").exists()
