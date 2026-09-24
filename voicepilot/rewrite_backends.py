from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Protocol

from .config import RewriteConfig
from .llama_server import LlamaServerStartupCancelled, ManagedLlamaServer, inspect_llama_server
from .ollama import OllamaModelMissing, OllamaUnavailable, check_ollama_health


class CompletionBackend(Protocol):
    """Provider-neutral text completion used by Polish and Rewrite."""

    def complete(self, prompt: str, *, num_predict: int) -> str: ...

    def close(self) -> None: ...

    def warm_up(self, cancel_event: threading.Event | None = None) -> bool: ...


class OllamaCompletionBackend:
    def __init__(self, config: RewriteConfig, *, option_overrides: dict[str, object] | None = None) -> None:
        self.config = config
        self.option_overrides = dict(option_overrides or {})

    def complete(self, prompt: str, *, num_predict: int) -> str:
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": num_predict,
                "seed": self.config.seed,
            },
            "keep_alive": self.config.ollama_keep_alive,
        }
        payload["options"].update(self.option_overrides)
        request = urllib.request.Request(
            self.config.ollama_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = read_http_error(exc)
            if "model" in detail.lower() and any(word in detail.lower() for word in ["not found", "pull", "missing"]):
                raise OllamaModelMissing(f"Model missing. Run: ollama pull {self.config.model}") from exc
            raise RuntimeError(f"Ollama request failed: {detail or exc}") from exc
        except TimeoutError as exc:
            raise OllamaUnavailable("Ollama timed out. Try a smaller model or increase the rewrite timeout.") from exc
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            if "timed out" in reason.lower():
                raise OllamaUnavailable("Ollama timed out. Try a smaller model or increase the rewrite timeout.") from exc
            raise OllamaUnavailable("Ollama is not running. Start Ollama to use Polish.") from exc

        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama returned an invalid JSON response.") from exc
        return str(result.get("response") or "")

    def close(self) -> None:
        return

    def warm_up(self, cancel_event: threading.Event | None = None) -> bool:
        return cancel_event is None or not cancel_event.is_set()


class LlamaServerCompletionBackend:
    def __init__(self, config: RewriteConfig, *, option_overrides: dict[str, object] | None = None) -> None:
        self.runtime = ManagedLlamaServer(config, completion_overrides=option_overrides)

    def complete(self, prompt: str, *, num_predict: int) -> str:
        return self.runtime.complete(prompt, num_predict=num_predict)

    def close(self) -> None:
        self.runtime.close()

    def warm_up(self, cancel_event: threading.Event | None = None) -> bool:
        try:
            self.runtime.ensure_ready(cancel_event)
        except LlamaServerStartupCancelled:
            return False
        return True


def create_completion_backend(config: RewriteConfig) -> CompletionBackend:
    provider = config.provider.strip().lower()
    if provider == "ollama":
        return OllamaCompletionBackend(config)
    if provider in {"embedded", "llama_cpp", "llama_server"}:
        return LlamaServerCompletionBackend(config)
    raise RuntimeError(f"Unsupported rewrite provider: {config.provider}")


def verify_completion_backend(
    config: RewriteConfig,
    cancel_event: threading.Event | None = None,
) -> None:
    """Prove that a configured backend can start and generate real output."""
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Polish setup was cancelled.")

    backend = create_completion_backend(config)
    try:
        if not backend.warm_up(cancel_event):
            raise RuntimeError("Polish setup was cancelled.")
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Polish setup was cancelled.")
        response = backend.complete(
            "Reply with exactly READY and nothing else.",
            num_predict=8,
        ).strip()
        if not response:
            raise RuntimeError(
                "The local writing model started but did not produce a response."
            )
    finally:
        backend.close()


def check_rewrite_backend_health(config: RewriteConfig, timeout_seconds: float = 1.5):
    provider = config.provider.strip().lower()
    if provider == "ollama":
        return check_ollama_health(config, timeout_seconds=timeout_seconds)
    if provider in {"embedded", "llama_cpp", "llama_server"}:
        return inspect_llama_server(config, timeout_seconds=timeout_seconds)
    raise RuntimeError(f"Unsupported rewrite provider: {config.provider}")


def read_http_error(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace").strip()
    except Exception:
        body = ""
    if not body:
        return str(error)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(payload, dict):
        return str(payload.get("error") or payload)
    return body
