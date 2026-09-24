from __future__ import annotations

from threading import Lock

from .speech_model_catalog import DownloadProgress, DownloadProgressCallback, SpeechModelPreset

def format_download_progress(progress: DownloadProgress) -> str:
    if progress.total_bytes > 0:
        downloaded = format_bytes(progress.downloaded_bytes)
        total = format_bytes(progress.total_bytes)
        remaining = format_bytes(progress.remaining_bytes)
        if progress.done:
            return f"{downloaded} downloaded."
        if progress.downloaded_bytes <= 0:
            return f"Starting download. {total} total."
        return f"{downloaded} of {total} downloaded, {remaining} left."
    return progress.status


def format_bytes(value: int | float) -> str:
    amount = float(max(0, value))
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} B"
            return f"{amount:.1f} {unit}"
        amount /= 1024


def _emit_progress(callback: DownloadProgressCallback | None, progress: DownloadProgress) -> None:
    if callback is None:
        return
    try:
        callback(progress)
    except Exception:
        pass


def _progress_tqdm_class(preset: SpeechModelPreset, callback: DownloadProgressCallback | None):
    if callback is None:
        return None

    lock = Lock()
    state = {"downloaded": 0, "total": 0}

    class WinsperTqdm:
        def __init__(self, *args, **kwargs):
            self.iterable = args[0] if args else None
            self.desc = str(kwargs.get("desc") or "")
            self.unit = str(kwargs.get("unit") or "")
            self.total = int(kwargs.get("total") or 0)
            self.n = int(kwargs.get("initial") or 0)
            self.disable = bool(kwargs.get("disable", False))
            self._report("Checking files" if self.unit != "B" else "Downloading")

        @classmethod
        def get_lock(cls):
            if not hasattr(cls, "_lock"):
                cls._lock = Lock()
            return cls._lock

        @classmethod
        def set_lock(cls, value) -> None:
            cls._lock = value

        def __iter__(self):
            if self.iterable is None:
                return
            for item in self.iterable:
                yield item
                self.update(1)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.close()

        def update(self, n: int | float | None = 1) -> None:
            step = int(n or 0)
            self.n += step
            if self.unit == "B":
                with lock:
                    state["downloaded"] = max(state["downloaded"], int(self.n))
                    state["total"] = max(state["total"], int(self.total or 0))
                self._report("Downloading")

        def refresh(self, *args, **kwargs) -> None:
            if self.unit == "B":
                with lock:
                    state["downloaded"] = max(state["downloaded"], int(self.n))
                    state["total"] = max(state["total"], int(self.total or 0))
                self._report("Downloading")

        def reset(self, total: int | None = None) -> None:
            if total is not None:
                self.total = int(total)
            self.n = 0
            self.refresh()

        def set_description(self, desc: str | None = None, refresh: bool = True) -> None:
            self.desc = str(desc or "")
            if refresh:
                self.refresh()

        def set_description_str(self, desc: str | None = None, refresh: bool = True) -> None:
            self.set_description(desc, refresh=refresh)

        def set_postfix(self, *args, **kwargs) -> None:
            pass

        def clear(self, *args, **kwargs) -> None:
            pass

        def close(self) -> None:
            pass

        def _report(self, status: str) -> None:
            if self.disable:
                return
            with lock:
                downloaded = int(state["downloaded"])
                total = int(state["total"])
            _emit_progress(
                callback,
                DownloadProgress(
                    model=preset.model,
                    repo_id=preset.repo_id,
                    status=status,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                ),
            )

    return WinsperTqdm


def _file_progress_tqdm_class(
    preset: SpeechModelPreset,
    callback: DownloadProgressCallback | None,
    completed_before: int,
    total_bytes: int,
    file_size: int,
    status: str,
    control_check=None,
):
    class WinsperFileTqdm:
        def __init__(self, *args, **kwargs):
            self.iterable = args[0] if args else None
            self.n = int(kwargs.get("initial") or 0)
            self.total = int(kwargs.get("total") or file_size or 0)
            self.disable = bool(kwargs.get("disable", False))
            self._report()

        @classmethod
        def get_lock(cls):
            if not hasattr(cls, "_lock"):
                cls._lock = Lock()
            return cls._lock

        @classmethod
        def set_lock(cls, value) -> None:
            cls._lock = value

        def __iter__(self):
            if self.iterable is None:
                return
            for item in self.iterable:
                yield item
                self.update(1)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.close()

        def update(self, n: int | float | None = 1) -> None:
            if control_check is not None:
                control_check()
            self.n += int(n or 0)
            self._report()

        def refresh(self, *args, **kwargs) -> None:
            if control_check is not None:
                control_check()
            self._report()

        def reset(self, total: int | None = None) -> None:
            if total is not None:
                self.total = int(total)
            self.n = 0
            self._report()

        def set_description(self, desc: str | None = None, refresh: bool = True) -> None:
            if refresh:
                self._report()

        def set_description_str(self, desc: str | None = None, refresh: bool = True) -> None:
            self.set_description(desc, refresh=refresh)

        def set_postfix(self, *args, **kwargs) -> None:
            pass

        def clear(self, *args, **kwargs) -> None:
            pass

        def close(self) -> None:
            self._report()

        def _report(self) -> None:
            if self.disable:
                return
            limit = max(file_size, int(self.total or 0), 0)
            current_file_bytes = min(max(0, int(self.n)), limit) if limit > 0 else max(0, int(self.n))
            downloaded = completed_before + current_file_bytes
            if total_bytes > 0:
                downloaded = min(downloaded, total_bytes)
            _emit_progress(
                callback,
                DownloadProgress(
                    model=preset.model,
                    repo_id=preset.repo_id,
                    status=status,
                    downloaded_bytes=downloaded,
                    total_bytes=total_bytes,
                ),
            )

    return WinsperFileTqdm


def _silent_tqdm_class():
    class SilentTqdm:
        def __init__(self, *args, **kwargs):
            self.iterable = args[0] if args else None
            self.total = int(kwargs.get("total") or 0)
            self.n = int(kwargs.get("initial") or 0)

        @classmethod
        def get_lock(cls):
            if not hasattr(cls, "_lock"):
                cls._lock = Lock()
            return cls._lock

        @classmethod
        def set_lock(cls, value) -> None:
            cls._lock = value

        def __iter__(self):
            if self.iterable is None:
                return
            for item in self.iterable:
                yield item
                self.update(1)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.close()

        def update(self, n: int | float | None = 1) -> None:
            self.n += int(n or 0)

        def refresh(self, *args, **kwargs) -> None:
            pass

        def reset(self, total: int | None = None) -> None:
            if total is not None:
                self.total = int(total)
            self.n = 0

        def set_description(self, desc: str | None = None, refresh: bool = True) -> None:
            pass

        def set_description_str(self, desc: str | None = None, refresh: bool = True) -> None:
            pass

        def set_postfix(self, *args, **kwargs) -> None:
            pass

        def clear(self, *args, **kwargs) -> None:
            pass

        def close(self) -> None:
            pass

    return SilentTqdm


def _short_filename(filename: str) -> str:
    value = str(filename or "model file")
    if len(value) <= 42:
        return value
    return f"...{value[-39:]}"
