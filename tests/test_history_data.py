import csv
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from voicepilot.history import (
    HistoryEvent,
    HistoryStore,
    event_from_dict,
    export_history_csv,
    retention_days_from_label,
    retention_label,
    summarize_history,
    history_path_for_config,
    legacy_history_path_for_config,
)
from voicepilot.history_ui_support import history_count_text, history_visible_count_text
from voicepilot.secure_store import SecureStoreError


def test_history_count_text_distinguishes_recent_entries_from_rolling_limit():
    assert history_count_text(0, 0, 200) == "No transcripts"
    assert history_count_text(1, 1, 200) == "1 transcript"
    assert history_count_text(12, 12, 200) == "12 transcripts"
    assert history_count_text(200, 200, 200) == "Latest 200 transcripts"
    assert history_count_text(1, 200, 200) == "1 match · Latest 200 stored"
    assert history_count_text(8, 200, 200) == "8 matches · Latest 200 stored"


def test_history_visible_count_text_explains_progressive_rendering():
    assert history_visible_count_text(25, 200, 200, 200) == "Showing 25 of 200 transcripts"
    assert history_visible_count_text(25, 80, 200, 200) == "Showing 25 of 80 matches"
    assert history_visible_count_text(80, 80, 200, 200) == history_count_text(80, 200, 200)


def test_history_retention_prunes_only_expired_valid_entries():
    with tempfile.TemporaryDirectory() as temp:
        store = HistoryStore(Path(temp) / "history.jsonl")
        now = datetime.now(timezone.utc)

        def event(event_id: str, created_at: str) -> HistoryEvent:
            return HistoryEvent(
                id=event_id,
                created_at=created_at,
                mode="ramble",
                input_text=event_id,
                output_text=event_id,
                profile_name="general",
                profile_label="General",
                process_name="app.exe",
                window_title="App",
                speech_model="small.en",
                word_count=1,
            )

        store.append(event("old", (now - timedelta(days=60)).isoformat()))
        store.append(event("recent", (now - timedelta(days=6)).isoformat()))
        store.append(event("unknown", "not-a-date"))
        store.retention_days = 30

        removed = store.prune(now=now)

        assert removed == 1
        assert [item.id for item in store.list()] == ["unknown", "recent"]


def test_history_append_does_not_reread_bounded_file(tmp_path):
    store = HistoryStore(tmp_path / "history.jsonl", max_items=2)
    original_read = store._read_locked
    read_calls = 0

    def tracked_read():
        nonlocal read_calls
        read_calls += 1
        return original_read()

    store._read_locked = tracked_read
    for index in range(5):
        store.append(
            HistoryEvent(
                id=str(index),
                created_at=f"2026-07-18T00:00:0{index}+00:00",
                mode="ramble",
                input_text="input",
                output_text="output",
                profile_name="general",
                profile_label="General",
                process_name="app.exe",
                window_title="App",
                speech_model="small.en",
            )
        )

    assert read_calls == 1
    assert [item.id for item in store.list()] == ["4", "3"]


def test_history_append_recovers_after_external_clear(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)

    def event(event_id: str) -> HistoryEvent:
        return HistoryEvent(
            id=event_id,
            created_at="2026-07-18T00:00:00+00:00",
            mode="ramble",
            input_text="input",
            output_text="output",
            profile_name="general",
            profile_label="General",
            process_name="app.exe",
            window_title="App",
            speech_model="small.en",
        )

    store.append(event("before"))
    path.unlink()
    store.append(event("after"))

    assert [item.id for item in store.list()] == ["after"]


