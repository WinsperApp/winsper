from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .ai_hardware import AIHardware

LEGACY_POLISH_MODEL_ARTIFACTS = {
    "qwen3-4b-instruct-2507-q4km": (2497280480, "85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9"),
}
LLAMA_CPP_VERSION = "b9859"
DEFAULT_POLISH_MODEL_ID = "qwen3-4b-instruct-2507-q4km"
PRELOAD_RUNTIME_OVERHEAD = 1.2
PRELOAD_SYSTEM_RESERVE_GB = 4.0


@dataclass(frozen=True)
class RuntimeAsset:
    filename: str
    url: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class RuntimeBundle:
    id: str
    backend: str
    architecture: str
    assets: tuple[RuntimeAsset, ...]
    device_vendor: str = ""


@dataclass(frozen=True)
class PolishModel:
    id: str
    label: str
    filename: str
    url: str
    sha256: str
    size_bytes: int
    license: str
    min_runtime: str
    min_ram_gb: float
    min_vram_gb: float
    context_size: int
    languages: tuple[str, ...]
    tier: str
    reasoning: bool = False


def _release_asset(filename: str, sha256: str, size_bytes: int) -> RuntimeAsset:
    return RuntimeAsset(
        filename=filename,
        url=f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}/{filename}",
        sha256=sha256,
        size_bytes=size_bytes,
    )


RUNTIME_BUNDLES: tuple[RuntimeBundle, ...] = (
    RuntimeBundle(
        id="cuda12-x64",
        backend="cuda",
        architecture="x64",
        device_vendor="nvidia",
        assets=(
            _release_asset(
                "llama-b9859-bin-win-cuda-12.4-x64.zip",
                "05ae4f4f0b141a11c72dd18b58af28356725be99f2bdd1867e3787601b3de9ec",
                266_068_914,
            ),
            _release_asset(
                "cudart-llama-bin-win-cuda-12.4-x64.zip",
                "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
                391_443_627,
            ),
        ),
    ),
    RuntimeBundle(
        id="vulkan-x64",
        backend="vulkan",
        architecture="x64",
        assets=(
            _release_asset(
                "llama-b9859-bin-win-vulkan-x64.zip",
                "5e7794aa22ba34c8e223934b0b3e14cd441612f26e9f06a4a0e5f47b9e7f577b",
                32_154_376,
            ),
        ),
    ),
    RuntimeBundle(
        id="cpu-x64",
        backend="cpu",
        architecture="x64",
        assets=(
            _release_asset(
                "llama-b9859-bin-win-cpu-x64.zip",
                "c9aa80f233a7d1749341860f11723b912d4cfd6eec19434c3d00bba0abc9f85c",
                17_478_474,
            ),
        ),
    ),
    RuntimeBundle(
        id="cpu-arm64",
        backend="cpu",
        architecture="arm64",
        assets=(
            _release_asset(
                "llama-b9859-bin-win-cpu-arm64.zip",
                "c591ef794cb85c1ed868922521aa162d894f141d05cfb49050034b2ea1550d08",
                11_371_301,
            ),
        ),
    ),
)


POLISH_MODELS: tuple[PolishModel, ...] = (
    PolishModel(
        id="qwen2.5-1.5b-q4km",
        label="Qwen 2.5 1.5B",
        filename="qwen2.5-1.5b-instruct-q4_k_m.gguf",
        url=(
            "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
            "qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true"
        ),
        sha256="6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
        size_bytes=1_117_320_736,
        license="Apache-2.0",
        min_runtime=LLAMA_CPP_VERSION,
        min_ram_gb=4,
        min_vram_gb=0,
        context_size=4096,
        languages=("multilingual",),
        tier="fast",
    ),
    PolishModel(
        id="qwen3-4b-instruct-2507-q4km",
        label="Qwen 3 4B",
        filename="Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        url=(
            "https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/main/"
            "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf?download=true"
        ),
        sha256="2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e",
        size_bytes=2_497_280_736,
        license="Apache-2.0",
        min_runtime=LLAMA_CPP_VERSION,
        min_ram_gb=8,
        min_vram_gb=3,
        context_size=4096,
        languages=("multilingual",),
        tier="balanced",
    ),
    PolishModel(
        id="qwen3-8b-q4km",
        label="Qwen 3 8B",
        filename="Qwen3-8B-Q4_K_M.gguf",
        url=(
            "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/"
            "Qwen3-8B-Q4_K_M.gguf?download=true"
        ),
        sha256="d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785",
        size_bytes=5_027_783_488,
        license="Apache-2.0",
        min_runtime=LLAMA_CPP_VERSION,
        min_ram_gb=16,
        min_vram_gb=4,
        context_size=4096,
        languages=("multilingual",),
        tier="quality",
    ),
)

