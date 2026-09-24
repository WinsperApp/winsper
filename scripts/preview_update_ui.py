"""Open the real Winsper update UI with a safe, simulated newer release."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from voicepilot.config import default_config_path
from voicepilot.updates import UpdateInfo


PREVIEW_UPDATE = UpdateInfo(
    version="0.3.0",
    installer_url="https://winsper.app/downloads/WinsperSetup-0.3.0-early-access.exe",
    sha256="0" * 64,
    notes=(
        "Performance improvements\n"
        "Faster startup and smoother transcription.\n\n"
        "Smarter experience\n"
        "Improved model setup and accuracy.\n\n"
        "More reliable\n"
        "Bug fixes and stability improvements."
    ),
    download_page_url="https://winsper.app/download/",
    channel="early-access",
    size_bytes=82_208_358,
)


def main() -> None:
    from PySide6.QtCore import QDir, QLockFile

    from voicepilot.settings_qt import run_settings_window

    preview_lock = QLockFile(
        str(Path(QDir.tempPath()) / "winsper-update-preview.lock")
    )
    preview_lock.setStaleLockTime(0)
    if not preview_lock.tryLock(0):
        print("The Winsper update preview is already open.")
        return

    try:
        with tempfile.TemporaryDirectory(prefix="winsper-update-preview-") as temporary:
            preview_config = Path(temporary) / "config.yaml"
            current_config = default_config_path()
            if current_config.is_file():
                shutil.copy2(current_config, preview_config)

            with patch("voicepilot.updates.check_for_update", return_value=PREVIEW_UPDATE):
                run_settings_window(preview_config, initial_page="About")
    finally:
        preview_lock.unlock()


if __name__ == "__main__":
    main()
