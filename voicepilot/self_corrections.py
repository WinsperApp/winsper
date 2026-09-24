from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SelfCorrectionResolution:
    text: str
    removed_phrases: tuple[str, ...] = ()
    required_phrases: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.removed_phrases)

    @property
    def has_safe_fallback(self) -> bool:
        """Whether both sides of a correction were identified with confidence."""
        return self.changed and bool(self.required_phrases)


_WEEKDAY = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
_RELATIVE_DAY = r"(?:today|tomorrow|yesterday)"
_NUMBER_PHRASE = r"\d+(?:\.\d+)?(?:\s+(?:lakhs?|crores?|million|billion|thousand|hundred|percent|%))?"
_SLOT_MARKER = re.compile(
    r"(?P<separator>\s*[,;:\u2014-]\s*)"
    r"(?P<marker>sorry(?:\s*,?\s*i\s+mean)?|i\s+mean|actually|or\s+rather)"
    r"\s+(?P<replacement>[^,;.!?]+)"
    r"(?P<ending>[.!?]?)\s*$",
    re.IGNORECASE,
)
_CANCEL_MARKER = re.compile(
    r"\b(?P<lead_no>no\s*,?\s*)?(?:do\s+not|don't)\s+say\s+that\b"
    r"\s*(?P<separator>[,;:.!?-]*)\s*"
    r"(?P<qualifier>just\s+|instead\s+)?(?P<say>say\s+)?(?P<replacement>.+)$",
    re.IGNORECASE,
)
_RESTART_MARKER = re.compile(
    r"\b(?:scratch\s+that|start\s+over|forget\s+that|on\s+second\s+thought|i\s+take\s+that\s+back)\b"
    r"\s*[,;:.!?-]*\s*(?P<replacement>.+)$",
    re.IGNORECASE,
)
_EXPLICIT_REPLACEMENT_MARKER = re.compile(
    r"\b(?:sorry\s*,?\s*)?"
    r"(?P<command>no\s*,?\s*wait|change\s+(?:that|it)\s+to|"
    r"replace\s+(?:that|it)\s+with|make\s+(?:that|it))\b"
    r"\s*[,;:.!?-]*\s*(?P<replacement>.+?)(?P<ending>[.!?]?)\s*$",
    re.IGNORECASE,
)
_CONTRAST_REPLACEMENT_MARKER = re.compile(
    r"\bnot\s+(?P<old>[^,.;!?]{1,80}),\s*(?:but|rather|instead)\s+(?P<replacement>[^.!?]+?)(?P<ending>[.!?]?)\s*$",
    re.IGNORECASE,
)
_CHAINED_WORD_REPLACEMENT_MARKER = re.compile(
    r"\bno\s*,\s*(?:sorry(?:\s*,?\s*i\s+mean)?|i\s+mean)\s*,\s*"
    r"(?P<replacement>[^\W\d_][\w'\u2019-]{0,40})(?P<ending>[.!?]?)\s*$",
    re.IGNORECASE,
)
_REPEATED_NEGATION_MARKER = re.compile(
    r"^(?P<old>[^,.;!?]{1,80})\s*,\s*"
    r"(?:(?:um+|uh+|er+|ah+)\s*,\s*)?no\s*,\s*not\s+(?P<repeated>[^,.;!?]{1,80})\s*,\s*"
    r"(?P<replacement>[^,.;!?]{1,80})(?P<ending>[.!?]?)\s*$",
    re.IGNORECASE,
)
_CORRECTION_MARKER = re.compile(
    r"\b(?:sorry(?:\s*,?\s*i\s+mean)?|i\s+mean|actually|or\s+rather|no\s*,?\s*wait|"
    r"scratch\s+that|start\s+over|forget\s+that|on\s+second\s+thought|i\s+take\s+that\s+back|"
    r"change\s+(?:that|it)\s+to|replace\s+(?:that|it)\s+with|make\s+(?:that|it))\b|"
    r"\bno\s*,\s*not\b",
    re.IGNORECASE,
)
_LANGUAGE_TAIL_CORRECTION_MARKERS = {
    "fr": ("non",),
    "hi": ("नहीं",),
    "es": ("perdón",),
}
_NONSPACE_TOKEN = re.compile(r"\S+", re.UNICODE)


