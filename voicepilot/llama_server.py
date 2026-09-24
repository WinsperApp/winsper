from __future__ import annotations

import atexit
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .ai_catalog import default_local_ai_root, local_ai_root, polish_model, polish_model_path
from .ai_hardware import detect_ai_hardware
from .ai_runtime import installed_runtime_candidates, probe_runtime
from .config import RewriteConfig

LLAMA_SERVER_ALIAS = "winsper-polish"


class LlamaServerUnavailable(RuntimeError):
    pass


class LlamaServerModelMissing(RuntimeError):
    pass


class LlamaServerStartupCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class LlamaServerHealth:
    ready: bool
    managed: bool
    endpoint: str
    message: str
    detail: str = ""


class ManagedLlamaServer:
    """Own one authenticated loopback llama-server process."""

    def __init__(
        self,
        config: RewriteConfig,
        *,
        completion_overrides: dict[str, object] | None = None,
    ) -> None:
        self.config = config
        self.completion_overrides = dict(completion_overrides or {})
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._log = None
        self._endpoint = normalize_server_url(config.llama_server_url) if config.llama_server_url else ""
        self._api_key = config.llama_api_key.strip()
        self._last_completion_metrics: dict[str, float] = {}
        self._closed = False
        self._atexit_callback = self.close
        atexit.register(self._atexit_callback)

    @property
    def endpoint(self) -> str:
        with self._lock:
            return self._endpoint

    @property
    def api_key(self) -> str:
        with self._lock:
            return self._api_key

    @property
    def managed(self) -> bool:
        return not bool(self.config.llama_server_url.strip())

    @property
    def process_id(self) -> int | None:
        with self._lock:
            return self._process.pid if self._process is not None and self._process.poll() is None else None

    @property
    def last_completion_metrics(self) -> dict[str, float]:
        with self._lock:
            return dict(self._last_completion_metrics)

    def ensure_ready(self, cancel_event: threading.Event | None = None) -> str:
        with self._lock:
            if cancel_event is not None and cancel_event.is_set():
                raise LlamaServerStartupCancelled("Embedded Polish warm-up yielded to a user action.")
            if self._closed:
                raise LlamaServerUnavailable("Embedded Polish runtime is closed.")
            if self._endpoint and self._health_ready():
                return self._endpoint
            if not self.managed:
                raise LlamaServerUnavailable(
                    f"Configured llama-server is unavailable at {self._endpoint}."
                )
            self._stop_process()
            model = resolve_llama_model_path(self.config)
            failures: list[str] = []
            for executable, detected_device, detected_device_name in resolve_llama_launch_candidates(self.config):
                if cancel_event is not None and cancel_event.is_set():
                    raise LlamaServerStartupCancelled("Embedded Polish warm-up yielded to a user action.")
                port = reserve_loopback_port()
                self._endpoint = f"http://127.0.0.1:{port}"
                self._api_key = secrets.token_urlsafe(32)
                try:
                    self._start_process(executable, model, port, detected_device, detected_device_name)
                    self._wait_until_ready(cancel_event)
                except LlamaServerStartupCancelled:
                    raise
                except LlamaServerUnavailable as exc:
                    failures.append(f"{executable.parent.name}: {exc}")
                    continue
                return self._endpoint
            detail = " | ".join(failures)[-1200:]
            raise LlamaServerUnavailable(
                "No compatible embedded llama-server runtime could start."
                + (f" {detail}" if detail else "")
            )

    def complete(self, prompt: str, *, num_predict: int) -> str:
        payload = {
            "model": LLAMA_SERVER_ALIAS,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": num_predict,
            "temperature": self.config.temperature,
            "seed": self.config.seed,
            "chat_template_kwargs": {"enable_thinking": False},
            "stream": False,
        }
        payload.update(self.completion_overrides)
        for attempt in range(2):
            endpoint = self.ensure_ready()
            try:
                response = post_json(
                    f"{endpoint}/v1/chat/completions",
                    payload,
                    timeout_seconds=self.config.timeout_seconds,
                    api_key=self.api_key,
                )
                choices = response.get("choices") if isinstance(response, dict) else None
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    raise RuntimeError("llama-server returned no completion.")
                message = choices[0].get("message")
                if not isinstance(message, dict):
                    raise RuntimeError("llama-server returned an invalid chat completion.")
                self._last_completion_metrics = completion_metrics(response)
                return str(message.get("content") or "")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if not self.managed or attempt:
                    raise LlamaServerUnavailable(f"llama-server request failed: {exc}") from exc
                with self._lock:
                    self._stop_process()
        raise LlamaServerUnavailable("llama-server request failed.")

    def health(self) -> LlamaServerHealth:
        try:
            endpoint = self.ensure_ready()
        except (LlamaServerUnavailable, LlamaServerModelMissing) as exc:
            return LlamaServerHealth(False, self.managed, self.endpoint, str(exc))
        return LlamaServerHealth(True, self.managed, endpoint, "Ready")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._stop_process()
            atexit.unregister(self._atexit_callback)

    def _health_ready(self) -> bool:
        if self._process is not None and self._process.poll() is not None:
            return False
        try:
            payload = get_json(f"{self._endpoint}/health", timeout_seconds=0.35)
        except Exception:
            return False
        return isinstance(payload, dict) and payload.get("status") == "ok"

    def _start_process(
        self,
        executable: Path,
        model: Path,
        port: int,
        detected_device: str = "",
        detected_device_name: str = "",
    ) -> None:
        device = self.config.llama_device.strip() or detected_device
        command = [
            str(executable),
            "--model",
            str(model),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--alias",
            LLAMA_SERVER_ALIAS,
            "--parallel",
            "1",
            "--ctx-size",
            str(max(512, self.config.llama_context_size)),
            "--n-gpu-layers",
            normalize_gpu_layers(self.config.llama_gpu_layers, device),
            "--sleep-idle-seconds",
            str(max(-1, self.config.llama_idle_seconds)),
        ]
        if device and device.lower() != "auto":
            command.extend(["--device", device])
        if uses_amd_780m_vulkan_workaround(device, detected_device, detected_device_name):
            command.extend(["--flash-attn", "off"])
        if self.config.llama_threads > 0:
            command.extend(["--threads", str(self.config.llama_threads)])
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        environment = os.environ.copy()
        environment["LLAMA_API_KEY"] = self._api_key
        self._log = tempfile.TemporaryFile(mode="w+b")
        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(executable.parent),
                stdin=subprocess.DEVNULL,
                stdout=self._log,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creationflags,
                env=environment,
            )
        except OSError as exc:
            self._close_log()
            raise LlamaServerUnavailable(f"Could not start llama-server: {exc}") from exc

    def _wait_until_ready(self, cancel_event: threading.Event | None = None) -> None:
        deadline = time.monotonic() + max(1.0, self.config.llama_start_timeout_seconds)
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                self._stop_process()
                raise LlamaServerStartupCancelled("Embedded Polish warm-up yielded to a user action.")
            if self._process is None or self._process.poll() is not None:
                detail = self._read_log_tail()
                self._stop_process()
                raise LlamaServerUnavailable(
                    "llama-server exited while loading the model."
                    + (f" {detail}" if detail else "")
                )
            if self._health_ready():
                return
            time.sleep(0.1)
        detail = self._read_log_tail()
        self._stop_process()
        raise LlamaServerUnavailable(
            "llama-server model startup timed out."
            + (f" {detail}" if detail else "")
        )

    def _stop_process(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except OSError:
                    pass
        self._close_log()

    def _read_log_tail(self) -> str:
        if self._log is None:
            return ""
        try:
            self._log.flush()
            self._log.seek(0)
            text = self._log.read().decode("utf-8", errors="replace")
        except Exception:
            return ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return " | ".join(lines[-3:])[-600:]

    def _close_log(self) -> None:
        if self._log is not None:
            try:
                self._log.close()
            except Exception:
                pass
            self._log = None


def resolve_llama_server_path(config: RewriteConfig) -> Path:
    candidates = resolve_llama_launch_candidates(config)
    if candidates:
        return candidates[0][0]
    raise LlamaServerUnavailable(
        "Embedded llama-server is not installed. Install the Winsper AI runtime or select Ollama."
    )


def resolve_llama_launch_candidates(config: RewriteConfig) -> list[tuple[Path, str, str]]:
    if config.llama_server_path.strip():
        explicit = Path(os.path.expandvars(config.llama_server_path)).expanduser()
        if not explicit.is_file():
            return []
        resolved = explicit.resolve()
        device = config.llama_device.strip()
        return [(resolved, device, runtime_device_name(resolved, device))]
    result: list[tuple[Path, str, str]] = []
    seen: set[str] = set()
    try:
        hardware = detect_ai_hardware()
    except Exception:
        hardware = None
    if hardware is not None:
        roots: list[Path | None] = [None]
        default_root = default_local_ai_root()
        if local_ai_root().resolve() != default_root.resolve():
            # Model storage is user-configurable; the signed runtime may remain in
            # stable app data. Never strand Polish after moving only model files.
            roots.append(default_root)
        for root in roots:
            try:
                installations = installed_runtime_candidates(hardware, root=root)
            except Exception:
                installations = []
            for installation in installations:
                key = str(installation.executable).casefold()
                if key not in seen:
                    seen.add(key)
                    result.append((installation.executable, installation.device, installation.device_name))

    candidates = bundled_llama_server_paths()
    discovered = shutil.which("llama-server")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file():
            resolved = candidate.resolve()
            key = str(resolved).casefold()
            if key not in seen:
                seen.add(key)
                result.append((resolved, config.llama_device.strip(), ""))
    return result


def bundled_llama_server_paths() -> list[Path]:
    executable_dir = Path(sys.executable).resolve().parent
    package_dir = Path(__file__).resolve().parent
    candidates = [
        package_dir / "runtime" / "llama" / "llama-server.exe",
        executable_dir / "llama" / "llama-server.exe",
        executable_dir / "llama-server.exe",
    ]
    frozen_root = getattr(sys, "_MEIPASS", "")
    if frozen_root:
        root = Path(frozen_root)
        candidates.extend(
            [
                root / "voicepilot" / "runtime" / "llama" / "llama-server.exe",
                root / "llama" / "llama-server.exe",
            ]
        )
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def bundled_llama_server_available() -> bool:
    return bool(bundled_llama_server_paths())


def runtime_device_name(executable: Path, device: str) -> str:
    if not device or device.casefold() == "auto":
        return ""
    probe = probe_runtime(executable)
    if not probe.ready:
        return ""
    return next(
        (name for candidate, name in probe.devices if candidate.casefold() == device.casefold()),
        "",
    )


def uses_amd_780m_vulkan_workaround(
    device: str,
    detected_device: str,
    detected_device_name: str,
) -> bool:
    return (
        device.casefold().startswith("vulkan")
        and device.casefold() == detected_device.casefold()
        and "780m" in detected_device_name.casefold()
    )


def resolve_llama_model_path(config: RewriteConfig) -> Path:
    if config.llama_model_path.strip():
        path = Path(os.path.expandvars(config.llama_model_path)).expanduser()
    elif config.llama_model_id.strip():
        try:
            path = polish_model_path(polish_model(config.llama_model_id.strip()))
        except KeyError as exc:
            raise LlamaServerModelMissing(
                f"Unknown embedded Polish model: {config.llama_model_id.strip()}."
            ) from exc
    else:
        path = default_llama_model_path()
    if path.is_file():
        return path.resolve()
    raise LlamaServerModelMissing(
        f"Embedded Polish model is missing: {path}. Download it from Winsper Settings."
    )


def inspect_llama_server(
    config: RewriteConfig,
    timeout_seconds: float = 0.5,
) -> LlamaServerHealth:
    endpoint = normalize_server_url(config.llama_server_url)
    if endpoint:
        try:
            payload = get_json(f"{endpoint}/health", timeout_seconds=timeout_seconds)
        except Exception as exc:
            return LlamaServerHealth(
                False,
                False,
                endpoint,
                "Configured llama-server is unavailable",
                str(exc),
            )
        ready = isinstance(payload, dict) and payload.get("status") == "ok"
        return LlamaServerHealth(
            ready,
            False,
            endpoint,
            "Ready" if ready else "Configured llama-server is not ready",
        )
    try:
        executable = resolve_llama_server_path(config)
        model = resolve_llama_model_path(config)
    except (LlamaServerUnavailable, LlamaServerModelMissing) as exc:
        return LlamaServerHealth(False, True, "", str(exc))
    return LlamaServerHealth(
        True,
        True,
        "",
        "Embedded runtime installed",
        f"{executable} | {model}",
    )


def default_llama_model_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) / "Winsper" if base else Path.home() / ".winsper"
    return root / "models" / "polish" / "winsper-polish.gguf"


