import pytest

from voicepilot.self_corrections import cancelled_content_leaked, resolve_explicit_self_corrections


def test_resolves_high_confidence_slot_corrections():
    assert resolve_explicit_self_corrections(
        "Please ask Ankit to review this, sorry I mean Akshay."
    ).text == "Please ask Akshay to review this."
    assert resolve_explicit_self_corrections(
        "Let's schedule it for Monday, actually Tuesday."
    ).text == "Let's schedule it for Tuesday."
    assert resolve_explicit_self_corrections(
        "The estimate is 15 lakhs, sorry 18 lakhs."
    ).text == "The estimate is 18 lakhs."
    assert resolve_explicit_self_corrections(
        "Let's schedule it for Monday, I mean Tuesday."
    ).text == "Let's schedule it for Tuesday."
    assert resolve_explicit_self_corrections(
        "The estimate is 15 lakhs, or rather 18 lakhs."
    ).text == "The estimate is 18 lakhs."


@pytest.mark.parametrize(
    ("language", "source", "expected"),
    [
        ("hi", "मीटिंग सोमवार को है, नहीं मंगलवार को है।", "मीटिंग मंगलवार को है।"),
        ("es", "Envíalo el lunes, perdón, el martes.", "Envíalo el martes."),
        ("fr", "Envoyez-le lundi, non, mardi.", "Envoyez-le mardi."),
    ],
)
def test_resolves_conservative_language_specific_tail_corrections(language, source, expected):
    resolution = resolve_explicit_self_corrections(source, language)

    assert resolution.text == expected
    assert resolution.has_safe_fallback


def test_language_tail_correction_requires_punctuation_and_configured_language():
    source = "No quiero lunes pero prefiero martes."

    assert resolve_explicit_self_corrections(source, "es").text == source
    assert resolve_explicit_self_corrections("Envoyez-le lundi, non, mardi.").text == (
        "Envoyez-le lundi, non, mardi."
    )


def test_resolves_cancelled_clause_and_restart():
    cancelled = resolve_explicit_self_corrections(
        "Can you tell him I am unhappy, no don't say that, just say we need better quality."
    )
    restarted = resolve_explicit_self_corrections(
        "Keep the customer informed. Use the old deployment plan. Scratch that, use the staged rollout."
    )
    second_thought = resolve_explicit_self_corrections(
        "Send the draft tonight. On second thought, send it tomorrow morning."
    )
    forget = resolve_explicit_self_corrections(
        "Send the draft tonight. Forget that, send it tomorrow morning."
    )
    take_back = resolve_explicit_self_corrections(
        "Send the draft tonight. I take that back, send it tomorrow morning."
    )

    assert cancelled.text == "we need better quality."
    assert cancelled.removed_phrases == ("Can you tell him I am unhappy",)
    assert restarted.text == "Keep the customer informed. use the staged rollout."
    assert restarted.removed_phrases == ("Use the old deployment plan.",)
    assert second_thought.text == "send it tomorrow morning."
    assert forget.text == "send it tomorrow morning."
    assert take_back.text == "send it tomorrow morning."


def test_resolves_explicit_no_wait_and_change_that_to():
    no_wait = resolve_explicit_self_corrections(
        "Send this to Rahul, no wait, send this to Priya."
    )
    changed = resolve_explicit_self_corrections(
        "Schedule it for Monday, change that to Tuesday."
    )
    made = resolve_explicit_self_corrections(
        "Schedule it for Monday, make that Tuesday."
    )

    assert no_wait.text == "send this to Priya."
    assert no_wait.removed_phrases == ("Send this to Rahul",)
    assert changed.text == "Schedule it for Tuesday."
    assert changed.removed_phrases == ("Monday",)
    assert made.text == "Schedule it for Tuesday."


def test_resolves_relative_day_change_it_to_correction():
    correction = resolve_explicit_self_corrections(
        "I am thinking of visiting office tomorrow, sorry change it to day after tomorrow."
    )

    assert correction.text == "I am thinking of visiting office day after tomorrow."
    assert correction.removed_phrases == ("tomorrow",)
    assert correction.required_phrases == ("day after tomorrow",)


def test_ambiguous_change_it_to_is_left_for_the_language_model():
    value = "Rewrite this paragraph, change it to be more formal."

    resolution = resolve_explicit_self_corrections(value)

    assert resolution.text == value
    assert not resolution.changed


def test_resolves_repeated_clause_contrast_correction_without_word_lists():
    correction = resolve_explicit_self_corrections(
        "I think my cat sat on the mat. Not my cat, but my dog sat on the mat."
    )

    assert correction.text == "I think my dog sat on the mat."
    assert correction.removed_phrases == ("my cat",)

    rather = resolve_explicit_self_corrections(
        "I think my cat sat on the mat. Not my cat, rather my dog sat on the mat."
    )
    assert rather.text == "I think my dog sat on the mat."

    instead = resolve_explicit_self_corrections(
        "I think my cat sat on the mat. Not my cat, instead my dog sat on the mat."
    )
    assert instead.text == "I think my dog sat on the mat."


def test_ambiguous_language_remains_unchanged():
    values = [
        "I actually enjoyed the meeting.",
        "What I mean is that we should wait.",
        "She said sorry, I mean it.",
        "Please tell him I don't say that often.",
        "12 users actually need 18 seats.",
        "Let's schedule it for Monday, actually Tuesday works better.",
        "We should rather wait until Tuesday.",
        "I like cats, but dogs are fine.",
    ]

    for value in values:
        resolution = resolve_explicit_self_corrections(value)
        assert resolution.text == value
        assert not resolution.changed


