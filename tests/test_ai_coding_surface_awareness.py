from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from voicepilot.ai_coding_surfaces import NATIVE_AI_CODING_SURFACES, WEB_AI_CODING_SURFACES
from voicepilot.app_context import (
    AppContextDetector,
    BrowserPageContext,
    WindowInfo,
    browser_label_for_domain,
    friendly_process_label,
)
from voicepilot.config import AppConfig
from voicepilot.config_migrations import CURRENT_SCHEMA_VERSION
from voicepilot.destination import infer_destination
from voicepilot.polish_prompts import build_polish_prompt, build_rewrite_prompt


@pytest.mark.parametrize(
    ("process", "expected_profile", "expected_destination", "expected_label"),
    (
        ("codex.exe", "prompt", "prompt", "Codex"),
        ("chatgpt.exe", "prompt", "prompt", "ChatGPT"),
        ("claude.exe", "prompt", "prompt", "Claude"),
        ("antigravity.exe", "prompt", "prompt", "Antigravity"),
        ("ollama app.exe", "prompt", "prompt", "Ollama"),
        ("antigravity ide.exe", "code", "code", "Antigravity IDE"),
        ("kiro.exe", "code", "code", "Kiro"),
        ("trae.exe", "code", "code", "TRAE"),
        ("zed.exe", "code", "code", "Zed"),
        ("vscodium.exe", "code", "code", "VSCodium"),
    ),
)
def test_popular_native_ai_coding_surface_routes_by_exact_process(
    process: str,
    expected_profile: str,
    expected_destination: str,
    expected_label: str,
) -> None:
    context = AppContextDetector(AppConfig()).detect_fast(WindowInfo(1, process, "Neutral workspace"))

    assert context.profile_name == expected_profile
    assert context.destination.kind == expected_destination
    assert friendly_process_label(process) == expected_label


@pytest.mark.parametrize("surface", WEB_AI_CODING_SURFACES, ids=lambda surface: surface.id)
def test_popular_web_ai_coding_surface_routes_by_verified_domain(surface) -> None:
    detector = AppContextDetector(AppConfig())
    context = detector._build_context(
        WindowInfo(1, "chrome.exe", surface.label),
        BrowserPageContext(surface.domain, browser_label_for_domain(surface.domain)),
    )

    assert context.profile_name == surface.profile
    assert context.destination.kind == surface.destination
    assert context.app_label == surface.label


@pytest.mark.parametrize(
    "process",
    (
        "mycodex.exe",
        "codex-helper.exe",
        "antigravity-helper.exe",
        "ollama.exe",
        "kiro-launcher.exe",
        "trae-agent.exe",
        "zed-update.exe",
    ),
)
def test_helpers_runtimes_and_process_lookalikes_do_not_impersonate_surfaces(process: str) -> None:
    context = AppContextDetector(AppConfig()).detect_fast(WindowInfo(1, process, "Neutral workspace"))

    assert context.profile_name == "general"
    assert context.destination.kind == "general"


@pytest.mark.parametrize(
    "title",
    (
        "Codex adoption plan",
        "Claude Code notes",
        "Ollama benchmark",
        "Antigravity evaluation",
        "Kiro migration",
    ),
)
def test_product_words_in_unrelated_native_titles_do_not_change_route(title: str) -> None:
    context = AppContextDetector(AppConfig()).detect_fast(WindowInfo(1, "notepad.exe", title))

    # Title words still cannot impersonate an AI/coding surface; Notepad keeps
    # its product-level Notes identity.
    assert context.profile_name == "notes"
    assert context.destination.kind == "notes"


@pytest.mark.parametrize("surface", WEB_AI_CODING_SURFACES, ids=lambda surface: surface.id)
def test_ai_coding_web_domain_lookalikes_stay_general(surface) -> None:
    spoofed = f"{surface.domain}.evil.example"
    detector = AppContextDetector(AppConfig())
    context = detector._build_context(
        WindowInfo(1, "chrome.exe", surface.label),
        BrowserPageContext(spoofed, browser_label_for_domain(spoofed)),
    )

    assert context.profile_name == "general"
    assert context.destination.kind == "general"


