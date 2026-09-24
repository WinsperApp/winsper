from __future__ import annotations

import ctypes
import os
import platform
import subprocess
from ctypes import wintypes
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class AIGpu:
    name: str
    vendor: str
    memory_gb: float | None = None
    device: str = ""


@dataclass(frozen=True)
class AIHardware:
    architecture: str
    cpu: str
    ram_gb: float | None
    gpus: tuple[AIGpu, ...]

    @property
    def has_nvidia(self) -> bool:
        return any(gpu.vendor == "nvidia" for gpu in self.gpus)

    @property
    def has_gpu(self) -> bool:
        return bool(self.gpus)

    @property
    def has_amd_780m(self) -> bool:
        return any("780m" in gpu.name.casefold() for gpu in self.gpus)

    @property
    def has_reliable_vulkan_gpu(self) -> bool:
        return any(
            gpu.vendor == "nvidia"
            or (
                gpu.vendor in {"amd", "intel", "other"}
                and gpu.memory_gb is not None
                and gpu.memory_gb >= 2
            )
            for gpu in self.gpus
        )

    @property
    def best_vram_gb(self) -> float | None:
        values = [gpu.memory_gb for gpu in self.gpus if gpu.memory_gb is not None]
        return max(values) if values else None


@lru_cache(maxsize=1)
def detect_ai_hardware() -> AIHardware:
    """Return process-stable hardware without repeating expensive probes."""
    gpus = _windows_display_adapters() if os.name == "nt" else []
    nvidia = _nvidia_gpus()
    if nvidia:
        other = [gpu for gpu in gpus if gpu.vendor != "nvidia"]
        gpus = [*nvidia, *other]
    return AIHardware(
        architecture=normalize_architecture(platform.machine()),
        cpu=_cpu_name(),
        ram_gb=_ram_gb(),
        gpus=tuple(_dedupe_gpus(gpus)),
    )


@lru_cache(maxsize=1)
def detect_ai_hardware_quick() -> AIHardware:
    """Return local hardware metadata without launching external probes."""
    gpus = _windows_display_adapters() if os.name == "nt" else []
    return AIHardware(
        architecture=normalize_architecture(platform.machine()),
        cpu=_cpu_name(),
        ram_gb=_ram_gb(),
        gpus=tuple(_dedupe_gpus(gpus)),
    )


def available_ram_gb() -> float | None:
    """Return currently available physical memory without optional dependencies."""
    status = _memory_status()
    return status.ullAvailPhys / (1024**3) if status is not None else None


def normalize_architecture(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"amd64", "x86_64", "x64"}:
        return "x64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    return normalized or "unknown"


def gpu_vendor(name: str, provider: str = "") -> str:
    value = f"{name} {provider}".casefold()
    if "nvidia" in value:
        return "nvidia"
    if "advanced micro devices" in value or "amd" in value or "radeon" in value:
        return "amd"
    if "intel" in value:
        return "intel"
    return "other"


def _nvidia_gpus() -> list[AIGpu]:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode:
        return []
    result: list[AIGpu] = []
    for index, line in enumerate(completed.stdout.splitlines()):
        name, separator, raw_memory = line.rpartition(",")
        if not separator or not name.strip():
            continue
        try:
            memory_gb = float(raw_memory.strip()) / 1024
        except ValueError:
            memory_gb = None
        result.append(AIGpu(name=name.strip(), vendor="nvidia", memory_gb=memory_gb, device=f"CUDA{index}"))
    return result


def _windows_display_adapters() -> list[AIGpu]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    adapters: list[AIGpu] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError:
        return []
    with root:
        index = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if not subkey_name.isdigit():
                continue
            try:
                subkey = winreg.OpenKey(root, subkey_name)
            except OSError:
                continue
            with subkey:
                name = _registry_text(winreg, subkey, "DriverDesc")
                provider = _registry_text(winreg, subkey, "ProviderName")
                if not name or any(token in name.casefold() for token in ("remote", "virtual", "basic display")):
                    continue
                memory_gb = _registry_memory_gb(winreg, subkey)
                adapters.append(AIGpu(name=name, vendor=gpu_vendor(name, provider), memory_gb=memory_gb))
    return adapters


def _registry_text(winreg, key, name: str) -> str:
    try:
        value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value).strip()


def _registry_memory_gb(winreg, key) -> float | None:
    for name in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
        try:
            value, _kind = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if isinstance(value, int) and value > 0:
            return value / (1024**3)
        if isinstance(value, bytes) and value:
            return int.from_bytes(value[:8], "little") / (1024**3)
    return None


def _cpu_name() -> str:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                value, _kind = winreg.QueryValueEx(key, "ProcessorNameString")
                if str(value).strip():
                    return str(value).strip()
        except OSError:
            pass
    return platform.processor().strip() or "Unknown CPU"


def _ram_gb() -> float | None:
    status = _memory_status()
    if status is not None:
        return status.ullTotalPhys / (1024**3)
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        return page_size * pages / (1024**3)
    except (AttributeError, OSError, ValueError):
        return None


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _memory_status() -> _MemoryStatus | None:
    if os.name != "nt":
        return None
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status
    except (AttributeError, OSError):
        pass
    return None


def _dedupe_gpus(gpus: list[AIGpu]) -> list[AIGpu]:
    result: list[AIGpu] = []
    seen: set[str] = set()
    for gpu in gpus:
        key = gpu.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(gpu)
    return result
