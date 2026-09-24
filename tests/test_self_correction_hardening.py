from voicepilot.config import RewriteConfig
from voicepilot.polish_service import TextRewriter
from voicepilot.self_corrections import resolve_explicit_self_corrections


class SequenceBackend:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, _prompt, *, num_predict):
        self.calls += 1
        return self.outputs.pop(0)


def test_explicit_no_sorry_replaces_only_immediately_prior_word():
    resolution = resolve_explicit_self_corrections("I want to become a better person no, sorry, human.")

    assert resolution.text == "I want to become a better human."
    assert resolution.removed_phrases == ("person",)
    assert resolution.required_phrases == ("human",)


def test_repeated_negation_keeps_only_final_phrase():
    resolution = resolve_explicit_self_corrections("As always, um, no, not as always, as sometimes.")

    assert resolution.text == "As sometimes."
    assert resolution.removed_phrases == ("As always",)
    assert resolution.required_phrases == ("as sometimes",)


def test_ambiguous_apology_and_ordinary_contrast_remain_untouched():
    cases = (
        "No, sorry humans need rest.",
        "I said no, but the human disagreed.",
        "Not as always, but as sometimes happens.",
        "Always, no, not usually, sometimes.",
    )

    for source in cases:
        assert resolve_explicit_self_corrections(source).text == source


def test_failed_model_correction_never_triggers_a_second_completion():
    source = "I want to become a better person no, sorry, human."
    backend = SequenceBackend(
        "I want to become a better person, human.",
        "I want to become a better person and human.",
    )

    result = TextRewriter(RewriteConfig(), [], backend=backend).polish(source)

    assert result == "I want to become a better person, human."
    assert backend.calls == 1