def test_history_is_dpapi_encrypted_and_migrates_plaintext_once(tmp_path):
    config_path = tmp_path / "config.yaml"
    legacy_path = legacy_history_path_for_config(config_path)
    legacy_path.write_text(
        json.dumps(
            {
                "id": "legacy",
                "created_at": "2026-07-18T00:00:00+00:00",
                "mode": "ramble",
                "input_text": "private source text",
                "output_text": "private output text",
                "profile_name": "general",
                "profile_label": "General",
                "process_name": "app.exe",
                "window_title": "App",
                "speech_model": "small.en",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    store = HistoryStore.for_config(config_path)
    assert [event.id for event in store.list()] == ["legacy"]
    encrypted_path = history_path_for_config(config_path)
    assert encrypted_path.exists()
    assert not legacy_path.exists()
    encrypted = encrypted_path.read_bytes()
    assert b"private source text" not in encrypted
    assert b"private output text" not in encrypted
    assert [event.id for event in HistoryStore.for_config(config_path).list()] == ["legacy"]


def test_history_removes_plaintext_residue_after_interrupted_migration(tmp_path):
    config_path = tmp_path / "config.yaml"
    store = HistoryStore.for_config(config_path)
    store.append(
        HistoryEvent(
            id="protected",
            created_at="2026-07-18T00:00:00+00:00",
            mode="ramble",
            input_text="private source",
            output_text="private output",
            profile_name="general",
            profile_label="General",
            process_name="app.exe",
            window_title="App",
            speech_model="small.en",
        )
    )
    legacy_path = legacy_history_path_for_config(config_path)
    legacy_path.write_text('{"id":"stale plaintext"}\n', encoding="utf-8")

    assert [event.id for event in HistoryStore.for_config(config_path).list()] == ["protected"]
    assert not legacy_path.exists()


def test_corrupt_encrypted_history_is_never_silently_replaced(tmp_path):
    config_path = tmp_path / "config.yaml"
    store = HistoryStore.for_config(config_path)
    encrypted_path = history_path_for_config(config_path)
    encrypted_path.write_bytes(b"not valid DPAPI data")
    original = encrypted_path.read_bytes()
    event = HistoryEvent(
        id="new",
        created_at="2026-07-18T00:00:00+00:00",
        mode="ramble",
        input_text="private source",
        output_text="private output",
        profile_name="general",
        profile_label="General",
        process_name="app.exe",
        window_title="App",
        speech_model="small.en",
    )

    with pytest.raises(SecureStoreError):
        store.list()
    with pytest.raises(SecureStoreError):
        store.append(event)

    assert encrypted_path.read_bytes() == original


def test_invalid_decrypted_history_is_never_silently_replaced(tmp_path):
    config_path = tmp_path / "config.yaml"
    store = HistoryStore.for_config(config_path)
    store._protected_store.save(b'{"unexpected":"object"}')
    original = history_path_for_config(config_path).read_bytes()

    with pytest.raises(SecureStoreError):
        store.list()

    assert history_path_for_config(config_path).read_bytes() == original


def test_history_delete_removes_only_requested_event(tmp_path):
    store = HistoryStore(tmp_path / "history.jsonl")

    def event(event_id: str) -> HistoryEvent:
        return HistoryEvent(
            id=event_id,
            created_at="2026-07-18T00:00:00+00:00",
            mode="ramble",
            input_text=event_id,
            output_text=event_id,
            profile_name="general",
            profile_label="General",
            process_name="app.exe",
            window_title="App",
            speech_model="small.en",
        )

    store.append(event("keep"))
    store.append(event("delete"))

    assert store.delete("delete") is True
    assert [item.id for item in store.list()] == ["keep"]
    assert store.delete("missing") is False


def test_history_export_is_unicode_safe_and_neutralizes_spreadsheet_formulas():
    with tempfile.TemporaryDirectory() as temp:
        destination = Path(temp) / "history.csv"
        event = HistoryEvent(
            id="export",
            created_at="2026-07-16T10:00:00+00:00",
            mode="ramble",
            input_text="\u0928\u092e\u0938\u094d\u0924\u0947\nAvery",
            output_text="=HYPERLINK(\"https://invalid.example\")",
            profile_name="general",
            profile_label="General",
            process_name="notepad.exe",
            window_title="Notes",
            speech_model="large-v3-turbo",
            speech_device="cuda",
            speech_compute_type="float16",
            transcription_ms=812,
            word_count=1,
        )

        export_history_csv([event], destination)

        with destination.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["Input"] == "\u0928\u092e\u0938\u094d\u0924\u0947\nAvery"
        assert rows[0]["Output"].startswith("'=HYPERLINK")
        assert rows[0]["Device"] == "cuda"
        assert rows[0]["Transcription ms"] == "812"


def test_history_insights_use_only_measured_timings_and_keep_old_records_compatible():
    old = event_from_dict(
        {
            "id": "old",
            "created_at": "2026-07-15T10:00:00+00:00",
            "mode": "ramble",
            "input_text": "hello",
            "output_text": "hello",
            "profile_name": "general",
            "profile_label": "General",
            "process_name": "app.exe",
            "window_title": "App",
            "speech_model": "small.en",
            "word_count": 1,
        }
    )
    measured = HistoryEvent(
        id="new",
        created_at="2026-07-16T10:00:00+00:00",
        mode="polish",
        input_text="um hello",
        output_text="Hello.",
        profile_name="general",
        profile_label="General",
        process_name="app.exe",
        window_title="App",
        speech_model="small.en",
        speech_device="cpu",
        transcription_ms=800,
        polish_ms=1200,
        word_count=1,
    )

    assert old is not None
    summary = summarize_history([old, measured])
    assert summary.actions == 2
    assert summary.measured_transcriptions == 1
    assert summary.average_transcription_ms == 800
    assert summary.average_polish_ms == 1200
    assert summary.primary_speech_model == "small.en"
    assert retention_label(90) == "90 days"
    assert retention_days_from_label("1 year") == 365
    assert retention_label(60) == "60 days"
    assert retention_days_from_label("60 days") == 60