def test_builtin_web_registry_works_when_saved_config_predates_new_domains() -> None:
    config = AppConfig()
    config.browser_context.rules = []
    detector = AppContextDetector(config)
    context = detector._build_context(
        WindowInfo(1, "msedge.exe", "Replit"),
        BrowserPageContext("replit.com", "Replit"),
    )

    assert context.profile_name == "code"
    assert context.destination.kind == "code"


def test_registry_processes_are_unique_and_normalized() -> None:
    processes = [
        process
        for surface in NATIVE_AI_CODING_SURFACES
        for process in surface.processes
    ]

    assert processes == [process.casefold() for process in processes]
    assert len(processes) == len(set(processes))


def test_cli_agents_remain_terminal_context_instead_of_fake_native_apps() -> None:
    for title in (
        "Claude Code",
        "Codex CLI",
        "Gemini CLI",
        "GitHub Copilot CLI",
        "Amazon Q Developer CLI",
        "Aider",
        "OpenCode",
        "Goose",
        "ollama run",
    ):
        destination = infer_destination("windowsterminal.exe", title, "code", "Windows Terminal")
        assert destination.kind == "terminal"


@pytest.mark.parametrize(
    ("process", "title"),
    (
        ("code.exe", "GitHub Copilot Chat"),
        ("code.exe", "Cline"),
        ("code.exe", "Roo Code"),
        ("code.exe", "Continue"),
        ("code.exe", "Gemini Code Assist"),
        ("code.exe", "Amazon Q Developer"),
        ("idea64.exe", "JetBrains AI Assistant"),
    ),
)
def test_embedded_ai_assistants_inherit_verified_editor_route(process: str, title: str) -> None:
    context = AppContextDetector(AppConfig()).detect_fast(WindowInfo(1, process, title))

    assert context.profile_name == "code"
    assert context.destination.kind == "code"


def test_all_ai_coding_surfaces_use_generic_prompts_with_metadata_only_identity() -> None:
    config = AppConfig()
    rendered: dict[tuple[str, str], set[str]] = {}
    surfaces = [*NATIVE_AI_CODING_SURFACES, *WEB_AI_CODING_SURFACES]
    for surface in surfaces:
        profile = config.profiles.styles[surface.profile]
        destination = infer_destination("", "", surface.profile, surface.label)
        cleanup = build_polish_prompt(
            "what should we change in module alpha",
            [],
            profile,
            surface.label,
            destination,
        )
        selection = build_rewrite_prompt(
            "Module alpha is delayed pending review.",
            "Make this concise without changing its status.",
            [],
            profile,
            surface.label,
            destination,
        )
        identity = f"App: {surface.label}"
        normalized_cleanup = cleanup.replace(identity, "App: <APP>")
        normalized_selection = selection.replace(identity, "App: <APP>")
        rendered.setdefault((surface.profile, "cleanup"), set()).add(normalized_cleanup)
        rendered.setdefault((surface.profile, "selection"), set()).add(normalized_selection)

    assert all(len(prompts) == 1 for prompts in rendered.values())


def test_example_config_lists_every_new_surface_identity() -> None:
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "config.example.yaml").read_text(encoding="utf-8"))
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION
    configured_processes = {
        process.casefold()
        for rule in data["profiles"]["rules"]
        for process in rule["processes"]
    }
    configured_domains = {
        domain.casefold()
        for rule in data["browser_context"]["rules"]
        for domain in rule["domains"]
    }

    expected_processes = {
        process
        for surface in NATIVE_AI_CODING_SURFACES
        for process in surface.processes
    }
    expected_domains = {surface.domain for surface in WEB_AI_CODING_SURFACES}
    assert expected_processes <= configured_processes
    assert expected_domains <= configured_domains


def test_live_e2e_inventory_has_both_modes_for_every_ai_coding_surface() -> None:
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "e2e" / "cases.yaml").read_text(encoding="utf-8"))
    case_ids = {case["id"] for case in data["cases"]}
    surface_ids = {
        surface.id
        for surface in (*NATIVE_AI_CODING_SURFACES, *WEB_AI_CODING_SURFACES)
    }

    assert {f"polish-ai-{surface_id}" for surface_id in surface_ids} <= case_ids
    assert {f"prompt-ai-{surface_id}" for surface_id in surface_ids} <= case_ids
