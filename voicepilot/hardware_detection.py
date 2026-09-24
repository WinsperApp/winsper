from __future__ import annotations

from .ai_hardware import detect_ai_hardware
from .speech_model_catalog import HardwareSummary


def cuda_runtime_available() -> bool:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count()) > 0
    except (ImportError, OSError, RuntimeError, ValueError):
        return False


def detect_hardware() -> HardwareSummary:
    hardware = detect_ai_hardware()
    gpu_names = tuple(gpu.name for gpu in hardware.gpus)
    return HardwareSummary(
        cpu=hardware.cpu,
        ram_gb=hardware.ram_gb,
        gpus=gpu_names,
        has_nvidia=hardware.has_nvidia,
        has_intel_arc=any(gpu.vendor == "intel" and "arc" in gpu.name.casefold() for gpu in hardware.gpus),
    )
