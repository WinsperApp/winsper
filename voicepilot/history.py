from __future__ import annotations

import csv
import io
import json
import threading
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .app_context import ForegroundContext
from .secure_store import DpapiFileStore, SecureStoreError
from .storage import atomic_write_text


@dataclass(frozen=True)
class HistoryEvent:
    id: str
    created_at: str
    mode: str
    input_text: str
    output_text: str
    profile_name: str
    profile_label: str
    process_name: str
    window_title: str
    speech_model: str
    browser_domain: str = ""
    browser_label: str = ""
    rewrite_model: str = ""
    instruction: str = ""
    source: str = ""
    snippet_name: str = ""
    snippet_trigger: str = ""
    word_count: int = 0
    transcription_ms: int = 0
    polish_ms: int = 0
    speech_engine: str = ""
    speech_device: str = ""
    speech_compute_type: str = ""


@dataclass(frozen=True)
class HistoryInsights:
    actions: int = 0
    words: int = 0
    dictations: int = 0
    polishes: int = 0
    measured_transcriptions: int = 0
    measured_polishes: int = 0
    average_transcription_ms: int = 0
    average_polish_ms: int = 0
    primary_speech_model: str = ""
    primary_speech_device: str = ""


RETENTION_OPTIONS: tuple[tuple[int, str], ...] = (
    (0, "Forever"),
    (30, "30 days"),
    (90, "90 days"),
    (365, "1 year"),
)


