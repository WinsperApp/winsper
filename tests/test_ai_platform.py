from __future__ import annotations

import hashlib
import json
import sys
import threading
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import patch

from voicepilot.ai_catalog import (
    DEFAULT_POLISH_MODEL_ID,
    POLISH_MODELS,
    RuntimeAsset,
    RuntimeBundle,
    compatible_polish_models,
    polish_model,
    polish_model_path,
    runtime_candidates,
    should_preload_polish_model,
    recommended_polish_model,
)
from voicepilot.ai_hardware import AIGpu, AIHardware, detect_ai_hardware, gpu_vendor, normalize_architecture
from voicepilot.ai_runtime import (
    embedded_model_for_ollama_reference,
    install_polish_model,
    install_runtime,
    model_is_installed,
    ollama_model_candidate,
    probe_runtime,
    reusable_ollama_model,
    runtime_is_installed,
    runtime_probe_supports_bundle,
    select_runtime_device,
    uninstall_runtime,
)


def test_ollama_reference_maps_to_certified_embedded_model():
    model = embedded_model_for_ollama_reference("QWEN2.5:1.5B")

    assert model is not None
    assert model.id == "qwen2.5-1.5b-q4km"
    assert embedded_model_for_ollama_reference("unknown:latest") is None


def test_polish_models_have_pinned_installable_artifacts(tmp_path):
    model = POLISH_MODELS[0]
    source = tmp_path / model.filename
    source.write_bytes(b"GGUF")
    installable = replace(
        model,
        url=source.as_uri(),
        sha256=hashlib.sha256(b"GGUF").hexdigest(),
        size_bytes=4,
    )

    assert polish_model_path(model, tmp_path) == tmp_path / "models" / model.id / model.filename
    assert all(item.url.startswith("https://") and len(item.sha256) == 64 for item in POLISH_MODELS)
    assert install_polish_model(installable, root=tmp_path, reuse_ollama=False).read_bytes() == b"GGUF"


def test_polish_model_download_honors_pause_before_streaming(tmp_path):
    model = POLISH_MODELS[0]
    source = tmp_path / model.filename
    source.write_bytes(b"GGUF")
    installable = replace(
        model,
        url=source.as_uri(),
        sha256=hashlib.sha256(b"GGUF").hexdigest(),
        size_bytes=4,
    )

    class PauseOnce:
        def __init__(self) -> None:
            self.calls = 0

        def is_set(self) -> bool:
            self.calls += 1
            return self.calls == 1

    pause = PauseOnce()
    with patch("voicepilot.ai_runtime.time.sleep") as sleep:
        installed = install_polish_model(
            installable,
            root=tmp_path / "managed",
            pause_event=pause,
            reuse_ollama=False,
        )

    assert installed.read_bytes() == b"GGUF"
    assert pause.calls > 1
    sleep.assert_called_once_with(0.01)


def test_model_download_fails_before_network_when_disk_space_is_insufficient(tmp_path):
    model = replace(
        POLISH_MODELS[0],
        url="https://example.invalid/model.gguf",
        size_bytes=1024,
    )

    with patch("voicepilot.ai_runtime.shutil.disk_usage", return_value=SimpleNamespace(free=0)):
        with pytest.raises(RuntimeError, match="Not enough free disk space"):
            install_polish_model(model, root=tmp_path, reuse_ollama=False)


def test_consumer_polish_catalog_has_exact_three_tiers():
    assert [(model.tier, model.id) for model in POLISH_MODELS] == [
        ("fast", "qwen2.5-1.5b-q4km"),
        ("balanced", "qwen3-4b-instruct-2507-q4km"),
        ("quality", "qwen3-8b-q4km"),
    ]
    assert DEFAULT_POLISH_MODEL_ID == "qwen3-4b-instruct-2507-q4km"
    balanced = POLISH_MODELS[1]
    assert balanced.size_bytes == 2_497_280_736
    assert balanced.sha256 == "2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e"
    assert polish_model("llama3.2-3b-q4km").tier == "legacy"


