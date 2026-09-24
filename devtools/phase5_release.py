"""Polish certification matrix used by the repository E2E lab."""

from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class PolishDestination:
    id: str
    kind: str
    app_label: str
    language: str = ""


DESTINATIONS: tuple[PolishDestination, ...] = (
    PolishDestination("notepad", "general", "Notepad"),
    PolishDestination("gmail", "email", "Gmail"),
    PolishDestination("slack", "chat", "Slack"),
    PolishDestination("word", "docs", "Microsoft Word"),
    PolishDestination("obsidian", "docs", "Obsidian"),
    PolishDestination("chatgpt", "prompt", "ChatGPT"),
    PolishDestination("vscode-python", "code", "VS Code", "python"),
    PolishDestination("vscode-typescript", "code", "VS Code", "typescript"),
    PolishDestination("powershell", "terminal", "Windows Terminal", "powershell"),
    PolishDestination("excel", "spreadsheet", "Microsoft Excel"),
    PolishDestination("powerpoint", "presentation", "Microsoft PowerPoint"),
    PolishDestination("browser-form", "general", "Browser form"),
)


EXTRA_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "phase5-rewrite-synonym",
        "kind": "rewrite",
        "category": "selected-arbitrary",
        "gate": "selected-query",
        "input": "stupid",
        "instruction": "Replace this with a professional synonym.",
        "must_exclude": ["stupid"],
        "requires_change": True,
    },
    {
        "id": "phase5-rewrite-answer",
        "kind": "rewrite",
        "category": "selected-arbitrary",
        "gate": "selected-query",
        "input": "What is product management?",
        "instruction": "Answer this in one concise sentence.",
        "must_include": ["product", "management"],
        "must_exclude": ["What is product management?"],
        "requires_change": True,
    },
    {
        "id": "phase5-rewrite-translate",
        "kind": "rewrite",
        "category": "selected-arbitrary",
        "gate": "selected-query",
        "input": "The meeting is on Tuesday.",
        "instruction": "Translate this to French.",
        "must_include": ["mardi"],
        "must_exclude": ["Tuesday"],
        "requires_change": True,
    },
    {
        "id": "phase5-rewrite-shorten",
        "kind": "rewrite",
        "category": "selected-arbitrary",
        "gate": "selected-query",
        "input": "The team met on Tuesday in Bengaluru to discuss the delayed Q2 release plan.",
        "instruction": "Make this substantially shorter without losing Tuesday, Bengaluru, Q2, or the delay.",
        "protected": ["Tuesday", "Bengaluru", "Q2"],
        "must_include_any": [["delay", "delayed"]],
        "max_length_ratio": 0.99,
        "requires_change": True,
    },
    {
        "id": "phase5-rewrite-bullets",
        "kind": "rewrite",
        "category": "selected-arbitrary",
        "gate": "selected-query",
        "input": "Review the API, confirm the migration, and update Priya.",
        "instruction": "Turn this into three bullet points.",
        "protected": ["API", "Priya"],
        "required_structure": "bullets",
        "requires_change": True,
    },
    {
        "id": "phase5-rewrite-professional",
        "kind": "rewrite",
        "category": "selected-arbitrary",
        "input": "hey the Q2 report is late please send it today",
        "instruction": "Make this professional and concise.",
        "protected": ["Q2", "today"],
        "requires_change": True,
    },
    {
        "id": "phase5-rewrite-delete-greeting",
        "kind": "rewrite",
        "category": "selected-arbitrary",
        "gate": "selected-query",
        "input": "Hi Avery, please share the Q2 deliverables today.",
        "instruction": "Remove only the greeting.",
        "must_exclude": ["Hi Avery"],
        "protected": ["Q2", "deliverables", "today"],
        "requires_change": True,
    },
    {
        "id": "phase5-rewrite-summarize",
        "kind": "rewrite",
        "category": "selected-arbitrary",
        "gate": "selected-query",
        "input": "Priya reviewed the FastAPI logs, found an OAuth callback error, and asked Rahul to update Q2 documentation.",
        "instruction": "Summarize this in one short sentence without losing the people or technologies.",
        "protected": ["Priya", "FastAPI", "OAuth", "Rahul", "Q2"],
        "max_length_ratio": 0.99,
        "requires_change": True,
    },
    {
        "id": "phase5-polish-email-layout",
        "kind": "polish",
        "category": "destination-formatting",
        "input": "hi Avery\n\nwhat is the status of the Q2 deliverables\n\nregards Rahul",
        "must_include": ["Avery", "Q2", "deliverables", "Rahul"],
        "protected": ["Avery", "Q2", "Rahul"],
        "destination_ids": ["gmail"],
    },
    {
        "id": "phase5-polish-list",
        "kind": "polish",
        "category": "destination-formatting",
        "input": "create a list first review the API second update Priya third deploy on Tuesday",
        "protected": ["API", "Priya", "Tuesday"],
        "required_structure": "bullets",
        "requires_change": True,
        "excluded_destination_ids": ["powershell"],
    },
    {
        "id": "phase5-polish-terminal",
        "kind": "polish",
        "category": "destination-formatting",
        "input": "cd into c drive users avery documents voice pilot and then run npm install",
        "must_include": ["npm install"],
        "requires_change": True,
        "destination_ids": ["powershell"],
    },
    {
        "id": "phase5-polish-hindi-correction",
        "kind": "polish",
        "category": "multilingual-correction",
        "gate": "language-preservation",
        "language": "hi",
        "input": "\u092e\u0940\u091f\u093f\u0902\u0917 \u0938\u094b\u092e\u0935\u093e\u0930 \u0915\u094b \u0939\u0948, \u0928\u0939\u0940\u0902 \u092e\u0902\u0917\u0932\u0935\u093e\u0930 \u0915\u094b \u0939\u0948\u0964",
        "must_include": ["\u092e\u0902\u0917\u0932\u0935\u093e\u0930"],
        "must_exclude": ["\u0938\u094b\u092e\u0935\u093e\u0930"],
        "required_scripts": ["devanagari"],
    },
    {
        "id": "phase5-polish-french-correction",
        "kind": "polish",
        "category": "multilingual-correction",
        "gate": "language-preservation",
        "language": "fr",
        "input": "Envoyez-le lundi, non, mardi.",
        "must_include": ["mardi"],
        "must_exclude": ["lundi"],
    },
    {
        "id": "phase5-polish-spanish-correction",
        "kind": "polish",
        "category": "multilingual-correction",
        "gate": "language-preservation",
        "language": "es",
        "input": "Env\u00edalo el lunes, perd\u00f3n, el martes.",
        "must_include": ["martes"],
        "must_exclude": ["lunes", "perd\u00f3n"],
    },
    {
        "id": "phase5-polish-hinglish",
        "kind": "polish",
        "category": "multilingual-correction",
        "gate": "language-preservation",
        "language": "mix-hi-en",
        "input": "Please send it \u0938\u094b\u092e\u0935\u093e\u0930 \u0915\u094b, no wait, \u092e\u0902\u0917\u0932\u0935\u093e\u0930 \u0915\u094b send it.",
        "must_include": ["\u092e\u0902\u0917\u0932\u0935\u093e\u0930"],
        "must_exclude": ["\u0938\u094b\u092e\u0935\u093e\u0930", "no wait"],
        "required_scripts": ["latin", "devanagari"],
    },
    {
        "id": "phase5-polish-date-number",
        "kind": "polish",
        "category": "protected-facts",
        "gate": "protected-facts",
        "input": "um revenue reached 18.5 lakhs on 12 July 2026 in Q2",
        "protected": ["18.5 lakhs", "12 July 2026", "Q2"],
        "must_exclude": ["um"],
        "requires_change": True,
    },
    {
        "id": "phase5-polish-uncertainty",
        "kind": "polish",
        "category": "intent-preservation",
        "gate": "intent-preservation",
        "input": "I think the Redis issue might possibly affect OAuth but I am not sure.",
        "protected": ["Redis", "OAuth"],
        "must_include_any": [["think", "might", "possibly", "not sure", "uncertain"]],
    },
    {
        "id": "phase5-rewrite-title-case",
        "kind": "rewrite",
        "category": "selected-arbitrary",
        "gate": "selected-query",
        "input": "winsper release plan",
        "instruction": "Convert this to title case.",
        "must_include": ["Winsper Release Plan"],
        "requires_change": True,
    },
    {
        "id": "phase5-polish-extra-fillers",
        "kind": "polish",
        "category": "filler-cleanup",
        "input": "um please uh review the API and send the update to Priya on Tuesday",
        "must_include": ["API", "Priya", "Tuesday"],
        "must_exclude": ["um", "uh"],
        "protected": ["API", "Priya", "Tuesday"],
        "requires_change": True,
    },
)