def test_discourse_marker_is_not_destructively_rewritten_as_replaced_content():
    value = "Book room A. Actually, make that room B."

    resolution = resolve_explicit_self_corrections(value)

    assert resolution.text == value
    assert not resolution.changed


def test_cancelled_content_leak_detection_is_case_insensitive():
    resolution = resolve_explicit_self_corrections(
        "Please ask Ankit to review this, sorry I mean Akshay."
    )

    assert cancelled_content_leaked(resolution, "Please ask ANKIT and Akshay.")
    assert not cancelled_content_leaked(resolution, "Please ask Akshay.")


def test_polish_sends_raw_input_and_never_recalls_model_for_semantic_failure():
    from voicepilot.config import RewriteConfig
    from voicepilot.rewrite import TextRewriter

    class LeakingBackend:
        def __init__(self):
            self.prompt = ""
            self.calls = 0

        def complete(self, prompt, *, num_predict):
            self.prompt = prompt
            self.calls += 1
            assert 128 <= num_predict <= 700
            return "Please ask Ankit to review this."

    backend = LeakingBackend()
    rewriter = TextRewriter(RewriteConfig(), [], backend=backend)

    result = rewriter.polish(
        "Please ask Ankit to review this, sorry I mean Akshay.",
    )

    assert "Please ask Ankit to review this, sorry I mean Akshay." in backend.prompt
    assert "Akshay" in backend.prompt
    assert "SPOKEN_REVISION_REFERENCE" in backend.prompt
    assert "<<<APP_REFERENCE>>>" not in backend.prompt
    assert "CORRECTION VALIDATION RETRY" not in backend.prompt
    assert backend.calls == 1
    assert result == "Please ask Ankit to review this."


def test_polish_does_not_preprocess_semantic_correction_before_model():
    from voicepilot.config import RewriteConfig
    from voicepilot.rewrite import TextRewriter

    class Backend:
        prompt = ""

        def complete(self, prompt, *, num_predict):
            self.prompt = prompt
            assert 128 <= num_predict <= 700
            return "Book room B."

    backend = Backend()
    rewriter = TextRewriter(RewriteConfig(), [], backend=backend)

    result = rewriter.polish("Book room A. Actually, make that room B.")

    assert "Book room A. Actually, make that room B." in backend.prompt
    assert result == "Book room B."


@pytest.mark.parametrize(
    ("source", "model_output"),
    [
        ("मीटिंग सोमवार को है। नहीं, मेरा मतलब मंगलवार को है।", "मीटिंग मंगलवार को है।"),
        ("Envoyez-le lundi — non, mardi.", "Envoyez-le mardi."),
        ("Envíalo el lunes; no, quise decir el martes.", "Envíalo el martes."),
        ("Meeting Monday ko hai—nahi, Tuesday ko hai.", "Meeting Tuesday ko hai."),
    ],
)
def test_polish_accepts_model_resolved_multilingual_self_corrections(source, model_output):
    from voicepilot.config import RewriteConfig
    from voicepilot.rewrite import TextRewriter

    class Backend:
        def complete(self, prompt, *, num_predict):
            assert source in prompt
            assert 128 <= num_predict <= 700
            return model_output

    assert TextRewriter(RewriteConfig(), [], backend=Backend()).polish(source) == model_output


def test_polish_prompt_receives_fixed_and_mixed_language_contracts():
    from voicepilot.rewrite import build_polish_prompt

    hindi = build_polish_prompt("नमस्ते", [], language="hi")
    hinglish = build_polish_prompt("Hello नमस्ते", [], language="mix-hi-en")

    assert "Speech language: Hindi." in hindi
    assert "uses 'नहीं' to correct" in hindi
    assert "preserve every already-present segment" in hindi
    assert "Never translate or erase code-switching" in hindi
    assert "Speech language: Mixed Hindi + English (Hinglish)." in hinglish
    assert "Write Hindi in Devanagari and English in Latin script" in hinglish
    assert "Do not translate, monolingualize, or normalize code-switched speech" in hinglish


def test_unknown_correction_pattern_uses_untouched_text_as_unsafe_output_fallback():
    from voicepilot.config import RewriteConfig
    from voicepilot.rewrite import TextRewriter

    source = "The total is five hundred, correction, six hundred."

    class Backend:
        def complete(self, _prompt, *, num_predict):
            assert 128 <= num_predict <= 700
            return "error " * 20

    result = TextRewriter(RewriteConfig(), [], backend=Backend()).polish(source)

    assert result == source


def test_polish_does_not_semantically_reject_a_single_completion():
    from voicepilot.config import RewriteConfig
    from voicepilot.rewrite import TextRewriter

    class MissingReplacementBackend:
        def complete(self, _prompt, *, num_predict):
            assert 128 <= num_predict <= 700
            return "I think something sat on the mat."

    rewriter = TextRewriter(RewriteConfig(), [], backend=MissingReplacementBackend())

    result = rewriter.polish(
        "I think my cat sat on the mat. Not my cat, but my dog sat on the mat."
    )

    assert result == "I think something sat on the mat."


def test_polish_does_not_use_scenario_specific_output_filtering():
    from voicepilot.config import RewriteConfig
    from voicepilot.rewrite import TextRewriter

    class EchoingBackend:
        def complete(self, _prompt, *, num_predict):
            assert 128 <= num_predict <= 700
            return "Cleanup rules: remove filler words and fix punctuation."

    rewriter = TextRewriter(RewriteConfig(), [], backend=EchoingBackend())

    assert rewriter.polish("Um hello there.") == "Cleanup rules: remove filler words and fix punctuation."
