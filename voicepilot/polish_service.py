from __future__ import annotations

import logging
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

from .ai_catalog import polish_model
from .config import ProfileStyle, RewriteConfig
from .destination import DestinationContext, apply_destination_postprocessing, normalize_destination_surface
from .polish_prompts import (
    build_polish_prompt,
    build_rewrite_prompt,
    clean_model_output,
    no_selection_operation,
    prompt_profile_for_model,
    PromptProfile,
    POLISH_PROMPT_VERSION,
)
from .polish_validation import (
    apply_cpp_file_aliases,
    ensure_question_punctuation,
    looks_like_degenerate_output,
    prepare_polish_input,
)
from .rewrite_backends import CompletionBackend, create_completion_backend
from .self_corrections import resolve_explicit_self_corrections
from .spoken_formatting import normalize_spoken_terminal_command, normalize_spoken_urls


LOGGER = logging.getLogger(__name__)
_WORD_PATTERN = re.compile(r"(?<!\w)[\w'-]+(?!\w)", re.UNICODE)


def protect_vocabulary_spellings(source: str, output: str, vocabulary: list[str]) -> str:
    """Canonicalize dictionary terms without adding terms absent from source."""
    result = output
    terms = []
    seen: set[str] = set()
    for value in vocabulary:
        term = str(value).strip()
        key = term.casefold()
        if not term or key in seen:
            continue
        seen.add(key)
        terms.append(term)

    for term in terms:
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        source_count = len(pattern.findall(source))
        result = pattern.sub(lambda _match, canonical=term: canonical, result)
        result_count = len(pattern.findall(result))
        if source_count == 0 or result_count >= source_count or " " in term or len(term) < 4:
            continue

        candidates: dict[str, tuple[str, int, float]] = {}
        for match in _WORD_PATTERN.finditer(result):
            candidate = match.group(0)
            key = candidate.casefold()
            if key in candidates or key in seen or key[:1] != term.casefold()[:1]:
                continue
            if abs(len(candidate) - len(term)) > 1:
                continue
            score = SequenceMatcher(None, key, term.casefold()).ratio()
            if score < 0.90:
                continue
            count = len(re.findall(rf"(?<!\w){re.escape(candidate)}(?!\w)", result, re.IGNORECASE))
            if count <= source_count:
                candidates[key] = (candidate, count, score)

        ranked = sorted(candidates.values(), key=lambda item: item[2], reverse=True)
        if not ranked or (len(ranked) > 1 and ranked[0][2] - ranked[1][2] < 0.04):
            continue
        candidate = ranked[0][0]
        result = re.sub(
            rf"(?<!\w){re.escape(candidate)}(?!\w)",
            lambda _match, canonical=term: canonical,
            result,
            flags=re.IGNORECASE,
        )
    return result


def unusable_completion_reason(output: str) -> str:
    """Catch only catastrophic output; never trigger another model call."""
    if not output.strip():
        return "empty"
    normalized = output.casefold()
    if "```" in output or ("<<<" in output and ">>>" in output) or "prompt version:" in normalized:
        return "prompt_leak"
    if looks_like_degenerate_output(output):
        return "degenerate"
    return ""


def rewrite_completion_budget(text: str, instruction: str) -> int:
    """Bound selected-text output without constraining the instruction vocabulary."""
    estimated_tokens = (len(text) + len(instruction) + 2) // 3
    return min(900, max(192, estimated_tokens * 2 + 64))


def polish_completion_budget(text: str) -> int:
    """Polish preserves meaning, so output should stay close to the source size."""
    estimated_tokens = (len(text) + 2) // 3
    return min(700, max(128, estimated_tokens * 2 + 48))


def estimated_prompt_tokens(value: str) -> int:
    """Conservative tokenizer-independent guard for the fixed local context."""
    ascii_characters = sum(character.isascii() for character in value)
    non_ascii_characters = len(value) - ascii_characters
    return (ascii_characters + 2) // 3 + non_ascii_characters


