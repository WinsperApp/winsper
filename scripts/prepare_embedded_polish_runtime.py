from __future__ import annotations

import argparse
import platform
import shutil
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from voicepilot.ai_catalog import runtime_bundle  # noqa: E402
from voicepilot.ai_hardware import normalize_architecture  # noqa: E402
from voicepilot.ai_runtime import (  # noqa: E402
    install_runtime,
    runtime_directory,
    runtime_is_installed,
)


def prepare_runtime(output: Path, cache_root: Path, architecture: str | None = None) -> Path:
    target_architecture = normalize_architecture(architecture or platform.machine())
    bundle_id = {
        "x64": "cpu-x64",
        "arm64": "cpu-arm64",
    }.get(target_architecture)
    if bundle_id is None:
        raise RuntimeError(f"No embedded Polish runtime is published for {target_architecture}.")

    bundle = runtime_bundle(bundle_id)
    if not runtime_is_installed(bundle, cache_root):
        install_runtime(bundle, root=cache_root)

    source = runtime_directory(bundle, cache_root)
    staging = output.parent / f".{output.name}.{uuid.uuid4().hex}.preparing"
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, staging)
        if output.exists():
            shutil.rmtree(output)
        staging.replace(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output / "llama-server.exe"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare the pinned CPU llama-server bundled with Winsper."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--architecture", choices=("x64", "arm64"))
    args = parser.parse_args()
    executable = prepare_runtime(
        args.output.resolve(),
        args.cache_root.resolve(),
        args.architecture,
    )
    print(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
