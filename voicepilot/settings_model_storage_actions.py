from __future__ import annotations

import queue
import threading

from .ai_catalog import default_local_ai_root, local_ai_root
from .model_storage import (
    copy_models_between_locations,
    default_huggingface_cache_root,
    huggingface_cache_root,
)


def restore_default_model_storage(
    owner,
    *,
    browse_button,
    default_button,
    feedback,
    on_done,
) -> None:
    """Copy active models back before switching to Winsper's default roots."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    events: "queue.Queue[tuple[str, object]]" = queue.Queue()
    speech_source = huggingface_cache_root()
    polish_source = local_ai_root()
    browse_button.setEnabled(False)
    default_button.setEnabled(False)
    feedback.show()

    def worker() -> None:
        try:
            copied = copy_models_between_locations(
                speech_source=speech_source,
                speech_destination=default_huggingface_cache_root(),
                polish_source=polish_source,
                polish_destination=default_local_ai_root(),
            )
            events.put(("done", copied))
        except Exception as exc:
            events.put(("error", exc))

    timer = QTimer(owner.window)

    def poll() -> None:
        try:
            event, payload = events.get_nowait()
        except queue.Empty:
            return
        timer.stop()
        feedback.hide()
        browse_button.setEnabled(True)
        default_button.setEnabled(True)
        if event == "done":
            on_done(int(payload))
            return
        QMessageBox.warning(
            owner.window,
            "Winsper",
            f"Winsper could not restore the default model location.\n\n{payload}",
        )

    timer.timeout.connect(poll)
    timer.start(100)
    threading.Thread(target=worker, name="WinsperModelStorageRestore", daemon=True).start()
