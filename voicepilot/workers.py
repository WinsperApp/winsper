from __future__ import annotations

import queue
import threading
from collections.abc import Callable


class BoundedWorker:
    """Single daemon worker with an optional one-item recovery queue.

    Normal submit rejects parallel work. Recovery from a cancelled backend call
    may queue one replacement without running models concurrently.
    """

    def __init__(self, name: str) -> None:
        self._queue: "queue.Queue[tuple[Callable, tuple] | None]" = queue.Queue(maxsize=1)
        self._busy = threading.Event()
        self._running = threading.Event()
        self._stopping = threading.Event()
        self._submit_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    @property
    def busy(self) -> bool:
        return self._busy.is_set()

    def submit(self, callback: Callable, *args, queue_if_busy: bool = False) -> bool:
        with self._submit_lock:
            if self._stopping.is_set() or (self._busy.is_set() and not queue_if_busy):
                return False
            try:
                self._queue.put_nowait((callback, args))
            except queue.Full:
                return False
            self._busy.set()
            return True

    def discard_pending(self, predicate: Callable[[Callable, tuple], bool]) -> bool:
        """Remove queued, not-yet-running work matching predicate."""
        with self._submit_lock:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return False
            if item is None:
                self._queue.put_nowait(item)
                return False
            callback, args = item
            if not predicate(callback, args):
                self._queue.put_nowait(item)
                return False
            if not self._running.is_set():
                self._busy.clear()
            return True

    def stop(self, timeout: float = 2.0) -> bool:
        with self._submit_lock:
            self._stopping.set()
            removed_pending_task = False
            while True:
                try:
                    item = self._queue.get_nowait()
                    removed_pending_task = removed_pending_task or item is not None
                except queue.Empty:
                    break
            if removed_pending_task:
                self._busy.clear()
            self._queue.put_nowait(None)
        if self._thread is threading.current_thread():
            return False
        self._thread.join(timeout=max(0.0, timeout))
        return not self._thread.is_alive()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            callback, args = item
            self._running.set()
            try:
                callback(*args)
            finally:
                self._running.clear()
                with self._submit_lock:
                    if self._queue.empty():
                        self._busy.clear()
