from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LanguageAwareModel(Protocol):
    languages: tuple[str, ...]


PARAKEET_V3_LANGUAGES = (
    "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu", "it",
    "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru", "uk",
)


@dataclass(frozen=True)
class MixedLanguageMode:
    code: str
    label: str
    primary_language: str
    script_instruction: str
    prompt: str = ""


MIXED_LANGUAGE_MODES: tuple[MixedLanguageMode, ...] = (
    MixedLanguageMode(
        "mix-hi-en",
        "Mixed Hindi + English (Hinglish)",
        "hi",
        "Write Hindi in Devanagari and English in Latin script.",
        "यह हिंदी और अंग्रेज़ी मिला-जुला भाषण है। जैसा बोला गया है वैसा ही लिखें। अनुवाद बिल्कुल न करें। हिंदी शब्द देवनागरी में लिखें और English words Latin script में रखें। भाषा बदलने को बनाए रखें।",
    ),
    MixedLanguageMode("mix-es-en", "Mixed Spanish + English (Spanglish)", "es", "Write Spanish and English in their normal Latin spelling."),
    MixedLanguageMode("mix-fr-en", "Mixed French + English (Franglais)", "fr", "Write French and English in their normal Latin spelling."),
    MixedLanguageMode("mix-de-en", "Mixed German + English (Denglish)", "de", "Write German and English in their normal Latin spelling."),
    MixedLanguageMode("mix-pt-en", "Mixed Portuguese + English", "pt", "Write Portuguese and English in their normal Latin spelling."),
    MixedLanguageMode("mix-ar-en", "Mixed Arabic + English", "ar", "Write Arabic in Arabic script and English in Latin script."),
    MixedLanguageMode("mix-bn-en", "Mixed Bengali + English", "bn", "Write Bengali in Bengali script and English in Latin script."),
    MixedLanguageMode("mix-mr-en", "Mixed Marathi + English", "mr", "Write Marathi in Devanagari and English in Latin script."),
    MixedLanguageMode("mix-ta-en", "Mixed Tamil + English", "ta", "Write Tamil in Tamil script and English in Latin script."),
    MixedLanguageMode("mix-te-en", "Mixed Telugu + English", "te", "Write Telugu in Telugu script and English in Latin script."),
)

SPEECH_LANGUAGE_NAMES: dict[str, str] = {
    "": "Auto / Mixed languages",
    "af": "Afrikaans",
    "am": "Amharic",
    "ar": "Arabic",
    "as": "Assamese",
    "az": "Azerbaijani",
    "ba": "Bashkir",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "bo": "Tibetan",
    "br": "Breton",
    "bs": "Bosnian",
    "ca": "Catalan",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "eu": "Basque",
    "fa": "Persian",
    "fi": "Finnish",
    "fo": "Faroese",
    "fr": "French",
    "gl": "Galician",
    "gu": "Gujarati",
    "ha": "Hausa",
    "haw": "Hawaiian",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "ht": "Haitian Creole",
    "hu": "Hungarian",
    "hy": "Armenian",
    "id": "Indonesian",
    "is": "Icelandic",
    "it": "Italian",
    "ja": "Japanese",
    "jw": "Javanese",
    "ka": "Georgian",
    "kk": "Kazakh",
    "km": "Khmer",
    "kn": "Kannada",
    "ko": "Korean",
    "la": "Latin",
    "lb": "Luxembourgish",
    "ln": "Lingala",
    "lo": "Lao",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mg": "Malagasy",
    "mi": "Maori",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mn": "Mongolian",
    "mr": "Marathi",
    "ms": "Malay",
    "mt": "Maltese",
    "my": "Myanmar",
    "ne": "Nepali",
    "nl": "Dutch",
    "nn": "Nynorsk",
    "no": "Norwegian",
    "oc": "Occitan",
    "pa": "Punjabi",
    "pl": "Polish",
    "ps": "Pashto",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sa": "Sanskrit",
    "sd": "Sindhi",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sn": "Shona",
    "so": "Somali",
    "sq": "Albanian",
    "sr": "Serbian",
    "su": "Sundanese",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "tg": "Tajik",
    "th": "Thai",
    "tk": "Turkmen",
    "tl": "Tagalog",
    "tr": "Turkish",
    "tt": "Tatar",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "yi": "Yiddish",
    "yo": "Yoruba",
    "zh": "Chinese",
    "yue": "Cantonese",
}

SPEECH_LANGUAGE_NAMES.update({mode.code: mode.label for mode in MIXED_LANGUAGE_MODES})


def speech_language_options() -> list[tuple[str, str]]:
    return [
        (code, name if not code else f"{name} ({code})")
        for code, name in SPEECH_LANGUAGE_NAMES.items()
    ]


def model_supports_language(preset: LanguageAwareModel, language: str) -> bool:
    code = language.strip().casefold()
    if mixed_language_mode(code) is not None:
        return "multilingual" in preset.languages
    if "multilingual" in preset.languages:
        return True
    if not code:
        return len(preset.languages) > 1
    return code in preset.languages


def fast_dictation_supported(language: str) -> bool:
    """Return whether the dedicated low-latency model supports *language*."""
    code = language.strip().casefold()
    return code == "en" or code in PARAKEET_V3_LANGUAGES


def mixed_language_mode(code: str) -> MixedLanguageMode | None:
    normalized = code.strip().casefold()
    return next((mode for mode in MIXED_LANGUAGE_MODES if mode.code == normalized), None)


def model_language_code(code: str) -> str | None:
    mode = mixed_language_mode(code)
    if mode is not None:
        return mode.primary_language
    normalized = code.strip().casefold()
    return normalized or None


def mixed_transcribe_prompt(code: str) -> str | None:
    mode = mixed_language_mode(code)
    if mode is None:
        return None
    return mode.prompt or (
        f"Transcribe {mode.label.removeprefix('Mixed ')} exactly as spoken. "
        "Do not translate, paraphrase, or normalize one language into the other. "
        f"{mode.script_instruction} Preserve code switching."
    )
