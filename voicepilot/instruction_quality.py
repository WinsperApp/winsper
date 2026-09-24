from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class InstructionAssessment:
    accepted: bool
    code: str = "ok"
    reason: str = ""


_FILLERS = frozenset({"um", "umm", "uh", "er", "ah", "hmm", "hm", "euh", "हम्म", "उम्म", "अं"})
_HALLUCINATIONS = (
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "subtitles by",
)
_NON_ACTION_WORDS = frozenset(
    {
        "a",
        "also",
        "an",
        "and",
        "are",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "here",
        "in",
        "is",
        "it",
        "just",
        "may",
        "might",
        "of",
        "on",
        "only",
        "or",
        "please",
        "should",
        "so",
        "that",
        "the",
        "them",
        "then",
        "there",
        "these",
        "this",
        "those",
        "to",
        "was",
        "well",
        "were",
        "will",
        "with",
        "would",
    }
)
_SCRIPT_RANGES = {
    "devanagari": ((0x0900, 0x097F),),
    "bengali": ((0x0980, 0x09FF),),
    "arabic": ((0x0600, 0x06FF), (0x0750, 0x077F)),
    "tamil": ((0x0B80, 0x0BFF),),
    "telugu": ((0x0C00, 0x0C7F),),
    "cjk": ((0x3040, 0x30FF), (0x3400, 0x9FFF), (0xAC00, 0xD7AF)),
}
_EXPECTED_SCRIPT = {
    "hi": "devanagari",
    "mr": "devanagari",
    "bn": "bengali",
    "ar": "arabic",
    "ur": "arabic",
    "ta": "tamil",
    "te": "telugu",
    "ja": "cjk",
    "zh": "cjk",
    "yue": "cjk",
    "ko": "cjk",
}


def assess_instruction(
    text: str,
    clip: object | None = None,
    language: str = "",
    context_text: str = "",
) -> InstructionAssessment:
    value = " ".join(text.split()).strip()
    if not value:
        return _reject("empty", "No instruction was transcribed.")
    if _very_low_energy(clip):
        return _reject("low_energy", "Recorded audio contained almost no speech energy.")

    words = re.findall(r"[^\W_]+(?:['’-][^\W_]+)?", value.casefold(), flags=re.UNICODE)
    if words and all(word in _FILLERS for word in words):
        return _reject("filler_only", "Only filler speech was detected.")
    if words and all(word in _NON_ACTION_WORDS for word in words):
        return _reject("non_actionable", "The instruction did not contain an actionable request.")
    if _looks_repetitive(words):
        return _reject("repetition", "The instruction transcript repeated the same token.")
    if _looks_like_unclear_short_instruction(words):
        return _reject(
            "unclear_short",
            "The short instruction could not be understood confidently.",
        )
    if _looks_corrupted(value):
        return _reject("corrupted", "The instruction transcript was corrupted.")
    if _is_context_echo(value, context_text):
        return _reject("context_echo", "The selected text was heard instead of an instruction.")
    if any(phrase in value.casefold() for phrase in _HALLUCINATIONS):
        return _reject("hallucination", "The transcript matched a common ASR hallucination.")
    if _has_extreme_script_mismatch(value, language):
        return _reject("language_mismatch", "The transcript script conflicts with the selected language.")
    return InstructionAssessment(True)


def instruction_language_for_selection(configured_language: str, selected_text: str) -> str:
    """Use obvious selection scripts only when user chose Auto/Mixed."""
    configured = configured_language.strip().casefold()
    if configured:
        return configured
    counts = script_counts(selected_text)
    latin = sum(character.isascii() and character.isalpha() for character in selected_text)
    candidates = (
        ("devanagari", "hi", "mix-hi-en"),
        ("bengali", "bn", "mix-bn-en"),
        ("arabic", "ar", "mix-ar-en"),
        ("tamil", "ta", "mix-ta-en"),
        ("telugu", "te", "mix-te-en"),
    )
    for script, fixed, mixed in candidates:
        if counts.get(script, 0) >= 2:
            return mixed if latin >= 2 else fixed
    return configured


def _reject(code: str, reason: str) -> InstructionAssessment:
    return InstructionAssessment(False, code, reason)


def _very_low_energy(clip: object | None) -> bool:
    samples = getattr(clip, "samples", None)
    if samples is None:
        return False
    try:
        import numpy as np

        values = np.asarray(samples, dtype="float32")
    except (TypeError, ValueError):
        return False
    if values.size == 0:
        return True
    peak = float(np.max(np.abs(values)))
    rms = float(np.sqrt(np.mean(np.square(values))))
    return peak < 0.0005 and rms < 0.0001


def _looks_repetitive(words: list[str]) -> bool:
    if len(words) < 4:
        return False
    if len(set(words)) == 1:
        return True
    longest_run = 1
    current_run = 1
    for previous, current in zip(words, words[1:]):
        current_run = current_run + 1 if current == previous else 1
        longest_run = max(longest_run, current_run)
    return longest_run >= 4


def _looks_corrupted(text: str) -> bool:
    if "�" in text or "\x00" in text:
        return True
    compact = "".join(text.split())
    if len(compact) < 6:
        return False
    meaningful = sum(character.isalnum() for character in compact)
    return meaningful / len(compact) < 0.35


def _looks_like_unclear_short_instruction(words: list[str]) -> bool:
    """Reject tiny consonant fragments without restricting valid commands."""
    if len(words) < 2 or len(words) > 3:
        return False
    if any(not word.isascii() or not word.isalpha() or len(word) < 2 for word in words):
        return False
    return all(re.search(r"[aeiouy]", word, flags=re.IGNORECASE) is None for word in words)


def _is_context_echo(instruction: str, context_text: str) -> bool:
    normalized_instruction = " ".join(re.findall(r"[^\W_]+", instruction.casefold(), flags=re.UNICODE))
    normalized_context = " ".join(re.findall(r"[^\W_]+", context_text.casefold(), flags=re.UNICODE))
    return bool(normalized_instruction and normalized_instruction == normalized_context)


def _has_extreme_script_mismatch(text: str, language: str) -> bool:
    code = language.strip().casefold()
    if not code or code.startswith("mix-"):
        return False
    counts = script_counts(text)
    observed = {script for script, count in counts.items() if script != "latin" and count >= 2}
    if not observed:
        return False
    expected = _EXPECTED_SCRIPT.get(code)
    if expected is not None:
        return expected not in observed
    return code == "en" and bool(observed)


def script_counts(text: str) -> dict[str, int]:
    counts = {name: 0 for name in _SCRIPT_RANGES}
    counts["latin"] = 0
    for character in text:
        if character.isascii() and character.isalpha():
            counts["latin"] += 1
            continue
        codepoint = ord(character)
        for name, ranges in _SCRIPT_RANGES.items():
            if any(start <= codepoint <= end for start, end in ranges):
                counts[name] += 1
                break
    return counts
