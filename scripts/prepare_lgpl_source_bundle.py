"""Fetch and verify corresponding LGPL sources for the pinned Windows release."""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
import urllib.request
from pathlib import Path


SOURCES = (
    (
        "qt-everywhere-src-6.11.1.tar.xz",
        "https://qt.mirror.constant.com/archive/qt/6.11/6.11.1/single/qt-everywhere-src-6.11.1.tar.xz",
        "252acef8c5ae68074d91cadba2ee4a83465051bbb970dd26e8f0daa0f3904e03",
    ),
    (
        "pyside-setup-everywhere-src-6.11.1.tar.xz",
        "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/pyside-setup-everywhere-src-6.11.1.tar.xz",
        "6ffd9835bb0dd2c56f061d62f1616bb1707cfc0202b80e3165d6be087f3965e2",
    ),
    (
        "pynput-1.8.2.tar.gz",
        "https://files.pythonhosted.org/packages/86/c6/e2d415610cfbc78308bee44218a46124aaa3301b1df08814df819b2254a1/pynput-1.8.2.tar.gz",
        "f493c87157cd3861b4468f7f896857051762f44ed26f1b641e7cc5840a457087",
    ),
    (
        "pystray-0.19.5-py2.py3-none-any.whl",
        "https://files.pythonhosted.org/packages/5c/64/927a4b9024196a4799eba0180e0ca31568426f258a4a5c90f87a97f51d28/pystray-0.19.5-py2.py3-none-any.whl",
        "a0c2229d02cf87207297c22d86ffc57c86c227517b038c0d3c59df79295ac617",
    ),
)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(output: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    lock = (root / "requirements-lock.txt").read_text(encoding="utf-8")
    if version != "1.1.2" or not all(
        pinned in lock for pinned in ("PySide6==6.11.1", "pynput==1.8.2", "pystray==0.19.5")
    ):
        raise ValueError("LGPL source list must be updated for this release's locked versions")
    output.mkdir(parents=True, exist_ok=True)
    inventory = []
    for filename, url, expected_sha256 in SOURCES:
        destination = output / filename
        if not destination.exists():
            temporary = output / f"{filename}.part"
            try:
                with urllib.request.urlopen(url, timeout=90) as response, temporary.open("wb") as target:
                    expected_length = int(response.headers.get("Content-Length", "0"))
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        target.write(chunk)
                if expected_length and temporary.stat().st_size != expected_length:
                    raise ValueError(f"Source archive incomplete: {filename}")
                if _hash_file(temporary) != expected_sha256:
                    raise ValueError(f"Source archive hash mismatch: {filename}")
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        if _hash_file(destination) != expected_sha256:
            raise ValueError(f"Source archive hash mismatch: {filename}")
        inventory.append({"file": filename, "url": url, "sha256": expected_sha256})
        print(f"verified {filename}")
    (output / "sources.json").write_text(
        json.dumps({"winsper_version": version, "sources": inventory}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/lgpl-source-1.1.2"))
    prepare(parser.parse_args().output)
