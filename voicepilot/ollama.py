from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .config import RewriteConfig

DEFAULT_OLLAMA_MODELS: tuple[str, ...] = ("qwen2.5:1.5b", "llama3.2:1b", "gemma3:1b")
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"


class OllamaUnavailable(RuntimeError):
    pass


class OllamaModelMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class OllamaHealth:
    reachable: bool
    model_available: bool
    model: str
    models: tuple[str, ...]
    tags_url: str
    latency_ms: int | None = None
    message: str = ""
    detail: str = ""

    @property
    def ready(self) -> bool:
        return self.reachable and self.model_available

    @property
    def pull_command(self) -> str:
        return f"ollama pull {self.model}"


def check_ollama_health(config: RewriteConfig, timeout_seconds: float = 1.5) -> OllamaHealth:
    model = (config.model or "").strip()
    tags_url = ollama_tags_url(config.ollama_url)
    request = urllib.request.Request(tags_url, method="GET")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError:
        if not ollama_cli_available():
            return OllamaHealth(
                reachable=False,
                model_available=False,
                model=model,
                models=(),
                tags_url=tags_url,
                message="Ollama is not reachable",
                detail=(
                    "Open Ollama, then check again. If it is not installed, "
                    f"get it from {OLLAMA_DOWNLOAD_URL}."
                ),
            )
        return OllamaHealth(
            reachable=False,
            model_available=False,
            model=model,
            models=(),
            tags_url=tags_url,
            message="Ollama is installed but not running",
            detail="Start Ollama, then check again.",
        )
    except UnicodeError as exc:
        return OllamaHealth(
            reachable=False,
            model_available=False,
            model=model,
            models=(),
            tags_url=tags_url,
            message="Ollama is unavailable",
            detail=str(exc),
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    models = parse_ollama_models(body)
    available = model_available(model, models)
    if not models:
        return OllamaHealth(
            reachable=True,
            model_available=False,
            model=model,
            models=(),
            tags_url=tags_url,
            latency_ms=latency_ms,
            message="Ollama is running, but no local models were found",
            detail=f"Run: ollama pull {model}" if model else "Pull a rewrite model in Ollama.",
        )
    if not available:
        return OllamaHealth(
            reachable=True,
            model_available=False,
            model=model,
            models=tuple(models),
            tags_url=tags_url,
            latency_ms=latency_ms,
            message=f"Ollama is running, but {model} is not installed",
            detail=f"Run: ollama pull {model}" if model else "Choose an installed model.",
        )
    return OllamaHealth(
        reachable=True,
        model_available=True,
        model=model,
        models=tuple(models),
        tags_url=tags_url,
        latency_ms=latency_ms,
        message=f"Ready: {model}",
        detail=f"Ollama responded in {latency_ms} ms.",
    )


def parse_ollama_models(body: str) -> list[str]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    raw_models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        return []
    names: list[str] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            value = str(item.get(key, "")).strip()
            if value and value not in names:
                names.append(value)
    return names


def ollama_cli_available() -> bool:
    return shutil.which("ollama") is not None


def model_available(requested: str, installed: list[str] | tuple[str, ...]) -> bool:
    requested = requested.strip()
    if not requested:
        return False
    requested_base = requested.split(":", 1)[0]
    for model in installed:
        candidate = model.strip()
        if candidate == requested:
            return True
        if ":" not in requested and candidate.split(":", 1)[0] == requested_base:
            return True
    return False


def format_ollama_health(health: OllamaHealth) -> str:
    if not health.reachable:
        return f"Unavailable: {health.detail}" if health.detail else "Unavailable"
    if not health.models:
        return "Reachable, no models listed"
    preview = ", ".join(health.models[:4])
    suffix = "" if len(health.models) <= 4 else f", +{len(health.models) - 4} more"
    status = "model ready" if health.model_available else f"{health.model} missing"
    latency = f", {health.latency_ms} ms" if health.latency_ms is not None else ""
    return f"Reachable ({preview}{suffix}; {status}{latency})"


def ollama_tags_url(generate_url: str) -> str:
    parsed = urllib.parse.urlparse(generate_url)
    if not parsed.scheme or not parsed.netloc:
        return "http://127.0.0.1:11434/api/tags"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/api/tags", "", "", ""))
