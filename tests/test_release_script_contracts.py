from __future__ import annotations

from pathlib import Path


def test_e2e_wrapper_exposes_release_certification_flags() -> None:
    script = Path("scripts/e2e.ps1").read_text(encoding="utf-8")

    assert '"phase5"' in script
    assert "[switch]$CertifyPhase4" in script
    assert "[switch]$CertifyPhase5" in script
    assert '$argsList += "--certify-phase4"' in script
    assert '$argsList += "--certify-phase5"' in script


def test_release_candidate_wrapper_matches_python_cli_contract() -> None:
    script = Path("scripts/certify-release-candidate.ps1").read_text(encoding="utf-8")

    assert '"-m", "devtools.release_candidate"' in script
    assert '"--config", $Config' in script
    assert '"--mode", $Mode' in script
    assert '"--cycles", [string]$Cycles' in script
    assert '"--output", $Output' in script
    assert '@("--package-exe", $PackageExe)' in script
    assert "build-release.ps1" in script
    assert "Test-Path -LiteralPath $PackageExe -PathType Leaf" in script


def test_installer_lifecycle_requires_explicit_machine_change_consent() -> None:
    script = Path("scripts/test-installer-lifecycle.ps1").read_text(encoding="utf-8")

    assert "if (-not $AllowDestructiveCurrentUserTest)" in script
    assert "A real Winsper installation is already registered" in script
    assert "Existing Winsper shortcuts or startup launchers" in script
    assert "$UninstallRegistryPaths" in script
    assert "Purge validation requires Winsper user-data roots to be absent" in script
    assert "Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop" in script
    assert "$LifecycleError = $_" in script
    assert "$CleanupErrors" in script
    assert "all cleanup steps were attempted" in script
    assert "-ErrorAction SilentlyContinue" not in script


def test_release_workflow_explicitly_opts_into_both_lifecycle_modes() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    invocation = (
        ".\\scripts\\test-installer-lifecycle.ps1 "
        "-InstallerPath $installer.FullName -AllowDestructiveCurrentUserTest"
    )
    assert invocation in workflow
    assert f"{invocation} -PreserveUserData" in workflow


def test_release_workflow_builds_from_its_own_virtual_environment() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "python -m venv .venv" in workflow
    assert workflow.count(".\\.venv\\Scripts\\python.exe -m pip") == 2
    assert '.\\.venv\\Scripts\\python.exe -c "from voicepilot import __version__' in workflow
    assert ".\\.venv\\Scripts\\python.exe scripts\\release_manifest.py" in workflow
    assert workflow.index("python -m venv .venv") < workflow.index("Build, test, and package")


def test_stable_publish_is_explicit_trust_aware_and_immutable() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    publisher = Path("scripts/publish-stable.ps1").read_text(encoding="utf-8")

    assert "type: boolean" in workflow
    assert "default: false" in workflow
    assert "if: ${{ inputs.publish }}" in workflow
    assert "release-inventory.json" in workflow
    assert "Get-AuthenticodeSignature" in publisher
    assert "[switch]$AllowUnsigned" in publisher
    assert "Unsigned release notice is missing" in publisher
    assert 'winsper-releases/stable.json' in publisher
    assert 'wrangler deploy' not in publisher
    assert "Immutable release already exists" in publisher
    assert "winsper-releases/$InstallerName" in publisher
    assert "$env:WINSPER_PYTHON" in publisher
    assert "Test-Path -LiteralPath $Python -PathType Leaf" in publisher
    assert '$PublicSize = [int64](@($Head.Headers["Content-Length"])[0])' in publisher
    early_access = Path("scripts/publish-early-access.ps1").read_text(encoding="utf-8")
    assert "Immutable release already exists" in early_access


