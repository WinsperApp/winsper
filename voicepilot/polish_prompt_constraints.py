from __future__ import annotations

import re

from .instruction_quality import script_counts


_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_COUNT_VALUE = r"(?:\d+|" + "|".join(_COUNT_WORDS) + r")"
_EXACT_WORD_COUNT = re.compile(rf"\bexactly\s+(?P<count>{_COUNT_VALUE})\s+words?\b", re.IGNORECASE)
_MAX_WORD_COUNT = re.compile(rf"\bno\s+more\s+than\s+(?P<count>{_COUNT_VALUE})\s+words?\b", re.IGNORECASE)
_EXACT_SENTENCE_COUNT = re.compile(
    rf"\bexactly\s+(?P<count>{_COUNT_VALUE})\s+(?:short\s+)?sentences?\b", re.IGNORECASE
)
_IMPLICIT_SHORTENING = re.compile(r"\b(?:concise|shorter|shorten|summari[sz]e|summary)\b", re.IGNORECASE)
_REMOVE_ONLY = re.compile(r"\b(?:remove|delete)\s+only\b", re.IGNORECASE)
_RELATIVE_DATE_WORDS = re.compile(
    r"\b(?:today|tonight|tomorrow|yesterday|this morning|this afternoon|this evening)\b",
    re.IGNORECASE,
)
_EXPLICIT_NUMERIC_PRESERVATION = re.compile(
    r"\b(?:do not|don't|without)\s+(?:change|changing|alter|altering)\s+"
    r"(?:any\s+)?(?:numbers?|amounts?|currenc(?:y|ies))\b",
    re.IGNORECASE,
)
_NUMERIC_VALUE_PHRASE = re.compile(
    r"(?<!\w)(?:(?:[A-Z]{3}|[$£€¥₹])\s*)?[-+]?\d(?:[\d,.]*\d)?"
    r"(?:\s*(?:%|(?!(?:and|or|while|but|in|on|at|to|from|for|with|without)\b)"
    r"[A-Za-zµ°][A-Za-z0-9µ°./-]*))?",
    re.IGNORECASE,
)
_CODE_SELECTION = re.compile(
    r"(?m)^\s*(?:def|class|import|from|function|const|let|var|interface|type|enum|SELECT|WITH)\b",
    re.IGNORECASE,
)
_FRACTIONAL_SHORTENING = re.compile(
    r"\bat\s+least\s+(?P<fraction>half|one\s+half|one\s+third|one\s+quarter)\s+shorter\b",
    re.IGNORECASE,
)
_MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_SPOKEN_DATE_LITERAL = re.compile(
    rf"\b(?:\d{{1,2}}\s+(?:{_MONTH_NAMES})\s+\d{{4}}|"
    rf"(?:{_MONTH_NAMES})\s+\d{{1,2}}(?:,\s*|\s+)\d{{4}})\b",
    re.IGNORECASE,
)
_CURRENCY_LITERAL = re.compile(
    r"(?<!\w)(?:(?:[A-Z]{3})\s+|[$£€¥₹]\s*)[-+]?\d(?:[\d,.]*\d)?",
)
_NUMBER_UNIT_LITERAL = re.compile(
    r"(?<![\w.])[-+]?\d(?:[\d,.]*\d)?\s+"
    r"(?:lakhs?|crores?|hundred|thousand|million|billion|trillion|percent|percentage|%)\b",
    re.IGNORECASE,
)
_TECHNICAL_IDENTIFIER = re.compile(r"\b(?:[A-Z][A-Z0-9]*-\d+|[A-Z]{1,5}\d+)\b")
_REGIONAL_ENGLISH_SPELLINGS = {
    "analyse",
    "analysed",
    "behaviour",
    "centre",
    "colour",
    "defence",
    "favourite",
    "grey",
    "licence",
    "organise",
    "organised",
    "programme",
    "travelling",
}


def _numeric_preservation_guidance(text: str, instruction: str) -> str:
    if not _EXPLICIT_NUMERIC_PRESERVATION.search(instruction):
        return ""
    numeric_phrases = list(
        dict.fromkeys(match.group(0).strip() for match in _NUMERIC_VALUE_PHRASE.finditer(text))
    )
    if not numeric_phrases:
        return ""
    return (
        "Copy these numeric value phrases character-for-character; never recalculate, localize, round, or "
        "substitute a digit: " + "; ".join(numeric_phrases) + "."
    )


