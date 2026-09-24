from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .ai_catalog import PolishModel, polish_model


_OLLAMA_MODEL_REFERENCES = {
    "qwen2.5-1.5b-q4km": "qwen2.5:1.5b",
    "qwen3-4b-instruct-2507-q4km": "qwen3:4b-instruct",
    "qwen3-8b-q4km": "qwen3:8b",
    "llama3.2-3b-q4km": "llama3.2:3b",
}


def ollama_model_reference(model_id: str) -> str | None:
    return _OLLAMA_MODEL_REFERENCES.get(model_id)


def embedded_model_for_ollama_reference(reference: str) -> PolishModel | None:
    """Return the certified embedded model matching an Ollama model name."""
    normalized = reference.strip().casefold()
    if not normalized:
        return None
    for model_id, ollama_reference in _OLLAMA_MODEL_REFERENCES.items():
        if ollama_reference.casefold() == normalized:
            return polish_model(model_id)
    return None


def ollama_model_candidate(
    model: PolishModel,
    *,
    ollama_root: Path | None = None,
) -> tuple[Path, str, str] | None:
    """Resolve an approved Ollama model layer without hashing it."""
    reference = ollama_model_reference(model.id)
    if reference is None:
        return None
    name, tag = reference.split(":", 1)
    root = (ollama_root or (Path.home() / ".ollama" / "models")).resolve()
    manifest = root / "manifests" / "registry.ollama.ai" / "library" / name / tag
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        layer = next(item for item in payload.get("layers", ()) if item.get("mediaType") == "application/vnd.ollama.image.model")
        digest = str(layer["digest"])
    except (OSError, ValueError, KeyError, StopIteration, TypeError, json.JSONDecodeError):
        return None
    if not digest.startswith("sha256:") or len(digest) != 71:
        return None
    expected = digest.removeprefix("sha256:")
    if any(character not in "0123456789abcdef" for character in expected):
        return None
    if expected != model.sha256:
        return None
    blob = (root / "blobs" / digest.replace(":", "-", 1)).resolve()
    if root not in blob.parents or not blob.is_file():
        return None
    try:
        if blob.stat().st_size != model.size_bytes or not has_gguf_magic(blob):
            return None
    except OSError:
        return None
    return blob, expected, reference


def reusable_ollama_model(
    model: PolishModel,
    *,
    ollama_root: Path | None = None,
) -> tuple[Path, str, str] | None:
    """Resolve an approved Ollama model layer after verifying its content digest."""
    candidate = ollama_model_candidate(model, ollama_root=ollama_root)
    if candidate is None:
        return None
    blob, expected, reference = candidate
    try:
        if sha256(blob) != expected:
            return None
    except OSError:
        return None
    return blob, expected, reference


def has_gguf_magic(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(4) == b"GGUF"
    except OSError:
        return False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
