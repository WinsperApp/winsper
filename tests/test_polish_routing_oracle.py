from __future__ import annotations

import pytest

from devtools.polish_routing_benchmark import CASES, Case, conservative_route, summarize, validate


def _case(case_id: str):
    return next(case for case in CASES if case.id == case_id)


@pytest.mark.parametrize(
    "case_id",
    (
        "mail_request_preserved",
        "mail_deictic_request_preserved",
        "vscode_json",
        "vscode_python",
        "vscode_javascript",
        "vscode_sql",
        "vscode_yaml",
        "vscode_comment_cleanup",
        "vscode_deictic_request_preserved",
        "terminal_powershell",
        "terminal_git_branch",
        "terminal_unsafe_request_preserved",
        "browser_search",
        "browser_support_form",
        "browser_translation_request_preserved",
        "docs_bullets",
        "excel_formula",
    ),
)
def test_no_selection_requests_are_content_not_generation_tasks(case_id: str) -> None:
    case = _case(case_id)

    assert case.branch == "no_selection"
    assert case.selected == ""
    assert case.expected_route == "ai"
    assert case.validator == "preserved_request"


@pytest.mark.parametrize(
    ("case_id", "preserved", "executed"),
    (
        (
            "mail_request_preserved",
            "Write a short email to the design team saying the review is at 3 pm and ask them to bring the final mockups.",
            "Hi design team, the review is at 3 pm. Please bring the final mockups.",
        ),
        (
            "vscode_json",
            "Create a JSON object with a key named x and the numeric value 12.",
            '{"x": 12}',
        ),
        (
            "terminal_powershell",
            "Write a PowerShell command that lists Python files in the current folder.",
            "Get-ChildItem -Filter *.py",
        ),
        (
            "browser_translation_request_preserved",
            "Translate this to French.",
            "Bonjour.",
        ),
        (
            "excel_formula",
            "Create an Excel formula that sums cells B2 through B10.",
            "=SUM(B2:B10)",
        ),
    ),
)
def test_request_validator_accepts_cleanup_and_rejects_execution(
    case_id: str,
    preserved: str,
    executed: str,
) -> None:
    case = _case(case_id)

    passed, issues = validate(case, "ai", preserved, "")
    assert passed, issues

    passed, issues = validate(case, "ai", executed, "")
    assert not passed
    assert any("request" in issue or "missing" in issue for issue in issues)


def test_no_selection_question_must_remain_a_question() -> None:
    case = _case("chat_casual")

    passed, issues = validate(
        case,
        "ai",
        "Hey, can we move the design review to 4:30? I have a customer call.",
        "",
    )
    assert passed, issues

    passed, issues = validate(
        case,
        "ai",
        "Yes, move the design review to 4:30 because of the customer call.",
        "",
    )
    assert not passed
    assert "question was answered or changed into a statement" in issues


def test_conservative_route_blocks_only_bad_no_selection_input() -> None:
    assert conservative_route(_case("mail_deictic_request_preserved"))[0] == "ai"
    assert conservative_route(_case("browser_translation_request_preserved"))[0] == "ai"
    assert conservative_route(_case("garbage_short"))[0] == "block"
    assert conservative_route(_case("garbage_repetition"))[0] == "block"

    ordinary_content = Case("ordinary", "daily", "Notepad", "document", "no_selection", "this is it")
    assert conservative_route(ordinary_content) == ("ai", "spoken_content")


def test_selected_text_cases_remain_explicit_arbitrary_tasks() -> None:
    selected = [case for case in CASES if case.branch == "selected"]

    assert selected
    assert all(case.selected for case in selected)
    assert all(case.expected_route == "ai" for case in selected)
    assert all(case.validator not in {"preserved_request", "preserved_question"} for case in selected)


def test_summary_names_valid_inputs_without_implying_generation_tasks() -> None:
    row = {
        "approach": "current",
        "elapsed_ms": 1.0,
        "expected_route": "ai",
        "passed": True,
        "decision": "ai",
    }

    result = summarize([row], "current")

    assert result["valid_input_accuracy_pct"] == 100.0
    assert "valid_task_accuracy_pct" not in result
