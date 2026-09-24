from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import traceback


MAX_LOG_BYTES = 200_000
RECENT_LOG_CHARS = 8_000
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_ -]?key|license[_ -]?key|access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*)[^\s,;&#]+"),
    re.compile(r"(?i)([?&](?:token|key|secret|signature)=)[^&#\s]+"),
)


def runtime_log_path_for_config(config_path: Path) -> Path:
    return config_path.parent / "voicepilot.log"


def write_runtime_log(config_path: Path, label: str, message: str, exc: BaseException | None = None) -> None:
    path = runtime_log_path_for_config(config_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _trim_log(path)
        lines = [
            "",
            f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {label}",
            redact_runtime_text(message.strip()) or "(no message)",
        ]
        if exc is not None:
            trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
            lines.append(redact_runtime_text(trace))
        with path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")
    except OSError:
        pass


def read_recent_runtime_log(config_path: Path, max_chars: int = RECENT_LOG_CHARS) -> str:
    path = runtime_log_path_for_config(config_path)
    if not path.exists():
        return "No runtime log yet."
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Could not read runtime log: {exc}"
    text = text.strip()
    if not text:
        return "Runtime log is empty."
    return text[-max_chars:]


def _trim_log(path: Path, max_bytes: int = MAX_LOG_BYTES) -> None:
    if not path.exists():
        return
    try:
        if path.stat().st_size <= max_bytes:
            return
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - max_bytes // 2))
            tail = handle.read()
        marker = b"[older log lines trimmed]\n"
        path.write_bytes(marker + tail)
    except OSError:
        pass


def redact_runtime_text(text: str) -> str:
    """Remove credentials from user-shareable diagnostics and local logs."""
    redacted = str(text or "")
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[redacted]", redacted)
    return redacted
