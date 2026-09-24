from __future__ import annotations

from dataclasses import dataclass

import pytest

from voicepilot.config import AppConfig, ProfileStyle
from voicepilot.destination import DestinationContext
from voicepilot.rewrite import TextRewriter, build_polish_prompt


@dataclass
class StaticBackend:
    output: str

    def complete(self, _prompt: str, *, num_predict: int) -> str:
        assert 128 <= num_predict <= 900
        return self.output


@pytest.mark.parametrize(
    ("name", "destination", "profile", "spoken", "model_output", "expected_fragment"),
    [
        (
            "email",
            DestinationContext("email", "Gmail"),
            ProfileStyle(label="Polished email"),
            "Hi Avery what is the status on deliverables? Regards Rahul",
            "Hi Avery what is the status on deliverables? Regards Rahul",
            "Hi Avery,\n\nwhat is the status on deliverables?\n\nRegards,\nRahul",
        ),
        (
            "chat",
            DestinationContext("chat", "Slack"),
            ProfileStyle(label="Chat concise"),
            "can you share the update by three",
            "Can you share the update by three?",
            "Can you share the update by three?",
        ),
        (
            "document",
            DestinationContext("docs", "Word"),
            ProfileStyle(label="Docs polished"),
            "first paragraph\n\nsecond paragraph",
            "First paragraph\n\nSecond paragraph.",
            "First paragraph\n\nSecond paragraph.",
        ),
        (
            "prompt",
            DestinationContext("prompt", "ChatGPT"),
            ProfileStyle(label="Prompt-aware"),
            "create a release plan with risks and owners",
            "Create a release plan with risks and owners.",
            "Create a release plan with risks and owners.",
        ),
        (
            "python",
            DestinationContext("code", "VS Code", "python", "title"),
            ProfileStyle(label="Code-aware"),
            "def add",
            "def add",
            "def add():",
        ),
        (
            "terminal",
            DestinationContext("terminal", "Windows Terminal"),
            ProfileStyle(label="Code-aware"),
            "get child item recurse",
            "Command: Get-ChildItem -Recurse",
            "Get-ChildItem -Recurse",
        ),
        (
            "spreadsheet",
            DestinationContext("spreadsheet", "Excel"),
            ProfileStyle(label="General"),
            "quarterly revenue",
            "Quarterly revenue",
            "Quarterly revenue",
        ),
        (
            "presentation",
            DestinationContext("presentation", "PowerPoint"),
            ProfileStyle(label="General"),
            "reduce onboarding time by forty percent",
            "Reduce onboarding time by 40%.",
            "Reduce onboarding time by 40%.",
        ),
        (
            "generic",
            DestinationContext("general", "Notepad"),
            ProfileStyle(label="General"),
            "this is a note",
            "This is a note.",
            "This is a note.",
        ),
    ],
)
def test_auto_polish_destination_matrix(name, destination, profile, spoken, model_output, expected_fragment):
    rewriter = TextRewriter(AppConfig().rewrite, [], backend=StaticBackend(model_output))
    output = rewriter.polish(spoken, profile, destination.app_label, destination)
    assert output == expected_fragment, name


def test_selected_rewrite_preserves_layout_unless_instruction_changes_it():
    original = "Hi Avery,\n\nStatus update.\n\nRegards,\nRahul"
    rewriter = TextRewriter(AppConfig().rewrite, [], backend=StaticBackend(original))
    output = rewriter.rewrite(
        original,
        "keep the wording unchanged",
        ProfileStyle(label="Polished email"),
        "Gmail",
        DestinationContext("email", "Gmail"),
    )
    assert output == original


def test_selected_email_rewrite_removes_model_markdown_artifacts_without_reformatting():
    original = "Hi Avery,\n\nStatus update.\n\nRegards,\nRahul"
    modeled = "Hi Avery,\n\nChecking status.\n\nRegards,  \nRahul"
    rewriter = TextRewriter(AppConfig().rewrite, [], backend=StaticBackend(modeled))
    output = rewriter.rewrite(
        original,
        "make it concise",
        ProfileStyle(label="Polished email"),
        "Gmail",
        DestinationContext("email", "Gmail"),
    )
    assert output == "Hi Avery,\n\nChecking status.\n\nRegards,\nRahul"


def test_every_destination_prompt_has_a_specific_output_contract():
    destinations = [
        DestinationContext("email", "Gmail"),
        DestinationContext("chat", "Slack"),
        DestinationContext("docs", "Word"),
        DestinationContext("prompt", "ChatGPT"),
        DestinationContext("code", "VS Code", "python", "title"),
        DestinationContext("terminal", "Windows Terminal"),
        DestinationContext("spreadsheet", "Excel"),
        DestinationContext("presentation", "PowerPoint"),
        DestinationContext("general", "Notepad"),
    ]
    for destination in destinations:
        prompt = build_polish_prompt("sample input", [], ProfileStyle(label="General"), destination.app_label, destination)
        assert "Formatting:" in prompt
        assert "Return only insertion-ready final text" in prompt