def selected_constraint_guidance(text: str, instruction: str) -> str:
    """Restate computable user limits so small models need not perform arithmetic."""
    constraints: list[str] = []
    exact_words = _EXACT_WORD_COUNT.search(instruction)
    if exact_words is not None:
        count = _count_value(exact_words.group("count"))
        constraints.append(
            f"Final output must contain exactly {count} whitespace-separated words. Silently fill word slots "
            f"1 through {count}, fill every slot, omit the slot numbers, and stop after word {count}; there is no "
            f"word {count + 1}. If a draft has {count + 1} words, remove one before output. Prefer a "
            "grammatical plural noun over an article plus noun when one fewer word is required. In an answer, do "
            "not add a modal such as must or should merely because the question says why should; answer its reason "
            "directly. Sentence-ending punctuation does not fill a word slot; attach it to the final word. Never "
            "fuse words or leave a slot empty."
        )
    max_words = _MAX_WORD_COUNT.search(instruction)
    if max_words is not None:
        maximum = _count_value(max_words.group("count"))
        safe_target = maximum - 2 if maximum >= 8 else maximum
        constraints.append(
            f"Final output has a hard ceiling of {maximum} words; aim for {safe_target} words so the limit is safely "
            "met. Prefer natural contractions and remove dispensable articles or framing before exceeding the "
            "ceiling."
        )
    exact_sentences = _EXACT_SENTENCE_COUNT.search(instruction)
    if exact_sentences is not None:
        constraints.append(
            f"Final output must contain exactly {_count_value(exact_sentences.group('count'))} sentences."
        )
    fractional = _FRACTIONAL_SHORTENING.search(instruction)
    if fractional is not None:
        retained_ratio = {
            "half": 0.5,
            "one half": 0.5,
            "one third": 2 / 3,
            "one quarter": 0.75,
        }[" ".join(fractional.group("fraction").casefold().split())]
        maximum = max(1, int(len(text.split()) * retained_ratio))
        safe_target = maximum - 2 if maximum >= 8 else maximum
        constraints.append(
            f"Final output has a hard ceiling of {maximum} whitespace-separated words; aim for {safe_target} words "
            "so the requested fractional shortening is safely met."
        )
    if exact_words is None and max_words is None and fractional is None and _IMPLICIT_SHORTENING.search(instruction):
        constraints.append(
            "Final output must contain fewer words than the selection and be visibly shorter. Remove nonessential "
            "framing before dropping any protected fact."
        )
    relative_dates = list(dict.fromkeys(match.group(0) for match in _RELATIVE_DATE_WORDS.finditer(text)))
    if relative_dates:
        constraints.append("Copy these relative date or deadline words exactly: " + ", ".join(relative_dates) + ".")
    numeric_guidance = _numeric_preservation_guidance(text, instruction)
    if numeric_guidance:
        constraints.append(numeric_guidance)
    if _REMOVE_ONLY.search(instruction):
        constraints.append(
            "Remove only the named target. Copy every word outside that target unchanged and in the original order; "
            "do not paraphrase, shorten, or omit anything else."
        )
    if constraints:
        subject_guidance = (
            "Copy the selected text's first grammatical subject noun verbatim and keep that subject explicit; never "
            "replace it with a related abstraction or return a subjectless fragment. Preserve the central action."
        )
        if exact_words is not None:
            subject_guidance += (
                " Preserve its direct-object noun phrase when it fits the requested limit; do not drop an object word "
                "merely to finish one slot early."
            )
        constraints.append(subject_guidance)
    return "\n".join(f"- {constraint}" for constraint in constraints)


def _count_value(value: str) -> int:
    folded = value.casefold()
    return int(folded) if folded.isdigit() else _COUNT_WORDS[folded]


def selected_literal_tail_guidance(text: str, instruction: str) -> str:
    """Repeat only explicit literal-preservation data at the small-model output edge."""
    guidance: list[str] = []
    numeric = _numeric_preservation_guidance(text, instruction)
    if numeric:
        guidance.append(numeric)
    if _REMOVE_ONLY.search(instruction):
        guidance.append(
            "Remove only the named target; copy every word outside it unchanged and in the original order."
        )
    return "\n".join(f"- {value}" for value in guidance)


