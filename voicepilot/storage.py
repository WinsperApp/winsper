from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


STALE_DOWNLOAD_PART_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def remove_download_parts(
    root: Path,
    *,
    suffixes: tuple[str, ...] = (".part", ".incomplete"),
) -> int:
    """Remove incomplete model-download files below one owned cache root."""
    if not root.exists():
        return 0
    removed = 0
    for path in root.rglob("*"):
        if not path.is_file() or not path.name.endswith(suffixes):
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            # Active or externally locked downloads stay untouched.
            continue
    return removed


def remove_stale_download_parts(
    root: Path,
    *,
    suffixes: tuple[str, ...] = (".part", ".incomplete"),
    max_age_seconds: int = STALE_DOWNLOAD_PART_MAX_AGE_SECONDS,
    now: float | None = None,
) -> int:
    """Remove abandoned model-download fragments while preserving recent resume data."""
    if not root.exists():
        return 0
    cutoff = (time.time() if now is None else now) - max(0, max_age_seconds)
    removed = 0
    for path in root.rglob("*"):
        if not path.is_file() or not path.name.endswith(suffixes):
            continue
        try:
            if path.stat().st_mtime > cutoff:
                continue
            path.unlink()
            removed += 1
        except OSError:
            # Active or externally locked downloads stay untouched.
            continue
    return removed


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, indent=indent, ensure_ascii=True),
    )
