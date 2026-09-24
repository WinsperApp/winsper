import json

import pytest

from voicepilot.config import RewriteConfig
from voicepilot.rewrite_backends import (
    LlamaServerCompletionBackend,
    OllamaCompletionBackend,
    create_completion_backend,
)


def test_completion_backend_factory_is_explicit():
    assert isinstance(
        create_completion_backend(RewriteConfig()),
        LlamaServerCompletionBackend,
    )
    assert isinstance(
        create_completion_backend(RewriteConfig(provider="ollama")),
        OllamaCompletionBackend,
    )
    with pytest.raises(RuntimeError, match="Unsupported rewrite provider: unknown"):
        create_completion_backend(RewriteConfig(provider="unknown"))


def test_ollama_backend_merges_lab_option_overrides(monkeypatch):
    import voicepilot.rewrite_backends as backends

    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def read():
            return b'{"response":"Cleaned."}'

    def respond(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(backends.urllib.request, "urlopen", respond)
    backend = OllamaCompletionBackend(
        RewriteConfig(provider="ollama", model="qwen3:8b"),
        option_overrides={"repeat_penalty": 1.05, "top_p": 0.8, "seed": 42},
    )

    assert backend.complete("prompt", num_predict=31) == "Cleaned."
    options = json.loads(requests[0][0].data)["options"]
    assert options == {
        "temperature": 0.2,
        "num_predict": 31,
        "repeat_penalty": 1.05,
        "top_p": 0.8,
        "seed": 42,
    }


def test_embedded_backend_passes_lab_option_overrides(monkeypatch):
    import voicepilot.rewrite_backends as backends

    created = []

    class Runtime:
        def __init__(self, config, *, completion_overrides=None):
            created.append((config, completion_overrides))

        def complete(self, prompt, *, num_predict):
            return f"{prompt}:{num_predict}"

        def close(self):
            return None

    monkeypatch.setattr(backends, "ManagedLlamaServer", Runtime)
    backend = LlamaServerCompletionBackend(
        RewriteConfig(provider="embedded"),
        option_overrides={"top_p": 0.8, "top_k": 20, "seed": 42},
    )

    assert backend.complete("prompt", num_predict=31) == "prompt:31"
    assert created[0][1] == {"top_p": 0.8, "top_k": 20, "seed": 42}


def test_embedded_verification_requires_real_generation(monkeypatch):
    import voicepilot.rewrite_backends as backends

    events: list[str] = []

    class Backend:
        def warm_up(self, _cancel_event=None):
            events.append("warm")
            return True

        def complete(self, _prompt, *, num_predict):
            assert num_predict == 8
            events.append("complete")
            return "READY"

        def close(self):
            events.append("close")

    monkeypatch.setattr(
        backends,
        "create_completion_backend",
        lambda _config: Backend(),
    )

    backends.verify_completion_backend(object())

    assert events == ["warm", "complete", "close"]


def test_embedded_verification_rejects_empty_generation(monkeypatch):
    import voicepilot.rewrite_backends as backends

    closed = False

    class Backend:
        def warm_up(self, _cancel_event=None):
            return True

        def complete(self, _prompt, *, num_predict):
            return " "

        def close(self):
            nonlocal closed
            closed = True

    monkeypatch.setattr(
        backends,
        "create_completion_backend",
        lambda _config: Backend(),
    )

    with pytest.raises(RuntimeError, match="did not produce a response"):
        backends.verify_completion_backend(object())

    assert closed