class TextRewriter:
    def __init__(
        self,
        config: RewriteConfig,
        vocabulary: list[str],
        backend: CompletionBackend | None = None,
    ) -> None:
        self.config = config
        self.vocabulary = vocabulary
        self.backend = backend
        self._backend_lock = threading.RLock()
        self._warm_up_cancel_event: threading.Event | None = None
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def rewrite(
        self,
        text: str,
        instruction: str,
        profile: ProfileStyle | None = None,
        app_label: str = "",
        destination: DestinationContext | None = None,
    ) -> str:
        target_destination = destination or DestinationContext()
        prompt_profile = self.prompt_profile()
        prompt = build_rewrite_prompt(
            text,
            instruction,
            self.vocabulary,
            profile,
            app_label,
            destination,
            prompt_profile=prompt_profile,
        )
        completion_budget = rewrite_completion_budget(text, instruction)
        self._require_prompt_capacity(prompt, completion_budget, operation="selected rewrite")
        output = apply_cpp_file_aliases(
            self._complete(prompt, num_predict=completion_budget),
            self.vocabulary,
        )
        output = protect_vocabulary_spellings(
            text,
            output,
            [*self.vocabulary, *(profile.vocabulary if profile is not None else [])],
        )
        reason = unusable_completion_reason(output)
        if reason:
            LOGGER.error(
                "polish_validation_rejected mode=selection prompt_version=%s prompt_profile=%s codes=%s",
                POLISH_PROMPT_VERSION,
                prompt_profile,
                reason,
            )
            raise RuntimeError(f"Local AI returned unusable output ({reason}). Nothing was replaced.")
        return normalize_destination_surface(output, target_destination)

    def polish(
        self,
        text: str,
        profile: ProfileStyle | None = None,
        app_label: str = "",
        destination: DestinationContext | None = None,
        language: str = "",
    ) -> str:
        target_destination = destination or DestinationContext()
        prompt_profile = self.prompt_profile()
        text = normalize_spoken_urls(text)
        if target_destination.kind == "terminal":
            text = normalize_spoken_terminal_command(text)
        correction = resolve_explicit_self_corrections(text, language)
        # Keep the model input intact. A high-confidence local correction is
        # prepared only as a zero-latency fallback for catastrophic output.
        model_input = prepare_polish_input(text, app_label)
        operation = no_selection_operation(model_input, target_destination)
        fallback_source = correction.text if correction.has_safe_fallback else text
        fallback = prepare_polish_input(fallback_source, app_label)
        if target_destination.kind != "terminal":
            fallback = ensure_question_punctuation(fallback)
        prompt = build_polish_prompt(
            model_input,
            self.vocabulary,
            profile,
            app_label,
            destination,
            language=language,
            prompt_profile=prompt_profile,
            revision_reference=correction.text if correction.has_safe_fallback else "",
        )
        completion_budget = polish_completion_budget(model_input)
        if not self._prompt_has_capacity(prompt, completion_budget):
            LOGGER.warning(
                "polish_validation_fallback mode=no_selection prompt_version=%s prompt_profile=%s codes=context_limit",
                POLISH_PROMPT_VERSION,
                prompt_profile,
            )
            return apply_destination_postprocessing(fallback, target_destination)
        output = apply_cpp_file_aliases(
            self._complete(prompt, num_predict=completion_budget),
            self.vocabulary,
        )
        output = protect_vocabulary_spellings(
            model_input,
            output,
            [*self.vocabulary, *(profile.vocabulary if profile is not None else [])],
        )
        reason = unusable_completion_reason(output)
        if reason:
            LOGGER.warning(
                "polish_validation_fallback mode=no_selection prompt_version=%s prompt_profile=%s codes=%s",
                POLISH_PROMPT_VERSION,
                prompt_profile,
                reason,
            )
            return apply_destination_postprocessing(fallback, target_destination)
        if operation == "preserve":
            output = ensure_question_punctuation(output)
        return apply_destination_postprocessing(output, target_destination)

    def _complete(self, prompt: str, num_predict: int) -> str:
        with self._backend_lock:
            backend = self._ensure_backend()
            return clean_model_output(backend.complete(prompt, num_predict=num_predict))

    def _prompt_has_capacity(self, prompt: str, num_predict: int) -> bool:
        context_size = max(512, int(self.config.llama_context_size))
        return estimated_prompt_tokens(prompt) + num_predict + 192 <= context_size

    def _require_prompt_capacity(self, prompt: str, num_predict: int, *, operation: str) -> None:
        if self._prompt_has_capacity(prompt, num_predict):
            return
        LOGGER.warning(
            "polish_validation_rejected mode=selection prompt_version=%s codes=context_limit",
            POLISH_PROMPT_VERSION,
        )
        raise RuntimeError(f"The {operation} is too long for the configured local model context. Nothing was replaced.")

    def warm_up(self, cancel_event: threading.Event | None = None) -> bool:
        cancel_event = cancel_event or threading.Event()
        if cancel_event.is_set():
            return False
        with self._backend_lock:
            if self._closed or cancel_event.is_set():
                return False
            backend = self._ensure_backend()
            self._warm_up_cancel_event = cancel_event
        try:
            warm_up = getattr(backend, "warm_up", None)
            if warm_up is None:
                return True
            return warm_up(cancel_event=cancel_event) is not False
        finally:
            with self._backend_lock:
                if self._warm_up_cancel_event is cancel_event:
                    self._warm_up_cancel_event = None

    def cancel_warm_up(self) -> None:
        cancel_event = self._warm_up_cancel_event
        if cancel_event is not None:
            cancel_event.set()

    def model_label(self) -> str:
        """Return configured rewrite backend/model, rather than stale Ollama metadata."""
        provider = self.config.provider.strip().casefold()
        if provider == "ollama":
            return f"Ollama \u00b7 {self.config.model.strip() or 'unknown model'}"
        if provider in {"embedded", "llama_cpp", "llama_server"}:
            model_id = self.config.llama_model_id.strip()
            try:
                label = polish_model(model_id).label
            except KeyError:
                label = Path(self.config.llama_model_path).expanduser().name or model_id or "unknown model"
            return f"Embedded llama.cpp \u00b7 {label}"
        return f"{self.config.provider.strip() or 'Unknown backend'} \u00b7 unknown model"

    def prompt_profile(self) -> PromptProfile:
        """Return explicit instruction profile or infer it from configured model capacity."""
        provider = self.config.provider.strip().casefold()
        if provider in {"embedded", "llama_cpp", "llama_server"}:
            model_reference = self.config.llama_model_id.strip() or Path(self.config.llama_model_path).name
        else:
            model_reference = self.config.model.strip()
        return prompt_profile_for_model(model_reference, self.config.prompt_profile)

    @staticmethod
    def prompt_version() -> str:
        """Expose diagnostic version without placing it in model-visible instructions."""
        return POLISH_PROMPT_VERSION

    def _ensure_backend(self) -> CompletionBackend:
        with self._backend_lock:
            if self._closed:
                raise RuntimeError("Polish backend is closed.")
            if self.backend is None:
                self.backend = create_completion_backend(self.config)
            return self.backend

    def close(self) -> None:
        self.cancel_warm_up()
        with self._backend_lock:
            self._closed = True
            backend = self.backend
            self.backend = None
        close = getattr(backend, "close", None)
        if close is not None:
            close()
