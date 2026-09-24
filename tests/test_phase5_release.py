from __future__ import annotations

from pathlib import Path

from devtools.e2e_lab import LabResult, constraint_outcome, load_cases
from devtools.phase5_release import evaluate_phase5_release, expand_phase5_cases
from voicepilot.rewrite import missing_protected_identifiers


def _result(index: int, status: str = "pass", *, kind: str | None = None, model: str = "Llama 3.2 3B") -> LabResult:
    return LabResult(
        run_id="run",
        case_id=f"phase5-{index}",
        suite="phase5",
        category="certification",
        kind=kind or ("polish" if index % 2 == 0 else "rewrite"),
        status=status,
        score=3 if status == "pass" else 0,
        latency_ms=800,
        expected="safe output",
        actual="safe output",
        gate="protected-facts",
        metrics={
            "rewrite_model": f"Embedded llama.cpp · {model}",
            "llama_prompt_ms": 300,
            "llama_predicted_ms": 400,
        },
    )


def test_phase5_matrix_has_at_least_500_unique_cross_destination_cases():
    cases = expand_phase5_cases(load_cases(Path("e2e/cases.yaml")))

    assert len(cases) >= 500
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["phase5_branch"] for case in cases} == {"dictated", "selected"}
    assert {case["destination"]["kind"] for case in cases} >= {
        "general",
        "email",
        "chat",
        "docs",
        "prompt",
        "code",
        "terminal",
        "spreadsheet",
        "presentation",
    }
    terminal_cases = [case for case in cases if case["id"].startswith("polish-powershell-command--")]
    assert len(terminal_cases) == 1
    assert terminal_cases[0]["destination"]["kind"] == "terminal"
    assert terminal_cases[0]["app_label"] == "PowerShell"
    git_command_cases = [case for case in cases if case["id"].startswith("polish-git-command--")]
    assert len(git_command_cases) == 1
    assert git_command_cases[0]["destination"]["kind"] == "terminal"
    chatgpt_cases = [case for case in cases if case["id"].startswith("prompt-ai-chatgpt--")]
    assert len(chatgpt_cases) == 1
    assert chatgpt_cases[0]["destination"]["kind"] == "prompt"


def test_phase5_objective_constraints_reject_verifiable_failures():
    unchanged = constraint_outcome(
        {"input": "stupid", "requires_change": True},
        "stupid",
    )
    too_long = constraint_outcome(
        {"input": "one two three four", "max_length_ratio": 0.5},
        "one two three four",
    )
    missing_list = constraint_outcome(
        {"input": "one two three", "required_structure": "bullets"},
        "One, two, and three.",
    )
    wrong_script = constraint_outcome(
        {"input": "नमस्ते", "required_scripts": ["devanagari"]},
        "Hello",
    )

    assert unchanged["status"] == "fail"
    assert too_long["status"] == "fail"
    assert missing_list["status"] == "fail"
    assert wrong_script["status"] == "fail"
    formatted_list = constraint_outcome(
        {
            "input": "first review API second update Priya third deploy Tuesday",
            "required_structure": "bullets",
            "requires_change": True,
        },
        "- Review API\n- Update Priya\n- Deploy Tuesday",
    )
    assert formatted_list["status"] == "pass"


def test_code_editor_protects_real_identifiers_without_freezing_prose():
    assert missing_protected_identifiers(
        "stupid",
        "Replace this with a professional synonym.",
        "unwise",
        "VS Code",
    ) == []
    assert missing_protected_identifiers(
        "def get_user(user_id): return db.find(user_id)",
        "Make this clearer without changing behavior.",
        "def get_user(): return db.find()",
        "VS Code",
    ) == ["user_id"]
    assert missing_protected_identifiers(
        "Priya found an OAuth callback error in the FastAPI logs.",
        "Summarize this.",
        "Priya identified a FastAPI OAuth callback error.",
        "VS Code",
    ) == []
    assert missing_protected_identifiers(
        "This discerning Monitor; Professional work looks stunning.",
        "Make this more concise.",
        "This professional work looks excellent.",
        "Outlook",
    ) == []


def test_phase5_release_requires_500_clean_executions():
    insufficient = evaluate_phase5_release([_result(index) for index in range(499)])
    ready = evaluate_phase5_release([_result(index) for index in range(500)])
    failed = evaluate_phase5_release([*[_result(index) for index in range(500)], _result(501, "fail")])

    assert not insufficient["ready"]
    assert ready["ready"]
    assert ready["branches"]["dictated"]["failed"] == 0
    assert ready["branches"]["selected"]["failed"] == 0
    assert not failed["ready"]
    assert failed["failed_gates"] == ["protected-facts"]


def test_phase5_release_rejects_missing_branch_or_mixed_models():
    dictated_only = evaluate_phase5_release([_result(index, kind="polish") for index in range(500)])
    mixed_models = evaluate_phase5_release(
        [
            *[_result(index) for index in range(499)],
            _result(500, model="Qwen 3 8B"),
        ]
    )

    assert not dictated_only["ready"]
    assert dictated_only["branches"]["selected"]["executed"] == 0
    assert not mixed_models["ready"]
    assert not mixed_models["single_model_ready"]