def test_verified_ollama_model_is_reused_without_copying(tmp_path):
    payload = b"GGUF" + b"\0" * 16
    digest = hashlib.sha256(payload).hexdigest()
    model = replace(POLISH_MODELS[0], sha256=digest, size_bytes=len(payload))
    ollama_root = tmp_path / "ollama"
    blob = ollama_root / "models" / "blobs" / f"sha256-{digest}"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)
    manifest = (
        ollama_root
        / "models"
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / "qwen2.5"
        / "1.5b"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "layers": [
                    {
                        "mediaType": "application/vnd.ollama.image.model",
                        "digest": f"sha256:{digest}",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    managed_root = tmp_path / "managed"

    models_root = ollama_root / "models"
    assert ollama_model_candidate(model, ollama_root=models_root) == (
        blob.resolve(),
        digest,
        "qwen2.5:1.5b",
    )
    assert reusable_ollama_model(model, ollama_root=models_root) == (
        blob.resolve(),
        digest,
        "qwen2.5:1.5b",
    )
    installed = install_polish_model(model, root=managed_root, ollama_root=models_root)

    assert installed.samefile(blob)
    assert model_is_installed(model, managed_root)
    marker = json.loads((installed.parent / "installation.json").read_text(encoding="utf-8"))
    assert marker["source"] == "ollama"



def test_exact_legacy_ollama_artifact_remains_installed(tmp_path, monkeypatch):
    import voicepilot.ai_runtime as ai_runtime

    model = polish_model("qwen3-4b-instruct-2507-q4km")
    payload = b"GGUF-legacy"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setitem(
        ai_runtime.LEGACY_POLISH_MODEL_ARTIFACTS,
        model.id,
        (len(payload), digest),
    )
    root = tmp_path / "managed"
    path = polish_model_path(model, root)
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    (path.parent / "installation.json").write_text(
        json.dumps(
            {
                "model_id": model.id,
                "source": "ollama",
                "ollama_reference": "qwen3:4b-instruct",
                "source_size": len(payload),
                "sha256": digest,
            }
        ),
        encoding="utf-8",
    )

    assert model_is_installed(model, root)

def test_corrupt_ollama_model_is_not_reused(tmp_path):
    model = POLISH_MODELS[0]
    payload = b"GGUF" + b"\0" * 16
    claimed_digest = hashlib.sha256(b"different").hexdigest()
    models_root = tmp_path / "models"
    blob = models_root / "blobs" / f"sha256-{claimed_digest}"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)
    manifest = (
        models_root
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / "qwen2.5"
        / "1.5b"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "layers": [
                    {
                        "mediaType": "application/vnd.ollama.image.model",
                        "digest": f"sha256:{claimed_digest}",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert ollama_model_candidate(model, ollama_root=models_root) is None
    assert reusable_ollama_model(model, ollama_root=models_root) is None


def test_hardware_normalization_and_runtime_priority():
    hardware = AIHardware(
        architecture=normalize_architecture("AMD64"),
        cpu="Test CPU",
        ram_gb=16,
        gpus=(AIGpu("NVIDIA Test", "nvidia", 6, "CUDA0"),),
    )

    assert hardware.architecture == "x64"
    assert hardware.has_nvidia
    assert hardware.best_vram_gb == 6
    assert [bundle.id for bundle in runtime_candidates(hardware)] == [
        "cuda12-x64",
        "vulkan-x64",
        "cpu-x64",
    ]
    assert gpu_vendor("AMD Radeon 780M") == "amd"
    assert gpu_vendor("Intel Arc A770") == "intel"

    amd = AIHardware("x64", "CPU", 16, (AIGpu("AMD Radeon", "amd", 8),))
    intel = AIHardware("x64", "CPU", 16, (AIGpu("Intel Arc", "intel", 8),))
    amd_integrated = AIHardware("x64", "CPU", 16, (AIGpu("AMD Radeon 780M", "amd", 0.5),))
    cpu = AIHardware("x64", "CPU", 8, ())
    arm = AIHardware("arm64", "ARM CPU", 8, ())
    assert [bundle.id for bundle in runtime_candidates(amd)] == ["vulkan-x64", "cpu-x64"]
    assert [bundle.id for bundle in runtime_candidates(intel)] == ["vulkan-x64", "cpu-x64"]
    assert [bundle.id for bundle in runtime_candidates(amd_integrated)] == ["cpu-x64", "vulkan-x64"]
    assert [bundle.id for bundle in runtime_candidates(cpu)] == ["cpu-x64"]
    assert [bundle.id for bundle in runtime_candidates(arm)] == ["cpu-arm64"]


def test_hardware_inventory_is_cached_for_process_lifetime(monkeypatch):
    import voicepilot.ai_hardware as hardware

    calls = 0

    def nvidia_gpus():
        nonlocal calls
        calls += 1
        return [AIGpu("NVIDIA Test", "nvidia", 8, "CUDA0")]

    detect_ai_hardware.cache_clear()
    try:
        monkeypatch.setattr(hardware, "_nvidia_gpus", nvidia_gpus)
        first = detect_ai_hardware()
        second = detect_ai_hardware()
        assert first is second
        assert calls == 1
    finally:
        detect_ai_hardware.cache_clear()


def test_legacy_hardware_summary_uses_authoritative_inventory(monkeypatch):
    import voicepilot.hardware_detection as legacy

    source = AIHardware(
        "x64",
        "Test CPU",
        24,
        (
            AIGpu("NVIDIA Test", "nvidia", 8),
            AIGpu("Intel Arc Test", "intel", 4),
        ),
    )
    monkeypatch.setattr(legacy, "detect_ai_hardware", lambda: source)

    summary = legacy.detect_hardware()

    assert summary.cpu == "Test CPU"
    assert summary.ram_gb == 24
    assert summary.gpus == ("NVIDIA Test", "Intel Arc Test")
    assert summary.has_nvidia
    assert summary.has_intel_arc


def test_polish_recommendation_defaults_to_balanced_when_memory_allows():
    capable = AIHardware("x64", "CPU", 16, (AIGpu("NVIDIA RTX", "nvidia", 6),))
    low_resource = AIHardware("x64", "CPU", 8, ())
    constrained = AIHardware("x64", "CPU", 6, ())

    assert recommended_polish_model(capable).id == DEFAULT_POLISH_MODEL_ID
    assert recommended_polish_model(low_resource).id == DEFAULT_POLISH_MODEL_ID
    assert recommended_polish_model(constrained).id == "qwen2.5-1.5b-q4km"
    assert "qwen3-8b-q4km" in {model.id for model in compatible_polish_models(capable)}


def test_low_vram_gpu_does_not_hide_cpu_compatible_models():
    hardware = AIHardware("x64", "CPU", 16, (AIGpu("Integrated GPU", "amd", 0.5),))

    assert {model.id for model in compatible_polish_models(hardware)} == {
        "qwen2.5-1.5b-q4km",
        "qwen3-4b-instruct-2507-q4km",
        "qwen3-8b-q4km",
    }


def test_polish_preload_preserves_memory_headroom():
    assert should_preload_polish_model(
        "qwen2.5-1.5b-q4km",
        available_memory_gb=6,
    )
    assert not should_preload_polish_model(
        "qwen3-8b-q4km",
        available_memory_gb=7,
    )
    assert should_preload_polish_model(
        "qwen3-8b-q4km",
        available_memory_gb=12,
    )


def test_polish_preload_is_conservative_when_memory_or_model_is_unknown(tmp_path):
    assert should_preload_polish_model(
        "qwen2.5-1.5b-q4km",
        available_memory_gb=None,
    )
    assert not should_preload_polish_model(
        "qwen3-8b-q4km",
        available_memory_gb=None,
    )
    assert not should_preload_polish_model(
        "custom-model",
        available_memory_gb=32,
    )
    assert not should_preload_polish_model(
        "qwen2.5-1.5b-q4km",
        model_path=str(tmp_path / "missing.gguf"),
        available_memory_gb=32,
    )
    custom = tmp_path / "custom.gguf"
    custom.write_bytes(b"GGUF")
    assert should_preload_polish_model(
        "qwen3-8b-q4km",
        model_path=str(custom),
        available_memory_gb=5,
    )


def test_verified_runtime_install_and_uninstall(tmp_path):
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("llama-server.exe", b"runtime")
        package.writestr("llama-cli.exe", b"unused")
        package.writestr("backend.dll", b"dll")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    bundle = RuntimeBundle(
        id="test-cpu",
        backend="cpu",
        architecture="x64",
        assets=(
            RuntimeAsset(
                filename="runtime.zip",
                url=source.as_uri(),
                sha256=digest,
                size_bytes=source.stat().st_size,
            ),
        ),
    )
    root = tmp_path / "installed"

    installation = install_runtime(bundle, root=root)

    assert installation.executable.read_bytes() == b"runtime"
    assert not (installation.directory / "llama-cli.exe").exists()
    assert runtime_is_installed(bundle, root)
    assert not (root / "downloads" / "runtime.zip").exists()
    marker = json.loads((installation.directory / "installation.json").read_text(encoding="utf-8"))
    assert marker["assets"] == [digest]

    uninstall_runtime(bundle, root=root)
    assert not installation.directory.exists()



def test_runtime_install_honors_cancel_before_network(tmp_path):
    bundle = RuntimeBundle(
        id="cancelled-runtime",
        backend="cuda",
        architecture="x64",
        assets=(
            RuntimeAsset(
                filename="runtime.zip",
                url="https://example.invalid/runtime.zip",
                sha256="0" * 64,
                size_bytes=1,
            ),
        ),
    )
    cancelled = threading.Event()
    cancelled.set()
    partial = tmp_path / "downloads" / "runtime.zip.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"partial")
    archive = tmp_path / "downloads" / "runtime.zip"
    archive.write_bytes(b"completed asset from unfinished bundle")

    with pytest.raises(RuntimeError, match="Runtime download cancelled"):
        install_runtime(bundle, root=tmp_path, cancel_event=cancelled)

    assert not (tmp_path / "downloads" / "runtime.zip").exists()
    assert not partial.exists()


def test_uninstall_runtime_removes_resumable_download_cache(tmp_path):
    from voicepilot.ai_runtime import uninstall_runtime

    bundle = RuntimeBundle(
        id="test-cpu",
        backend="cpu",
        architecture="x64",
        assets=(RuntimeAsset("runtime.zip", "https://example.invalid/runtime.zip", "0" * 64, 1),),
    )
    cached = tmp_path / "downloads" / "runtime.zip"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"x")

    uninstall_runtime(bundle, root=tmp_path)

    assert not cached.exists()


def test_runtime_install_rejects_zip_traversal(tmp_path):
    source = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("../escape.txt", b"bad")
        package.writestr("llama-server.exe", b"runtime")
    bundle = RuntimeBundle(
        id="unsafe",
        backend="cpu",
        architecture="x64",
        assets=(
            RuntimeAsset(
                filename="unsafe.zip",
                url=source.as_uri(),
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                size_bytes=source.stat().st_size,
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="Unsafe path"):
        install_runtime(bundle, root=tmp_path / "installed")

    assert not (tmp_path / "escape.txt").exists()


def test_device_selection_prefers_matching_gpu():
    hardware = AIHardware(
        architecture="x64",
        cpu="CPU",
        ram_gb=16,
        gpus=(
            AIGpu("NVIDIA GeForce RTX 4050 Laptop GPU", "nvidia", 6),
            AIGpu("AMD Radeon 780M Graphics", "amd", 8),
        ),
    )
    probe = probe_runtime(Path("missing.exe"))
    assert not probe.ready

    from voicepilot.ai_runtime import RuntimeProbe

    ready = RuntimeProbe(
        True,
        "b9859",
        (
            ("Vulkan0", "AMD Radeon 780M Graphics"),
            ("Vulkan1", "NVIDIA GeForce RTX 4050 Laptop GPU"),
        ),
    )
    vulkan = RuntimeBundle("vk", "vulkan", "x64", ())
    cuda = RuntimeBundle("cuda", "cuda", "x64", ())
    assert select_runtime_device(vulkan, ready, hardware) == "Vulkan1"
    assert select_runtime_device(cuda, ready, hardware) == "CUDA0"


def test_accelerated_runtime_requires_matching_device_from_real_probe():
    from voicepilot.ai_runtime import RuntimeProbe

    cuda = RuntimeBundle("cuda", "cuda", "x64", ())
    vulkan = RuntimeBundle("vulkan", "vulkan", "x64", ())
    cpu = RuntimeBundle("cpu", "cpu", "x64", ())
    probe = RuntimeProbe(
        True,
        "test",
        (("Vulkan0", "AMD Radeon"),),
    )

    assert not runtime_probe_supports_bundle(cuda, probe)
    assert runtime_probe_supports_bundle(vulkan, probe)
    assert runtime_probe_supports_bundle(cpu, probe)


def test_successful_runtime_probe_is_cached_until_executable_changes(tmp_path, monkeypatch):
    import voicepilot.ai_runtime as runtime

    executable = tmp_path / "llama-server.exe"
    executable.write_bytes(b"runtime")
    calls = []

    def run(_executable, arguments, _timeout):
        calls.append(tuple(arguments))
        return "b9859" if arguments == ["--version"] else "Available devices:\nVulkan0: Test GPU"

    monkeypatch.setattr(runtime, "_run_runtime", run)

    first = probe_runtime(executable)
    second = probe_runtime(executable)
    assert first.ready and second == first
    assert calls == [("--version",), ("--list-devices",)]

    executable.write_bytes(b"changed runtime")
    assert probe_runtime(executable).ready
    assert calls == [
        ("--version",),
        ("--list-devices",),
        ("--version",),
        ("--list-devices",),
    ]


def test_failed_runtime_probe_is_retried(tmp_path, monkeypatch):
    import voicepilot.ai_runtime as runtime

    executable = tmp_path / "llama-server.exe"
    executable.write_bytes(b"runtime")
    calls = 0

    def fail(_executable, _arguments, _timeout):
        nonlocal calls
        calls += 1
        raise RuntimeError("not ready")

    monkeypatch.setattr(runtime, "_run_runtime", fail)

    assert not probe_runtime(executable).ready
    assert not probe_runtime(executable).ready
    assert calls == 2


def test_managed_server_falls_back_when_preferred_runtime_fails(tmp_path):
    from voicepilot.config import RewriteConfig
    from voicepilot.llama_server import LlamaServerUnavailable, ManagedLlamaServer

    cuda = tmp_path / "cuda" / "llama-server.exe"
    cpu = tmp_path / "cpu" / "llama-server.exe"
    model = tmp_path / "model.gguf"
    runtime = ManagedLlamaServer(RewriteConfig(provider="embedded"))
    starts = []

    def start(executable, _model, _port, device, device_name):
        starts.append((executable, device, device_name))
        if executable == cuda:
            raise LlamaServerUnavailable("CUDA unavailable")

    with (
        patch("voicepilot.llama_server.resolve_llama_model_path", return_value=model),
        patch(
            "voicepilot.llama_server.resolve_llama_launch_candidates",
            return_value=[(cuda, "CUDA0", "NVIDIA Test"), (cpu, "", "")],
        ),
        patch("voicepilot.llama_server.reserve_loopback_port", side_effect=[8101, 8102]),
        patch.object(runtime, "_start_process", side_effect=start),
        patch.object(runtime, "_wait_until_ready"),
    ):
        assert runtime.ensure_ready() == "http://127.0.0.1:8102"
    runtime.close()

    assert starts == [(cuda, "CUDA0", "NVIDIA Test"), (cpu, "", "")]


def test_frozen_bundle_runtime_is_discovered(tmp_path):
    from voicepilot.config import RewriteConfig
    from voicepilot.llama_server import (
        bundled_llama_server_available,
        bundled_llama_server_paths,
        resolve_llama_launch_candidates,
    )

    server = tmp_path / "voicepilot" / "runtime" / "llama" / "llama-server.exe"
    server.parent.mkdir(parents=True)
    server.write_bytes(b"runtime")

    with (
        patch.object(sys, "_MEIPASS", str(tmp_path), create=True),
        patch("voicepilot.llama_server.installed_runtime_candidates", return_value=[]),
        patch("voicepilot.llama_server.shutil.which", return_value=None),
    ):
        assert bundled_llama_server_available()
        assert server.resolve() in bundled_llama_server_paths()
        assert resolve_llama_launch_candidates(RewriteConfig()) == [(server.resolve(), "", "")]

def test_custom_model_storage_keeps_default_runtime_available(tmp_path):
    from types import SimpleNamespace

    from voicepilot.config import RewriteConfig
    from voicepilot.llama_server import resolve_llama_launch_candidates

    custom_root = tmp_path / "custom" / "polish"
    default_root = tmp_path / "app-data" / "local-ai"
    executable = default_root / "runtime" / "llama-server.exe"
    installation = SimpleNamespace(
        executable=executable,
        device="CUDA0",
        device_name="Test GPU",
    )
    calls = []

    def installed(_hardware, *, root=None):
        calls.append(root)
        return [installation] if root == default_root else []

    with (
        patch("voicepilot.llama_server.detect_ai_hardware", return_value=object()),
        patch("voicepilot.llama_server.local_ai_root", return_value=custom_root),
        patch("voicepilot.llama_server.default_local_ai_root", return_value=default_root),
        patch("voicepilot.llama_server.installed_runtime_candidates", side_effect=installed),
        patch("voicepilot.llama_server.bundled_llama_server_paths", return_value=[]),
        patch("voicepilot.llama_server.shutil.which", return_value=None),
    ):
        assert resolve_llama_launch_candidates(RewriteConfig()) == [
            (executable, "CUDA0", "Test GPU")
        ]

    assert calls == [None, default_root]