def resolve_explicit_self_corrections(text: str, language: str = "") -> SelfCorrectionResolution:
    original = text.strip()
    if not original:
        return SelfCorrectionResolution(original)
    language_tail = _resolve_language_tail_correction(original, language)
    if language_tail is not None:
        return language_tail
    cancelled = _resolve_cancelled_clause(original)
    if cancelled is not None:
        return cancelled
    chained_word = _resolve_chained_word_replacement(original)
    if chained_word is not None:
        return chained_word
    repeated_negation = _resolve_repeated_negation(original)
    if repeated_negation is not None:
        return repeated_negation
    explicit = _resolve_explicit_replacement(original)
    if explicit is not None:
        return explicit
    contrast = _resolve_contrast_replacement(original)
    if contrast is not None:
        return contrast
    restarted = _resolve_restart(original)
    if restarted is not None:
        return restarted
    replaced = _resolve_slot_replacement(original)
    if replaced is not None:
        return replaced
    return SelfCorrectionResolution(original)


def _resolve_language_tail_correction(
    text: str,
    language: str,
) -> SelfCorrectionResolution | None:
    """Resolve a short, explicitly marked replacement at the end of an utterance.

    Requiring a configured language, punctuation before the cue, a short final
    replacement, and retained leading context keeps ordinary negation intact.
    """
    code = language.strip().casefold().split("-", 1)[0]
    markers = _LANGUAGE_TAIL_CORRECTION_MARKERS.get(code)
    if not markers:
        return None
    marker_pattern = "|".join(re.escape(marker) for marker in markers)
    match = re.fullmatch(
        rf"(?P<left>.+?)[,;—-]\s*(?P<marker>{marker_pattern})\s*[,;:]?\s*"
        rf"(?P<replacement>[^,;.!?।]+)(?P<ending>[.!?।]?)\s*",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    left = match.group("left").rstrip()
    replacement = _clean_fragment(match.group("replacement"))
    replacement_words = list(_NONSPACE_TOKEN.finditer(replacement))
    left_words = list(_NONSPACE_TOKEN.finditer(left))
    if not replacement_words or len(replacement_words) > 4 or len(left_words) <= len(replacement_words):
        return None
    replace_from = left_words[-len(replacement_words)].start()
    removed = left[replace_from:].strip()
    if not removed or _normalize(removed) == _normalize(replacement):
        return None
    result = left[:replace_from] + replacement + match.group("ending")
    return SelfCorrectionResolution(result, (removed,), (replacement,))


def _resolve_chained_word_replacement(text: str) -> SelfCorrectionResolution | None:
    """Resolve a strong "no, sorry, X" correction of the immediately prior word."""
    match = _CHAINED_WORD_REPLACEMENT_MARKER.search(text)
    if match is None:
        return None
    left = text[: match.start()].rstrip(" ,;:-")
    previous_words = list(re.finditer(r"[^\W\d_][\w'\u2019-]{0,40}", left, flags=re.UNICODE))
    if len(previous_words) < 2:
        return None
    previous = previous_words[-1]
    replacement = match.group("replacement")
    if _normalize(previous.group(0)) == _normalize(replacement):
        return None
    result = left[: previous.start()] + replacement + left[previous.end() :] + match.group("ending")
    return SelfCorrectionResolution(result, (previous.group(0),), (replacement,))


def _resolve_repeated_negation(text: str) -> SelfCorrectionResolution | None:
    """Resolve "X, [filler,] no, not X, Y" only when X repeats exactly."""
    match = _REPEATED_NEGATION_MARKER.fullmatch(text)
    if match is None or _normalize(match.group("old")) != _normalize(match.group("repeated")):
        return None
    old = _clean_fragment(match.group("old"))
    replacement = _clean_fragment(match.group("replacement"))
    if not old or not replacement or _normalize(old) == _normalize(replacement):
        return None
    result = replacement + match.group("ending")
    if text[:1].isupper():
        result = result[:1].upper() + result[1:]
    return SelfCorrectionResolution(result, (old,), (replacement,))


def cancelled_content_leaked(resolution: SelfCorrectionResolution, output: str) -> bool:
    normalized_output = _normalize(output)
    return any(
        len(_normalize(phrase)) >= 3 and _normalize(phrase) in normalized_output
        for phrase in resolution.removed_phrases
    )


def correction_replacement_missing(resolution: SelfCorrectionResolution, output: str) -> bool:
    normalized_output = _normalize(output)
    return any(
        len(_normalize(phrase)) >= 2 and _normalize(phrase) not in normalized_output
        for phrase in resolution.required_phrases
    )


def correction_marker_leaked(
    source: str,
    output: str,
    resolution: SelfCorrectionResolution,
) -> bool:
    if not resolution.changed:
        return False
    output_normalized = _normalize(output)
    markers = {_normalize(match.group(0)) for match in _CORRECTION_MARKER.finditer(source)}
    return any(marker and marker in output_normalized for marker in markers)


def _resolve_cancelled_clause(text: str) -> SelfCorrectionResolution | None:
    match = _CANCEL_MARKER.search(text)
    if match is None:
        return None
    if not any(match.group(name) for name in ("lead_no", "qualifier", "say")):
        return None
    replacement = _clean_fragment(match.group("replacement"))
    if not replacement:
        return None
    left = text[: match.start()].rstrip(" ,;:-")
    prefix, cancelled = _split_last_sentence(left)
    if not cancelled:
        return None
    result = _join_prefix(prefix, replacement)
    return SelfCorrectionResolution(result, (cancelled,), (replacement,))


def _resolve_restart(text: str) -> SelfCorrectionResolution | None:
    match = _RESTART_MARKER.search(text)
    if match is None:
        return None
    replacement = _clean_fragment(match.group("replacement"))
    if not replacement:
        return None
    left = text[: match.start()].rstrip(" ,;:-")
    prefix, cancelled = _split_last_sentence(left)
    if not cancelled:
        return None
    result = _join_prefix(prefix, replacement)
    return SelfCorrectionResolution(result, (cancelled,), (replacement,))


def _resolve_explicit_replacement(text: str) -> SelfCorrectionResolution | None:
    match = _EXPLICIT_REPLACEMENT_MARKER.search(text)
    if match is None:
        return None
    replacement = _clean_fragment(match.group("replacement"))
    ending = match.group("ending")
    if not replacement:
        return None
    left = text[: match.start()].rstrip(" ,;:-")
    replacement_slot = replacement.rstrip(".!?")
    slot = _find_replaced_slot(left, replacement_slot)
    if slot is not None:
        start, end = slot
        removed = left[start:end]
        result = left[:start] + replacement_slot + left[end:]
        return SelfCorrectionResolution(result.rstrip() + ending, (removed,), (replacement_slot,))
    # "It" has no safe deterministic referent here. Leave the untouched
    # sentence for the language model rather than replacing an arbitrary clause.
    if re.search(r"\bit\b", match.group("command"), flags=re.IGNORECASE):
        return None
    prefix, cancelled = _split_last_sentence(left)
    if not cancelled:
        return None
    # A preceding discourse marker can otherwise be mistaken for the content
    # being replaced: "Actually, make that room B" used to become "room B"
    # while leaving the original sentence intact.
    if _normalize(cancelled) in {"actually", "sorry", "wait"}:
        return None
    result = _join_prefix(prefix, replacement.rstrip(".!?")) + ending
    return SelfCorrectionResolution(result, (cancelled,), (replacement.rstrip(".!?"),))


def _resolve_slot_replacement(text: str) -> SelfCorrectionResolution | None:
    match = _SLOT_MARKER.search(text)
    if match is None:
        return None
    left = text[: match.start()].rstrip()
    replacement = _clean_fragment(match.group("replacement"))
    ending = match.group("ending")
    marker = match.group("marker").casefold()
    if not left or not replacement:
        return None

    slot = _find_replaced_slot(left, replacement)
    if slot is None:
        return None
    start, end = slot
    removed = left[start:end]
    if marker == "actually" and not _safe_actual_replacement(removed, replacement):
        return None
    result = left[:start] + replacement + left[end:]
    result = result.rstrip() + ending
    return SelfCorrectionResolution(result, (removed,), (replacement,))


def _resolve_contrast_replacement(text: str) -> SelfCorrectionResolution | None:
    """Resolve only a repeated-clause correction such as "not my cat, but my dog sat ...".

    This intentionally requires the replacement to repeat the tail of the prior
    sentence. That keeps normal contrast prose untouched while making spoken
    corrections deterministic before the language model sees them.
    """
    match = _CONTRAST_REPLACEMENT_MARKER.search(text)
    if match is None:
        return None
    left = text[: match.start()].rstrip()
    if not left or not re.search(r"[.!?]\s*$", left):
        return None
    sentence_start = max((boundary.end() for boundary in re.finditer(r"[.!?]\s+", left)), default=0)
    sentence = left[sentence_start:]
    old = _clean_fragment(match.group("old"))
    replacement = _clean_fragment(match.group("replacement"))
    if not old or not replacement:
        return None
    old_matches = list(re.finditer(rf"(?<!\w){re.escape(old)}(?!\w)", sentence, re.IGNORECASE))
    if not old_matches:
        return None
    old_match = old_matches[-1]
    tail_words = _words(sentence[old_match.end() :])
    replacement_words = _words(replacement)
    if not tail_words or len(replacement_words) <= len(tail_words):
        return None
    if replacement_words[-len(tail_words) :] != tail_words:
        return None
    replacement_subject = " ".join(replacement.split()[: len(replacement_words) - len(tail_words)]).strip()
    if not replacement_subject or _normalize(replacement_subject) == _normalize(old):
        return None
    removed = sentence[old_match.start() : old_match.end()]
    absolute_start = sentence_start + old_match.start()
    absolute_end = sentence_start + old_match.end()
    result = left[:absolute_start] + replacement_subject + left[absolute_end:]
    return SelfCorrectionResolution(result, (removed,), (replacement_subject,))


def _find_replaced_slot(left: str, replacement: str) -> tuple[int, int] | None:
    replacement = replacement.strip()
    if re.fullmatch(_NUMBER_PHRASE, replacement, flags=re.IGNORECASE):
        matches = list(re.finditer(_NUMBER_PHRASE, left, flags=re.IGNORECASE))
        return matches[-1].span() if matches else None
    if re.fullmatch(_WEEKDAY, replacement, flags=re.IGNORECASE):
        matches = list(re.finditer(rf"\b{_WEEKDAY}\b", left, flags=re.IGNORECASE))
        return matches[-1].span() if matches else None
    relative_days = re.findall(rf"\b{_RELATIVE_DAY}\b", replacement, flags=re.IGNORECASE)
    if len(relative_days) == 1:
        matches = list(
            re.finditer(rf"\b{re.escape(relative_days[0])}\b", left, flags=re.IGNORECASE)
        )
        return matches[-1].span() if matches else None
    if re.fullmatch(r"[A-Z][A-Za-z'\u2019-]{1,40}", replacement):
        matches = list(re.finditer(r"\b[A-Z][A-Za-z'\u2019-]{1,40}\b", left))
        matches = [item for item in matches if item.start() > 0]
        return matches[-1].span() if matches else None
    return None


def _safe_actual_replacement(removed: str, replacement: str) -> bool:
    return bool(
        (
            re.fullmatch(_NUMBER_PHRASE, removed, flags=re.IGNORECASE)
            and re.fullmatch(_NUMBER_PHRASE, replacement, flags=re.IGNORECASE)
        )
        or (
            re.fullmatch(_WEEKDAY, removed, flags=re.IGNORECASE)
            and re.fullmatch(_WEEKDAY, replacement, flags=re.IGNORECASE)
        )
    )


def _split_last_sentence(text: str) -> tuple[str, str]:
    boundaries = list(re.finditer(r"[.!?]\s+", text))
    if not boundaries:
        return "", text.strip()
    boundary = boundaries[-1].end()
    return text[:boundary].strip(), text[boundary:].strip()


def _join_prefix(prefix: str, replacement: str) -> str:
    if not prefix:
        return replacement
    return f"{prefix} {replacement}"


def _clean_fragment(value: str) -> str:
    return value.strip(" \t\r\n,;:-")


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split()).strip(" \t\r\n,;:.!?-\u2014")


def _words(value: str) -> list[str]:
    return re.findall(r"[\w'-]+", value.casefold())