def best_selected_tail_guidance(text: str, instruction: str) -> str:
    """Put one compact, computed length constraint beside the Best output edge."""
    exact_words = _EXACT_WORD_COUNT.search(instruction)
    if exact_words is not None:
        count = _count_value(exact_words.group("count"))
        return (
            f"- FINAL LIMIT: fill exactly {count} whitespace-separated word slots; "
            f"do not stop after only {count - 1}."
        )
    max_words = _MAX_WORD_COUNT.search(instruction)
    if max_words is not None:
        maximum = _count_value(max_words.group("count"))
        target = maximum - 1 if maximum > 1 else maximum
        return f"- FINAL LIMIT: at most {maximum} whitespace-separated words; target {target}."
    exact_sentences = _EXACT_SENTENCE_COUNT.search(instruction)
    if exact_sentences is not None:
        count = _count_value(exact_sentences.group("count"))
        return f"- FINAL LIMIT: exactly {count} sentences."
    fractional = _FRACTIONAL_SHORTENING.search(instruction)
    if fractional is not None:
        retained_ratio = {
            "half": 0.5,
            "one half": 0.5,
            "one third": 2 / 3,
            "one quarter": 0.75,
        }[" ".join(fractional.group("fraction").casefold().split())]
        maximum = max(1, int(len(text.split()) * retained_ratio))
        return f"- FINAL LIMIT: at most {maximum} whitespace-separated words."
    if _IMPLICIT_SHORTENING.search(instruction):
        return f"- FINAL LIMIT: fewer than {len(text.split())} whitespace-separated words."
    return ""


def source_script_guidance(text: str, instruction: str = "") -> str:
    """Keep non-Latin source scripts explicit unless translation is requested."""
    if re.search(r"\btranslat(?:e|ed|ion)\b", instruction, re.IGNORECASE):
        return ""
    scripts = [name for name, count in script_counts(text).items() if name != "latin" and count >= 2]
    if not scripts:
        return ""
    labels = ", ".join(name.replace("_", " ").title() for name in scripts)
    anchor = next(
        (
            token.strip(".,!?;:()[]{}\"'")
            for token in text.split()
            if any(character.isalpha() and not character.isascii() for character in token)
        ),
        "",
    )
    anchor_guidance = (
        f" Final result MUST contain this exact unchanged source-script anchor: {anchor}."
        if anchor
        else ""
    )
    return (
        f"- Source contains {labels} writing. Final output must contain text in that writing system; copy those "
        f"source spans instead of translating or replacing them.{anchor_guidance}"
    )


def source_code_guidance(text: str) -> str:
    if not _CODE_SELECTION.search(text):
        return ""
    return (
        "- Source is code. Return the complete updated code artifact with the requested edit and all untargeted code "
        "preserved. Never return prose or an explanation instead of the code."
    )


def polish_literal_guidance(text: str) -> str:
    """Expose exact source forms that small cleanup models often localize."""
    literals: list[tuple[int, str]] = []
    for pattern in (
        _SPOKEN_DATE_LITERAL,
        _CURRENCY_LITERAL,
        _NUMBER_UNIT_LITERAL,
        _TECHNICAL_IDENTIFIER,
    ):
        literals.extend((match.start(), match.group(0)) for match in pattern.finditer(text))
    exact = list(
        dict.fromkeys(value.strip() for _, value in sorted(literals) if value.strip())
    )
    return (
        "Copy these source literals character-for-character; never reorder date fields, replace currency codes with "
        "symbols, localize separators, or change attached units: " + "; ".join(exact) + "."
        if exact
        else ""
    )


def regional_english_spelling_guidance(text: str) -> str:
    spellings = regional_english_spellings(text)
    return (
        "Final output must contain every one of these exact regional English spellings unchanged; never convert "
        "them to another regional variant: "
        + ", ".join(spellings)
        + "."
        if spellings
        else ""
    )


def regional_english_spellings(text: str) -> list[str]:
    return list(
        dict.fromkeys(
            match.group(0)
            for match in re.finditer(r"\b[A-Za-z]+\b", text)
            if match.group(0).casefold() in _REGIONAL_ENGLISH_SPELLINGS
        )
    )


def fast_polish_source_tail_guidance(text: str) -> str:
    """Repeat source-form constraints beside the Fast output edge."""
    checks: list[str] = []
    spellings = regional_english_spellings(text)
    if spellings:
        checks.append(
            "Final result MUST contain every exact source spelling: " + " | ".join(spellings) + "."
        )
    script = source_script_guidance(text)
    if script:
        checks.append(script)
    return "\nFINAL SOURCE CHECK:\n" + "\n".join(checks) if checks else ""
