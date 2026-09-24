import hashlib

import pytest

from scripts.release_manifest import build_manifest


def test_release_manifest_uses_https_and_exact_installer_hash(tmp_path):
    installer = tmp_path / "WinsperSetup-0.2.0.exe"
    installer.write_bytes(b"signed installer")
    manifest = build_manifest(
        installer,
        version="0.2.0",
        base_url="https://downloads.winsper.app/releases/",
        notes="Stable release.",
    )
    assert manifest == {
        "version": "0.2.0",
        "installer_url": "https://downloads.winsper.app/releases/WinsperSetup-0.2.0.exe",
        "sha256": hashlib.sha256(b"signed installer").hexdigest(),
        "notes": "Stable release.",
        "channel": "stable",
        "size_bytes": len(b"signed installer"),
    }
    with pytest.raises(ValueError, match="HTTPS"):
        build_manifest(installer, version="0.2.0", base_url="http://example.com", notes="")
    with pytest.raises(ValueError, match="official Winsper"):
        build_manifest(installer, version="0.2.0", base_url="https://example.com", notes="")


def test_release_manifest_describes_manual_early_access_download(tmp_path):
    installer = tmp_path / "WinsperSetup-0.2.0-early-access.exe"
    installer.write_bytes(b"unsigned early access installer")
    manifest = build_manifest(
        installer,
        version="0.2.0",
        base_url="https://winsper.app/downloads/",
        notes="Controlled Early Access.",
        channel="early-access",
        download_page_url="https://winsper.app/download/",
    )
    assert manifest["channel"] == "early-access"
    assert manifest["download_page_url"] == "https://winsper.app/download/"
    assert manifest["size_bytes"] == installer.stat().st_size

    with pytest.raises(ValueError, match="download page URL"):
        build_manifest(
            installer,
            version="0.2.0",
            base_url="https://winsper.app/downloads/",
            notes="",
            channel="early-access",
            download_page_url="http://winsper.app/download/",
        )
