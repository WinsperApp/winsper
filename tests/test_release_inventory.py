from __future__ import annotations

import hashlib

from scripts.release_inventory import build_inventory


def test_release_inventory_binds_files_version_and_revision(tmp_path):
    package = tmp_path / "Winsper"
    package.mkdir()
    executable = package / "Winsper.exe"
    executable.write_bytes(b"application")
    installer = tmp_path / "WinsperSetup-1.0.0.exe"
    installer.write_bytes(b"installer")

    inventory = build_inventory(
        package,
        [installer],
        version="1.0.0",
        revision="abc123",
    )

    assert inventory["version"] == "1.0.0"
    assert inventory["source_revision"] == "abc123"
    assert inventory["artifacts"] == [
        {
            "path": "Winsper.exe",
            "size_bytes": len(b"application"),
            "sha256": hashlib.sha256(b"application").hexdigest(),
        },
        {
            "path": "WinsperSetup-1.0.0.exe",
            "size_bytes": len(b"installer"),
            "sha256": hashlib.sha256(b"installer").hexdigest(),
        },
    ]
    assert any(item["name"] == "pytest" for item in inventory["build_environment_dependencies"])
