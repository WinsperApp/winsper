from __future__ import annotations

import pytest

from voicepilot.instruction_quality import assess_instruction
from voicepilot.voice_commands import parse_voice_command


@pytest.mark.parametrize(
    ("spoken", "label"),
    [
        ("please make this more concise for me", "Shorter"),
        ("turn this into bullet points", "Bullets"),
        ("translate this to Brazilian Portuguese", "Translate to Brazilian Portuguese"),
    ],
)
def test_standalone_positive_presets_still_canonicalize(spoken: str, label: str):
    command = parse_voice_command(spoken, local_actions_enabled=False)

    assert command.kind == "edit"
    assert command.label == label


@pytest.mark.parametrize(
    "spoken",
    [
        "Do not make it shorter.",
        "Make it shorter, but preserve every heading.",
        "Make it professional and translate it to French.",
        "Keep the word professional but simplify the rest.",
        "Translate this to French and summarize it.",
        "Translate to Spanish, preserving all identifiers.",
        "Do not replace the last sentence with hello.",
    ],
)
def test_negated_or_compound_custom_instructions_preserve_exact_spoken_text(spoken: str):
    command = parse_voice_command(spoken, local_actions_enabled=False)

    assert command.kind == "raw"
    assert command.label == "Custom"
    assert command.instruction == spoken


@pytest.mark.parametrize("instruction", ["And so this", "this and that", "well then this"])
def test_deictic_or_function_word_only_instructions_are_rejected(instruction: str):
    assessment = assess_instruction(instruction)

    assert not assessment.accepted
    assert assessment.code == "non_actionable"


@pytest.mark.parametrize(
    "instruction",
    ["delete", "summarize", "SQL", "make bold", "answer it", "use plain language"],
)
def test_terse_actionable_instructions_remain_accepted(instruction: str):
    assert assess_instruction(instruction).accepted