class HistoryStore:
    def __init__(
        self,
        path: Path,
        max_items: int = 200,
        enabled: bool = True,
        retention_days: int = 0,
        legacy_path: Path | None = None,
    ) -> None:
        self.path = path
        self.legacy_path = legacy_path
        self.max_items = max(1, int(max_items))
        self.enabled = enabled
        self.retention_days = max(0, int(retention_days))
        self._lock = threading.Lock()
        self._cached_events: list[HistoryEvent] | None = None
        self._known_event_count: int | None = None
        self._known_file_signature = self._file_signature_locked()
        self._last_retention_check: date | None = None
        self._protected_store = DpapiFileStore(
            path,
            entropy=b"Winsper encrypted history v1",
            description="Winsper history",
            data_label="encrypted history",
        )

    @classmethod
    def for_config(
        cls,
        config_path: Path,
        max_items: int = 200,
        enabled: bool = True,
        retention_days: int = 0,
    ) -> "HistoryStore":
        return cls(
            history_path_for_config(config_path),
            max_items=max_items,
            enabled=enabled,
            retention_days=retention_days,
            legacy_path=legacy_history_path_for_config(config_path),
        )

    def append(self, event: HistoryEvent) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._invalidate_if_file_changed_locked()
            events = self._events_locked()
            events.append(event)
            self._write_locked(events)
            self._enforce_limits_locked()

    def list(self, limit: int | None = None) -> list[HistoryEvent]:
        with self._lock:
            self._invalidate_if_file_changed_locked()
            self._prune_retention_locked()
            events = self._events_locked()
        events.reverse()
        return events[:limit] if limit is not None else events

    def latest(self) -> HistoryEvent | None:
        events = self.list(limit=1)
        return events[0] if events else None

    def clear(self) -> None:
        with self._lock:
            self._remove_legacy_plaintext_locked()
            self._protected_store.delete()
            self._known_event_count = 0
            self._cached_events = []
            self._known_file_signature = None
            self._last_retention_check = None

    def delete(self, event_id: str) -> bool:
        """Delete one persisted event by id."""
        if not event_id:
            return False
        with self._lock:
            self._invalidate_if_file_changed_locked()
            events = self._events_locked()
            remaining = [event for event in events if event.id != event_id]
            if len(remaining) == len(events):
                return False
            self._write_locked(remaining)
            return True

    def prune(self, now: datetime | None = None) -> int:
        """Remove entries older than the configured retention window."""
        with self._lock:
            self._invalidate_if_file_changed_locked()
            return self._prune_retention_locked(now=now)

    def update_output(self, event_id: str, output_text: str) -> HistoryEvent | None:
        if not self.enabled:
            return None
        with self._lock:
            self._invalidate_if_file_changed_locked()
            events = self._events_locked()
            updated_event: HistoryEvent | None = None
            updated: list[HistoryEvent] = []
            for event in events:
                if event.id == event_id:
                    updated_event = replace(event, output_text=output_text, word_count=len(output_text.split()))
                    updated.append(updated_event)
                else:
                    updated.append(event)
            if updated_event is None:
                return None
            self._write_locked(updated)
            return updated_event

    def update_source(self, event_id: str, source: str) -> HistoryEvent | None:
        """Persist final delivery state for a previously checkpointed event."""
        if not self.enabled:
            return None
        with self._lock:
            self._invalidate_if_file_changed_locked()
            events = self._events_locked()
            updated_event: HistoryEvent | None = None
            updated: list[HistoryEvent] = []
            for event in events:
                if event.id == event_id:
                    updated_event = replace(event, source=source)
                    updated.append(updated_event)
                else:
                    updated.append(event)
            if updated_event is None:
                return None
            self._write_locked(updated)
            return updated_event

    def _enforce_limits_locked(self) -> None:
        retention_due = self.retention_days > 0 and self._last_retention_check != datetime.now(timezone.utc).date()
        limit_due = self._known_event_count is None or self._known_event_count > self.max_items
        if not retention_due and not limit_due:
            self._known_file_signature = self._file_signature_locked()
            return

        events = self._events_locked()
        keep = _events_within_retention(events, self.retention_days)
        if self.retention_days > 0:
            self._last_retention_check = datetime.now(timezone.utc).date()
        if len(keep) > self.max_items:
            keep = keep[-self.max_items :]
        if len(keep) != len(events):
            self._write_locked(keep)
        else:
            self._known_event_count = len(events)
            self._known_file_signature = self._file_signature_locked()

    def _prune_retention_locked(self, now: datetime | None = None) -> int:
        if self.retention_days <= 0:
            return 0
        events = self._events_locked()
        keep = _events_within_retention(events, self.retention_days, now=now)
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        self._last_retention_check = reference.astimezone(timezone.utc).date()
        removed = len(events) - len(keep)
        if removed:
            self._write_locked(keep)
        return removed

    def _write_locked(self, events: list[HistoryEvent]) -> None:
        payload = json.dumps([asdict(event) for event in events], ensure_ascii=True).encode("utf-8")
        self._protected_store.save(payload)
        self._cached_events = list(events)
        self._known_event_count = len(events)
        self._known_file_signature = self._file_signature_locked()

    def _read_locked(self) -> list[HistoryEvent]:
        if not self.path.exists():
            legacy_events = self._migrate_legacy_locked()
            if legacy_events is not None:
                return legacy_events
            self._cached_events = []
            self._known_event_count = 0
            self._known_file_signature = None
            return []
        try:
            data = json.loads((self._protected_store.load() or b"[]").decode("utf-8"))
        except SecureStoreError:
            self._cached_events = None
            self._known_event_count = None
            self._known_file_signature = self._file_signature_locked()
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self._cached_events = None
            self._known_event_count = None
            self._known_file_signature = self._file_signature_locked()
            raise SecureStoreError("Encrypted history is damaged and was left untouched.") from exc
        if not isinstance(data, list):
            self._cached_events = None
            self._known_event_count = None
            self._known_file_signature = self._file_signature_locked()
            raise SecureStoreError("Encrypted history has an invalid format and was left untouched.")
        events: list[HistoryEvent] = []
        for item in data:
            event = event_from_dict(item) if isinstance(item, dict) else None
            if event is not None:
                events.append(event)
        self._remove_legacy_plaintext_locked()
        self._cached_events = list(events)
        self._known_event_count = len(events)
        self._known_file_signature = self._file_signature_locked()
        return events

    def _events_locked(self) -> list[HistoryEvent]:
        if self.path.exists() and self.legacy_path is not None and self.legacy_path.exists():
            self._remove_legacy_plaintext_locked()
        if self._cached_events is None:
            return self._read_locked()
        return list(self._cached_events)

    def _invalidate_if_file_changed_locked(self) -> None:
        signature = self._file_signature_locked()
        if signature != self._known_file_signature:
            self._cached_events = None
            self._known_event_count = None
            self._last_retention_check = None
            self._known_file_signature = signature

    def _file_signature_locked(self) -> tuple[int, int] | None:
        path = self.path if self.path.exists() else self.legacy_path
        if path is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _migrate_legacy_locked(self) -> list[HistoryEvent] | None:
        if self.legacy_path is None or not self.legacy_path.exists():
            return None
        try:
            lines = self.legacy_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise SecureStoreError("Winsper could not read legacy plaintext history.") from exc
        events = [event for line in lines if line.strip() for event in (event_from_dict(_json_object(line)),) if event is not None]
        self._write_locked(events)
        self._remove_legacy_plaintext_locked()
        self._known_file_signature = self._file_signature_locked()
        return list(events)

    def _remove_legacy_plaintext_locked(self) -> None:
        if self.legacy_path is None:
            return
        try:
            self.legacy_path.unlink(missing_ok=True)
        except OSError as exc:
            raise SecureStoreError("Winsper protected the history, but could not remove the legacy plaintext copy.") from exc


