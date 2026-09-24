from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

MAX_INSTALLER_BYTES = 512 * 1024 * 1024
OFFICIAL_UPDATE_DOMAIN = "winsper.app"


def _is_official_https_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and (host == OFFICIAL_UPDATE_DOMAIN or host.endswith(f".{OFFICIAL_UPDATE_DOMAIN}"))


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    installer_url: str
    sha256: str
    notes: str = ""
    download_page_url: str = ""
    channel: str = "stable"
    size_bytes: int = 0


def parse_update_manifest(payload: bytes) -> UpdateInfo:
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Update manifest must be a JSON object.")
    version = str(data.get("version") or "").strip()
    installer_url = str(data.get("installer_url") or "").strip()
    sha256 = str(data.get("sha256") or "").strip().lower()
    if not version or not re.fullmatch(r"\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ValueError("Update manifest has an invalid version.")
    if not _is_official_https_url(installer_url):
        raise ValueError("Update installer must use an official Winsper HTTPS URL.")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("Update manifest has an invalid SHA-256 digest.")
    download_page_url = str(data.get("download_page_url") or "").strip()
    if download_page_url and not _is_official_https_url(download_page_url):
        raise ValueError("Update download page must use an official Winsper HTTPS URL.")
    channel = str(data.get("channel") or "stable").strip().casefold()
    if channel not in {"stable", "early-access"}:
        raise ValueError("Update manifest has an invalid release channel.")
    try:
        size_bytes = max(0, int(data.get("size_bytes") or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Update manifest has an invalid installer size.") from exc
    return UpdateInfo(
        version,
        installer_url,
        sha256,
        str(data.get("notes") or "").strip(),
        download_page_url,
        channel,
        size_bytes,
    )


def manual_download_url(info: UpdateInfo, fallback_url: str) -> str:
    """Return the human-facing HTTPS download page for a manual update."""
    candidate = info.download_page_url.strip() or fallback_url.strip()
    if not _is_official_https_url(candidate):
        raise ValueError("Manual update page must use an official Winsper HTTPS URL.")
    return candidate


def check_for_update(feed_url: str, current_version: str, timeout_seconds: float = 8.0) -> UpdateInfo | None:
    if not _is_official_https_url(feed_url):
        raise ValueError("Update feed must use an official Winsper HTTPS URL.")
    request = urllib.request.Request(feed_url, headers={"User-Agent": f"Winsper/{current_version}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read(512 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        # A channel may exist before its first public release. Treat a missing
        # manifest as "no update yet"; other server failures remain visible.
        if exc.code == 404:
            return None
        raise
    if len(payload) > 512 * 1024:
        raise ValueError("Update manifest is unexpectedly large.")
    info = parse_update_manifest(payload)
    return info if version_key(info.version) > version_key(current_version) else None


def download_update(
    info: UpdateInfo,
    *,
    expected_publisher: str,
    destination: Path | None = None,
    timeout_seconds: float = 120.0,
) -> Path:
    if not expected_publisher.strip():
        raise ValueError("Update publisher is not configured in this build.")
    if not _is_official_https_url(info.installer_url):
        raise ValueError("Update installer must use an official Winsper HTTPS URL.")
    if info.size_bytes < 0 or info.size_bytes > MAX_INSTALLER_BYTES:
        raise ValueError("Update installer size is invalid.")
    target = destination or update_download_dir() / f"WinsperSetup-{info.version}.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    downloaded_bytes = 0
    request = urllib.request.Request(info.installer_url, headers={"User-Agent": "Winsper Updater"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response, temporary.open("wb") as handle:
            final_url = response.geturl()
            if not _is_official_https_url(final_url):
                raise ValueError("Update download redirected outside official Winsper HTTPS hosting.")
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_bytes = int(content_length)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Update server returned an invalid installer size.") from exc
                if declared_bytes < 0 or declared_bytes > MAX_INSTALLER_BYTES:
                    raise ValueError("Update installer is unexpectedly large.")
                if info.size_bytes and declared_bytes != info.size_bytes:
                    raise ValueError("Update installer size does not match the manifest.")
            while chunk := response.read(1024 * 1024):
                downloaded_bytes += len(chunk)
                if downloaded_bytes > MAX_INSTALLER_BYTES:
                    raise ValueError("Update installer is unexpectedly large.")
                if info.size_bytes and downloaded_bytes > info.size_bytes:
                    raise ValueError("Update installer size does not match the manifest.")
                digest.update(chunk)
                handle.write(chunk)
        if info.size_bytes and downloaded_bytes != info.size_bytes:
            raise ValueError("Update installer size does not match the manifest.")
        if digest.hexdigest().lower() != info.sha256:
            raise ValueError("Downloaded update failed SHA-256 verification.")
        verify_authenticode_signature(temporary, expected_publisher)
        os.replace(temporary, target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return target


def verify_authenticode_signature(path: Path, expected_publisher: str) -> str:
    """Require a trusted Windows signature pinned to Winsper's publisher."""
    if os.name != "nt":
        raise RuntimeError("Authenticode verification requires Windows.")
    publisher = expected_publisher.strip()
    if not publisher:
        raise ValueError("Update publisher is not configured in this build.")
    escaped_path = str(path.resolve()).replace("'", "''")
    script = (
        f"$s=Get-AuthenticodeSignature -LiteralPath '{escaped_path}';"
        "$o=[pscustomobject]@{Status=[string]$s.Status;Subject=[string]$s.SignerCertificate.Subject};"
        "$o|ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise ValueError("Windows could not verify the update signature.")
    try:
        result = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Windows returned an invalid update signature result.") from exc
    status = str(result.get("Status") or "")
    subject = str(result.get("Subject") or "")
    if status.casefold() != "valid":
        raise ValueError(f"Update signature is not trusted ({status or 'unknown status'}).")
    if publisher.casefold() not in subject.casefold():
        raise ValueError("Update signature publisher does not match Winsper.")
    return subject


def update_download_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return root / "Winsper" / "updates"


def version_key(value: str) -> tuple[int, ...]:
    core = value.split("-", 1)[0].split("+", 1)[0]
    return tuple(int(part) for part in core.split("."))
