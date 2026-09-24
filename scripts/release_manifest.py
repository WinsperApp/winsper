"""Create the signed-installer update manifest consumed by Winsper."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlparse


def _official_https_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and (host == "winsper.app" or host.endswith(".winsper.app"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    installer: Path,
    *,
    version: str,
    base_url: str,
    notes: str,
    channel: str = "stable",
    download_page_url: str = "",
) -> dict[str, object]:
    if not _official_https_url(base_url):
        raise ValueError("Release download base URL must use official Winsper HTTPS hosting.")
    if channel not in {"stable", "early-access"}:
        raise ValueError("Release channel must be stable or early-access.")
    if download_page_url and not _official_https_url(download_page_url):
        raise ValueError("Release download page URL must use official Winsper HTTPS hosting.")
    manifest: dict[str, object] = {
        "version": version,
        "installer_url": urljoin(base_url.rstrip("/") + "/", installer.name),
        "sha256": sha256(installer),
        "notes": notes.strip(),
        "channel": channel,
        "size_bytes": installer.stat().st_size,
    }
    if download_page_url:
        manifest["download_page_url"] = download_page_url
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--channel", choices=("stable", "early-access"), default="stable")
    parser.add_argument("--download-page-url", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_manifest(
        args.installer,
        version=args.version,
        base_url=args.base_url,
        notes=args.notes,
        channel=args.channel,
        download_page_url=args.download_page_url,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