def history_path_for_config(config_path: Path) -> Path:
    return config_path.parent / "history.enc"


def legacy_history_path_for_config(config_path: Path) -> Path:
    return config_path.parent / "history.jsonl"


def create_history_event(
    mode: str,
    input_text: str,
    output_text: str,
    context: ForegroundContext,
    speech_model: str,
    rewrite_model: str = "",
    instruction: str = "",
    source: str = "",
    snippet_name: str = "",
    snippet_trigger: str = "",
    transcription_ms: int = 0,
    polish_ms: int = 0,
    speech_engine: str = "",
    speech_device: str = "",
    speech_compute_type: str = "",
) -> HistoryEvent:
    return HistoryEvent(
        id=uuid.uuid4().hex,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        mode=mode,
        input_text=input_text,
        output_text=output_text,
        profile_name=context.profile_name,
        profile_label=context.profile.label,
        process_name=context.process_name,
        window_title=context.window_title,
        browser_domain=context.browser_domain,
        browser_label=context.browser_label,
        speech_model=speech_model,
        rewrite_model=rewrite_model,
        instruction=instruction,
        source=source,
        snippet_name=snippet_name,
        snippet_trigger=snippet_trigger,
        word_count=len(output_text.split()),
        transcription_ms=max(0, int(transcription_ms)),
        polish_ms=max(0, int(polish_ms)),
        speech_engine=speech_engine,
        speech_device=speech_device,
        speech_compute_type=speech_compute_type,
    )


def event_from_dict(data: dict[str, Any]) -> HistoryEvent | None:
    try:
        return HistoryEvent(
            id=str(data.get("id") or ""),
            created_at=str(data.get("created_at") or ""),
            mode=str(data.get("mode") or ""),
            input_text=str(data.get("input_text") or ""),
            output_text=str(data.get("output_text") or ""),
            profile_name=str(data.get("profile_name") or ""),
            profile_label=str(data.get("profile_label") or ""),
            process_name=str(data.get("process_name") or ""),
            window_title=str(data.get("window_title") or ""),
            browser_domain=str(data.get("browser_domain") or ""),
            browser_label=str(data.get("browser_label") or ""),
            speech_model=str(data.get("speech_model") or ""),
            rewrite_model=str(data.get("rewrite_model") or ""),
            instruction=str(data.get("instruction") or ""),
            source=str(data.get("source") or ""),
            snippet_name=str(data.get("snippet_name") or ""),
            snippet_trigger=str(data.get("snippet_trigger") or ""),
            word_count=int(data.get("word_count") or 0),
            transcription_ms=max(0, int(data.get("transcription_ms") or 0)),
            polish_ms=max(0, int(data.get("polish_ms") or 0)),
            speech_engine=str(data.get("speech_engine") or ""),
            speech_device=str(data.get("speech_device") or ""),
            speech_compute_type=str(data.get("speech_compute_type") or ""),
        )
    except (TypeError, ValueError):
        return None


def retention_label(days: int) -> str:
    normalized = max(0, int(days))
    known = next((label for value, label in RETENTION_OPTIONS if value == normalized), "")
    if known:
        return known
    return f"{normalized} day{'s' if normalized != 1 else ''}"


def retention_days_from_label(label: str, default: int = 0) -> int:
    known = next((days for days, value in RETENTION_OPTIONS if value == label), None)
    if known is not None:
        return known
    first = (label or "").strip().split(" ", 1)[0]
    try:
        return max(0, int(first))
    except ValueError:
        return max(0, int(default))