def test_release_workflow_certifies_the_fresh_package_and_uploads_evidence() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "Certify packaged startup and shutdown" in workflow
    assert ".\\scripts\\certify-release-candidate.ps1 -Mode package" in workflow
    assert "c.onboarding.completed = True" in workflow
    assert "c.speech.preload_on_startup = False" in workflow
    assert "c.dictation.polish_enabled = False" in workflow
    assert "c.hotkeys.dictate = 'ctrl+alt+shift+f9'" in workflow
    assert "c.hotkeys.polish = 'ctrl+alt+shift+f10'" in workflow
    assert "c.hotkeys.cancel = 'ctrl+alt+shift+f11'" in workflow
    assert "artifacts/certification/release-package/**" in workflow
    assert "Production long-session application-action soak" in workflow
    assert "-m devtools.runtime_soak" in workflow
    assert "artifacts/certification/runtime-soak.json" in workflow
    assert workflow.index("Build, test, and package") < workflow.index("Certify packaged startup and shutdown")
    assert workflow.index("Verify Authenticode before execution") < workflow.index(
        "Certify packaged startup and shutdown"
    )
    assert workflow.index("Verify Authenticode before execution") < workflow.index(
        "Certify clean install and uninstall"
    )
    assert workflow.index("Certify packaged startup and shutdown") < workflow.index("Create update manifest")


def test_ci_runs_non_hardware_architecture_and_runtime_soak_gates() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "python scripts/check_architecture.py" in workflow
    assert 'python -m pytest -q -m "not hardware"' in workflow
    assert "python -m devtools.runtime_soak" in workflow
    assert "artifacts/certification/runtime-soak.json" in workflow


def test_release_build_runs_architecture_gate_before_tests() -> None:
    script = Path("scripts/build-release.ps1").read_text(encoding="utf-8")

    architecture = "& $Python .\\scripts\\check_architecture.py"
    tests = "& $Python -m pytest"
    assert architecture in script
    assert script.index(architecture) < script.index(tests)


def test_release_build_accepts_an_explicit_project_runtime() -> None:
    script = Path("scripts/build-release.ps1").read_text(encoding="utf-8")

    assert '[string]$Python = ".\\.venv\\Scripts\\python.exe"' in script
    assert "pass -Python" in script


def test_embedded_runtime_helper_binds_imports_to_the_release_checkout() -> None:
    script = Path("scripts/prepare_embedded_polish_runtime.py").read_text(encoding="utf-8")

    root_binding = "sys.path.insert(0, str(PROJECT_ROOT))"
    catalog_import = "from voicepilot.ai_catalog import runtime_bundle"
    assert root_binding in script
    assert script.index(root_binding) < script.index(catalog_import)


def test_installer_keeps_user_data_unless_user_chooses_to_remove_it() -> None:
    script = Path("installer/Winsper.iss").read_text(encoding="utf-8")

    assert "function ShouldRemoveUserData(): Boolean;" in script
    assert "Choose No to keep your data for a later reinstall." in script
    assert "if (CurUninstallStep <> usUninstall) or not ShouldRemoveUserData() then" in script
    assert "DelTree(RoamingDataPath, True, True, True)" in script
    assert "DelTree(LocalDataPath, True, True, True)" in script
    assert "--prepare-uninstall" not in script
    assert "license-recovery" not in script


def test_benchmark_wrapper_forwards_warm_run_count() -> None:
    script = Path("scripts/benchmark.ps1").read_text(encoding="utf-8")

    assert "[int]$WarmRuns = 5" in script
    assert '"--warm-runs", $WarmRuns' in script


def test_packaged_onboarding_uses_app_owned_marks() -> None:
    spec = Path("winsper.spec").read_text(encoding="utf-8")
    package_config = Path("pyproject.toml").read_text(encoding="utf-8")

    for filename in ("outlook.svg", "slack.png", "chatgpt.png", "vscode.png", "terminal.png"):
        assert filename in spec
        assert (Path("voicepilot") / "assets" / "apps" / filename).is_file()
        assert f'"assets/apps/{filename}"' in package_config
    assert 'root / "voicepilot" / "assets" / "apps" / app_mark' in spec
    assert 'root / "website"' not in spec


def test_packaged_distribution_includes_lgpl_license_text() -> None:
    spec = Path("winsper.spec").read_text(encoding="utf-8")

    assert '("COPYING", "COPYING.LGPL")' in spec
    assert 'assets.append((str(source), "licenses"))' in spec