def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def normalize_server_url(value: str) -> str:
    return value.strip().rstrip("/")


def normalize_gpu_layers(value: str | int, device: str = "") -> str:
    normalized = str(value).strip().lower()
    if normalized == "auto" and device.casefold().startswith(("cuda", "vulkan", "metal")):
        # llama.cpp's automatic layer count can occasionally leave a model
        # split between CPU and GPU even when it fits. Full offload is both
        # faster and more predictable; runtime fallback still protects GPUs
        # that cannot load the selected model.
        return "all"
    if normalized in {"auto", "all"}:
        return normalized
    try:
        return str(max(0, int(normalized)))
    except ValueError:
        return "auto"


def completion_metrics(response: dict) -> dict[str, float]:
    metrics: dict[str, float] = {}
    timings = response.get("timings")
    if not isinstance(timings, dict):
        return metrics
    for key in (
        "prompt_n",
        "prompt_ms",
        "prompt_per_second",
        "predicted_n",
        "predicted_ms",
        "predicted_per_second",
    ):
        value = timings.get(key)
        if isinstance(value, (int, float)):
            metrics[f"llama_{key}"] = float(value)
    return metrics


def get_json(url: str, *, timeout_seconds: float) -> dict:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(
    url: str,
    payload: dict,
    *,
    timeout_seconds: float,
    api_key: str = "",
) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = read_server_error(exc)
        raise RuntimeError(f"llama-server request failed: {detail or exc}") from exc


def read_server_error(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8", errors="replace"))
    except Exception:
        return str(error)
    if not isinstance(payload, dict):
        return str(payload)
    detail = payload.get("error")
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail or payload)