def summarize_history(events: list[HistoryEvent]) -> HistoryInsights:
    transcription_times = [event.transcription_ms for event in events if event.transcription_ms > 0]
    polish_times = [event.polish_ms for event in events if event.polish_ms > 0]
    models = Counter(event.speech_model for event in events if event.speech_model)
    devices = Counter(event.speech_device for event in events if event.speech_device)
    polish_modes = {"polish", "prompt", "polish_selection", "rewrite"}
    return HistoryInsights(
        actions=len(events),
        words=sum(max(0, event.word_count) for event in events),
        dictations=sum(event.mode not in polish_modes for event in events),
        polishes=sum(event.mode in polish_modes for event in events),
        measured_transcriptions=len(transcription_times),
        measured_polishes=len(polish_times),
        average_transcription_ms=_average_ms(transcription_times),
        average_polish_ms=_average_ms(polish_times),
        primary_speech_model=models.most_common(1)[0][0] if models else "",
        primary_speech_device=devices.most_common(1)[0][0] if devices else "",
    )


def history_insights_text(events: list[HistoryEvent]) -> str:
    insights = summarize_history(events)
    if not insights.actions:
        return "Performance details appear after your first dictation."
    parts = [
        f"{insights.actions} action{'s' if insights.actions != 1 else ''}",
        f"{insights.words:,} words",
    ]
    if insights.measured_transcriptions:
        parts.append(f"speech avg {_duration_label(insights.average_transcription_ms)}")
    if insights.measured_polishes:
        parts.append(f"Polish avg {_duration_label(insights.average_polish_ms)}")
    if insights.primary_speech_model:
        parts.append(insights.primary_speech_model)
    if insights.primary_speech_device:
        parts.append("GPU" if insights.primary_speech_device.casefold() == "cuda" else insights.primary_speech_device.upper())
    if not insights.measured_transcriptions:
        parts.append("timing starts with your next dictation")
    return "  ·  ".join(parts)


def export_history_csv(events: list[HistoryEvent], destination: Path) -> None:
    """Export history in a Unicode Excel-friendly CSV without formula injection."""
    columns = (
        "Date",
        "Mode",
        "Application",
        "Website",
        "Input",
        "Output",
        "Instruction",
        "Speech model",
        "Polish model",
        "Device",
        "Compute",
        "Delivery",
        "Words",
        "Transcription ms",
        "Polish ms",
    )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for event in events:
        writer.writerow(
            {
                "Date": _csv_cell(event.created_at),
                "Mode": _csv_cell(event.mode),
                "Application": _csv_cell(event.process_name),
                "Website": _csv_cell(event.browser_domain),
                "Input": _csv_cell(event.input_text),
                "Output": _csv_cell(event.output_text),
                "Instruction": _csv_cell(event.instruction),
                "Speech model": _csv_cell(event.speech_model),
                "Polish model": _csv_cell(event.rewrite_model),
                "Device": _csv_cell(event.speech_device),
                "Compute": _csv_cell(event.speech_compute_type),
                "Delivery": _csv_cell(event.source),
                "Words": max(0, event.word_count),
                "Transcription ms": max(0, event.transcription_ms),
                "Polish ms": max(0, event.polish_ms),
            }
        )
    atomic_write_text(destination, "\ufeff" + buffer.getvalue())


def _events_within_retention(
    events: list[HistoryEvent],
    retention_days: int,
    now: datetime | None = None,
) -> list[HistoryEvent]:
    if retention_days <= 0:
        return list(events)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    cutoff = reference.astimezone(timezone.utc) - timedelta(days=retention_days)
    keep: list[HistoryEvent] = []
    for event in events:
        created_at = _parse_timestamp(event.created_at)
        if created_at is None or created_at >= cutoff:
            keep.append(event)
    return keep


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _average_ms(values: list[int]) -> int:
    return int(round(sum(values) / len(values))) if values else 0


def _duration_label(milliseconds: int) -> str:
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    return f"{milliseconds / 1000:.1f} s"


def _csv_cell(value: str) -> str:
    text = str(value or "")
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _json_object(line: str) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
