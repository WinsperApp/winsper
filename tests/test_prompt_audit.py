from voicepilot.config import AppConfig
from devtools.prompt_audit import audit_all_prompts


def test_every_constructed_prompt_contract_passes():
    results = audit_all_prompts(AppConfig())

    assert len(results) >= 40
    assert all(result.passed for result in results), [
        (result.name, result.failures) for result in results if not result.passed
    ]
    assert all(result.sha256 for result in results)
