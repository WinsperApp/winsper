from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_inventory(
    package_root: Path,
    installers: list[Path],
    *,
    version: str,
    revision: str,
) -> dict[str, object]:
    package_root = package_root.resolve()
    artifacts: list[dict[str, object]] = []
    for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
        artifacts.append(
            {
                "path": path.relative_to(package_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    for path in sorted(item.resolve() for item in installers):
        artifacts.append(
            {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    dependencies: list[dict[str, str]] = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        license_name = (
            distribution.metadata.get("License-Expression")
            or distribution.metadata.get("License")
            or "UNKNOWN"
        ).strip()
        dependencies.append(
            {
                "name": name,
                "version": distribution.version,
                "license": license_name,
            }
        )
    dependencies.sort(key=lambda item: item["name"].casefold())
    return {
        "format_version": 1,
        "product": "Winsper",
        "version": version,
        "source_revision": revision,
        "artifacts": artifacts,
        "build_environment_dependencies": dependencies,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a deterministic Winsper release inventory.")
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--installer", action="append", default=[], type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    inventory = build_inventory(
        args.package_root,
        args.installer,
        version=args.version,
        revision=args.revision,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
