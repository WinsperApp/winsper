from __future__ import annotations

import hashlib
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from voicepilot.updates import UpdateInfo, check_for_update, download_update


class _DownloadResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        url: str = "https://winsper.app/downloads/WinsperSetup-0.3.0.exe",
        content_length: int | None = None,
    ) -> None:
        self._payload = payload
        self._offset = 0
        self._url = url
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        end = len(self._payload) if size < 0 else min(len(self._payload), self._offset + size)
        chunk = self._payload[self._offset : end]
        self._offset = end
        return chunk


def _info(payload: bytes, *, size_bytes: int | None = None) -> UpdateInfo:
    return UpdateInfo(
        version="0.3.0",
        installer_url="https://winsper.app/downloads/WinsperSetup-0.3.0.exe",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload) if size_bytes is None else size_bytes,
    )


def test_missing_stable_manifest_means_no_update_yet() -> None:
    feed = "https://winsper.app/updates/stable.json"
    missing = urllib.error.HTTPError(feed, 404, "Not Found", None, None)

    with patch("voicepilot.updates.urllib.request.urlopen", side_effect=missing):
        assert check_for_update(feed, "1.0.0") is None


def test_update_check_still_surfaces_non_404_server_failures() -> None:
    feed = "https://winsper.app/updates/stable.json"
    failure = urllib.error.HTTPError(feed, 503, "Unavailable", None, None)

    with (
        patch("voicepilot.updates.urllib.request.urlopen", side_effect=failure),
        pytest.raises(urllib.error.HTTPError),
    ):
        check_for_update(feed, "1.0.0")


def test_download_update_verifies_before_exposing_installer(tmp_path: Path) -> None:
    payload = b"signed Winsper installer"
    target = tmp_path / "WinsperSetup.exe"
    response = _DownloadResponse(payload, content_length=len(payload))

    with (
        patch("voicepilot.updates.urllib.request.urlopen", return_value=response),
        patch("voicepilot.updates.verify_authenticode_signature", return_value="CN=Winsper") as verify,
    ):
        result = download_update(_info(payload), expected_publisher="Winsper", destination=target)

    assert result == target
    assert target.read_bytes() == payload
    assert not target.with_suffix(".exe.part").exists()
    assert verify.call_args.args[0] == target.with_suffix(".exe.part")


@pytest.mark.parametrize(
    ("response", "info", "message"),
    [
        (
            _DownloadResponse(b"wrong"),
            _info(b"expected", size_bytes=0),
            "SHA-256",
        ),
        (
            _DownloadResponse(b"short", content_length=5),
            _info(b"short", size_bytes=6),
            "size does not match",
        ),
        (
            _DownloadResponse(b"payload", url="http://example.test/WinsperSetup.exe"),
            _info(b"payload"),
            "outside official Winsper",
        ),
        (
            _DownloadResponse(b"payload", url="https://example.test/WinsperSetup.exe"),
            _info(b"payload"),
            "outside official Winsper",
        ),
    ],
)
def test_download_update_rejects_untrusted_payloads_and_cleans_up(
    tmp_path: Path,
    response: _DownloadResponse,
    info: UpdateInfo,
    message: str,
) -> None:
    target = tmp_path / "WinsperSetup.exe"
    with (
        patch("voicepilot.updates.urllib.request.urlopen", return_value=response),
        patch("voicepilot.updates.verify_authenticode_signature"),
        pytest.raises(ValueError, match=message),
    ):
        download_update(info, expected_publisher="Winsper", destination=target)

    assert not target.exists()
    assert not target.with_suffix(".exe.part").exists()


def test_download_update_cleans_up_when_signature_fails(tmp_path: Path) -> None:
    payload = b"unsigned installer"
    target = tmp_path / "WinsperSetup.exe"
    response = _DownloadResponse(payload, content_length=len(payload))

    with (
        patch("voicepilot.updates.urllib.request.urlopen", return_value=response),
        patch(
            "voicepilot.updates.verify_authenticode_signature",
            side_effect=ValueError("publisher mismatch"),
        ),
        pytest.raises(ValueError, match="publisher mismatch"),
    ):
        download_update(_info(payload), expected_publisher="Winsper", destination=target)

    assert not target.exists()
    assert not target.with_suffix(".exe.part").exists()