# Resolve explicit settings from older installs without advertising rejected
# models to new users or silently replacing their selection.
LEGACY_POLISH_MODELS: tuple[PolishModel, ...] = (
    PolishModel(
        id="llama3.2-3b-q4km",
        label="Llama 3.2 3B (legacy)",
        filename="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        url=(
            "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/"
            "Llama-3.2-3B-Instruct-Q4_K_M.gguf?download=true"
        ),
        sha256="6c1a2b41161032677be168d354123594c0e6e67d2b9227c84f296ad037c728ff",
        size_bytes=2_019_377_696,
        license="Llama-3.2",
        min_runtime=LLAMA_CPP_VERSION,
        min_ram_gb=8,
        min_vram_gb=3,
        context_size=4096,
        languages=("en", "de", "fr", "it", "pt", "hi", "es", "th"),
        tier="legacy",
    ),
)


def runtime_bundle(bundle_id: str) -> RuntimeBundle:
    for bundle in RUNTIME_BUNDLES:
        if bundle.id == bundle_id:
            return bundle
    raise KeyError(bundle_id)


def polish_model(model_id: str) -> PolishModel:
    for model in (*POLISH_MODELS, *LEGACY_POLISH_MODELS):
        if model.id == model_id:
            return model
    raise KeyError(model_id)


def runtime_candidates(hardware: AIHardware) -> list[RuntimeBundle]:
    candidates: list[RuntimeBundle] = []
    if hardware.architecture == "x64":
        if hardware.has_nvidia:
            candidates.append(runtime_bundle("cuda12-x64"))
        if hardware.has_reliable_vulkan_gpu:
            candidates.append(runtime_bundle("vulkan-x64"))
        candidates.append(runtime_bundle("cpu-x64"))
        if hardware.has_amd_780m and not hardware.has_reliable_vulkan_gpu:
            # Keep CPU boringly safe by default while still exposing the
            # device-scoped Vulkan workaround as an optional runtime.
            candidates.append(runtime_bundle("vulkan-x64"))
    elif hardware.architecture == "arm64":
        candidates.append(runtime_bundle("cpu-arm64"))
    return candidates


def recommended_polish_model(hardware: AIHardware) -> PolishModel:
    """Choose the safe everyday preset; Best remains an explicit quality choice."""
    ram = hardware.ram_gb or 0
    if ram >= 8:
        return polish_model(DEFAULT_POLISH_MODEL_ID)
    return polish_model("qwen2.5-1.5b-q4km")


# Kept for callers outside this package while the clearer name rolls out.
temporary_model_recommendation = recommended_polish_model


def polish_model_path(model: PolishModel, root: Path | None = None) -> Path:
    return (root or local_ai_root()) / "models" / model.id / model.filename


def compatible_polish_models(hardware: AIHardware) -> list[PolishModel]:
    ram = hardware.ram_gb or 0
    result: list[PolishModel] = []
    for model in POLISH_MODELS:
        if ram < model.min_ram_gb:
            continue
        # GPU memory controls offload speed, not whether the CPU fallback can run.
        result.append(model)
    return result


def should_preload_polish_model(
    model_id: str,
    *,
    model_path: str = "",
    available_memory_gb: float | None,
) -> bool:
    """Keep background warm-up inside a conservative physical-memory budget."""
    if model_path.strip():
        path = Path(model_path).expanduser()
        if not path.is_file():
            return False
        try:
            size_bytes = path.stat().st_size
        except OSError:
            return False
        safe_when_memory_unknown = size_bytes <= 2 * 1024**3
    else:
        try:
            selected = polish_model(model_id)
        except KeyError:
            return False
        size_bytes = selected.size_bytes
        safe_when_memory_unknown = selected.tier == "fast"

    if available_memory_gb is None:
        return safe_when_memory_unknown

    model_size_gb = size_bytes / (1024**3)
    required_memory_gb = model_size_gb * PRELOAD_RUNTIME_OVERHEAD + PRELOAD_SYSTEM_RESERVE_GB
    return available_memory_gb >= required_memory_gb


def default_local_ai_root() -> Path:
    """Return Winsper's stable app-data root for the embedded AI runtime."""

    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return (Path(base) / "Winsper" if base else Path.home() / ".winsper") / "local-ai"


def local_ai_root() -> Path:
    from .model_storage import configured_model_storage_root

    configured = configured_model_storage_root()
    if configured is not None:
        return configured / "polish"
    return default_local_ai_root()
