from voicepilot.app_context import AppContextDetector, browser_label_for_domain, domain_matches, matches_process
from voicepilot.config import AppConfig


def test_process_matching_requires_the_exact_executable_alias():
    assert matches_process("Code.exe", "code.exe")
    assert matches_process(r"C:\Program Files\Microsoft VS Code\Code.exe", "code.exe")
    assert not matches_process("mycode.exe", "code.exe")
    assert not matches_process("code.exe.backup", "code.exe")


def test_process_lookalike_does_not_select_a_builtin_profile():
    detector = AppContextDetector(AppConfig())

    assert detector._match_profile("code.exe", "Editor") == "code"
    assert detector._match_profile("mycode.exe", "Editor") == "general"


def test_single_label_domain_rule_matches_only_a_complete_hostname_label():
    assert domain_matches("confluence", "confluence")
    assert domain_matches("confluence.example", "confluence")
    assert domain_matches("docs.confluence.example", "confluence")
    assert not domain_matches("notconfluence.example", "confluence")
    assert not domain_matches("confluence-lookalike.example", "confluence")


def test_full_domain_rule_preserves_exact_and_subdomain_matching():
    assert domain_matches("github.com", "github.com")
    assert domain_matches("gist.github.com", "github.com")
    assert domain_matches("teams.example", "*.example")
    assert not domain_matches("notgithub.com", "github.com")


def test_domain_lookalike_does_not_select_a_profile_or_known_label():
    detector = AppContextDetector(AppConfig())

    assert detector._match_profile("chrome.exe", "Confluence", "team.confluence.example") == "docs"
    assert detector._match_profile("chrome.exe", "Confluence", "notconfluence.example") == "general"
    assert browser_label_for_domain("notconfluence.example") == "notconfluence.example"