def expand_phase5_cases(cases: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    base = [
        case
        for case in cases
        if case.get("suite") == "polish" or case.get("kind") == "rewrite"
    ]
    base.extend(copy.deepcopy(EXTRA_CASES))
    expanded: list[dict[str, Any]] = []
    for case in base:
        declared_destination = copy.deepcopy(case.get("destination") or {})
        allowed_destinations = {str(item) for item in case.get("destination_ids") or []}
        excluded_destinations = {str(item) for item in case.get("excluded_destination_ids") or []}
        destinations: list[tuple[str, dict[str, Any]]] = []
        if declared_destination:
            label = str(declared_destination.get("app_label") or case.get("app_label") or "declared")
            destination_id = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-") or "declared"
            destinations.append((destination_id, declared_destination))
        else:
            destinations.extend((destination.id, asdict(destination)) for destination in DESTINATIONS)

        for destination_id, destination in destinations:
            if allowed_destinations and destination_id not in allowed_destinations:
                continue
            if destination_id in excluded_destinations:
                continue
            variant = copy.deepcopy(case)
            variant["id"] = f"{case['id']}--{destination_id}"
            variant["suite"] = "phase5"
            variant["app_label"] = str(destination.get("app_label") or variant.get("app_label") or "E2E test")
            variant["destination"] = destination
            variant["phase5_branch"] = "selected" if case.get("kind") == "rewrite" else "dictated"
            if case.get("category") in {"self-correction", "filler-cleanup"}:
                variant.setdefault("requires_change", True)
            expanded.append(variant)
    return expanded


def evaluate_phase5_release(results: Iterable[object]) -> dict[str, Any]:
    executed = [
        result
        for result in results
        if getattr(result, "suite", "") == "phase5"
        and getattr(result, "status", "") != "skip"
    ]
    failures = [result for result in executed if getattr(result, "status", "") in {"fail", "error"}]
    inference_latencies = [
        inference_ms
        for result in executed
        if (inference_ms := _inference_ms(result)) is not None
    ]
    p95_ms = _percentile(inference_latencies, 95)
    model_labels = sorted(
        {
            str(_metric(result, "rewrite_model"))
            for result in executed
            if _metric(result, "rewrite_model")
        }
    )
    latency_target_ms = _latency_target_ms(model_labels)
    latency_ready = p95_ms is not None and p95_ms <= latency_target_ms
    branches = {
        branch: _branch_summary(executed, branch)
        for branch in ("dictated", "selected")
    }
    branches_ready = all(summary["executed"] > 0 and summary["failed"] == 0 for summary in branches.values())
    single_model_ready = len(model_labels) == 1
    return {
        "ready": len(executed) >= 500 and not failures and latency_ready and branches_ready and single_model_ready,
        "executed": len(executed),
        "passed": len(executed) - len(failures),
        "failed": len(failures),
        "coverage_target": 500,
        "warm_p95_ms": p95_ms,
        "latency_target_ms": latency_target_ms,
        "latency_ready": latency_ready,
        "models": model_labels,
        "single_model_ready": single_model_ready,
        "branches": branches,
        "failed_gates": sorted(
            {
                str(getattr(result, "gate", "") or "ungated")
                for result in failures
            }
        ),
    }


def _branch_summary(results: list[object], branch: str) -> dict[str, Any]:
    expected_kind = "rewrite" if branch == "selected" else "polish"
    branch_results = [result for result in results if getattr(result, "kind", "") == expected_kind]
    failures = [result for result in branch_results if getattr(result, "status", "") in {"fail", "error"}]
    inference_latencies = [
        inference_ms
        for result in branch_results
        if (inference_ms := _inference_ms(result)) is not None
    ]
    return {
        "executed": len(branch_results),
        "passed": len(branch_results) - len(failures),
        "failed": len(failures),
        "warm_p95_ms": _percentile(inference_latencies, 95),
        "failed_gates": sorted(
            {
                str(getattr(result, "gate", "") or "ungated")
                for result in failures
            }
        ),
    }


def _metric(result: object, key: str):
    metrics = getattr(result, "metrics", {})
    return metrics.get(key) if isinstance(metrics, dict) else None


def _inference_ms(result: object) -> float | None:
    prompt_ms = _metric(result, "llama_prompt_ms")
    predicted_ms = _metric(result, "llama_predicted_ms")
    if isinstance(prompt_ms, (int, float)) and isinstance(predicted_ms, (int, float)):
        return float(prompt_ms) + float(predicted_ms)
    return None


def _latency_target_ms(model_labels: list[str]) -> float:
    labels = " ".join(model_labels).casefold()
    if "qwen 3 8b" in labels:
        return 2500.0
    if "llama 3.2 3b" in labels or "llama-3.2-3b" in labels:
        return 1000.0
    return 2000.0


def _percentile(values: list[float], percentage: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentage / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction
