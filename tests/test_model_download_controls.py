import threading
import time

import pytest

from voicepilot.model_storage import (
    ModelDownloadCancelled,
    _wait_for_download_control,
)


def test_model_download_pause_blocks_and_resume_continues():
    paused = threading.Event()
    cancelled = threading.Event()
    paused.set()
    completed = threading.Event()

    def transfer_chunk() -> None:
        _wait_for_download_control(paused, cancelled)
        completed.set()

    worker = threading.Thread(target=transfer_chunk)
    worker.start()
    time.sleep(0.1)
    assert worker.is_alive()
    assert not completed.is_set()

    paused.clear()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert completed.is_set()


def test_model_download_cancel_wakes_a_paused_transfer():
    paused = threading.Event()
    cancelled = threading.Event()
    paused.set()
    result = []

    def transfer_chunk() -> None:
        try:
            _wait_for_download_control(paused, cancelled)
        except ModelDownloadCancelled:
            result.append("cancelled")

    worker = threading.Thread(target=transfer_chunk)
    worker.start()
    time.sleep(0.1)
    cancelled.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert result == ["cancelled"]


def test_model_download_cancel_is_checked_before_transfer():
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(ModelDownloadCancelled):
        _wait_for_download_control(threading.Event(), cancelled)
