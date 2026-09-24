from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path

import pytest

from devtools import release_candidate


def _cycle(index: int, *, status: str = "pass", startup_ms: float = 100.0, shutdown_ms: float = 50.0):
    return {
        "cycle": index,
        "status": status,
        "pid": 1000 + index,
        "startup_ms": startup_ms if status == "pass" else None,
        "shutdown_ms": shutdown_ms if status == "pass" else None,
        "exit_code": 0 if status == "pass" else 1,
        "resource_samples": [
            {
                "process_count": 2,
                "working_set_bytes": 120 * release_candidate.MIB,
                "private_bytes": 80 * release_candidate.MIB,
                "handles": 100,
                "threads": 12,
            },
            {
                "process_count": 3,
                "working_set_bytes": 140 * release_candidate.MIB,
                "private_bytes": 90 * release_candidate.MIB,
                "handles": 120,
                "threads": 15,
            },
        ]
        if status == "pass"
        else [],
        "error": "" if status == "pass" else "readiness timeout",
    }


def test_percentile_and_stats_are_stable_for_small_samples():
    assert release_candidate.percentile([], 95) is None
    assert release_candidate.percentile([10], 95) == 10
    assert release_candidate.percentile([0, 100], 95) == 95
    assert release_candidate.percentile([0, 100], -10) == 0
    assert release_candidate.percentile([0, 100], 110) == 100

    assert release_candidate.metric_stats([30, 10, 20]) == {
        "samples": 3,
        "min": 10.0,
        "p50": 20.0,
        "p95": 29.0,
        "max": 30.0,
    }


def test_readiness_requires_exact_state_detail_and_launch_pid():
    ready = {"status": "listening", "detail": "Hotkeys active", "pid": "4321"}

    assert release_candidate.state_is_ready(ready, 4321)
    assert release_candidate.state_is_ready(
        {**ready, "pid": 4322},
        4321,
        allowed_descendant_pids={4321, 4322},
    )
    assert not release_candidate.state_is_ready({**ready, "pid": 9999}, 4321)
    assert not release_candidate.state_is_ready(
        {**ready, "pid": 9999},
        4321,
        allowed_descendant_pids={4321, 4322},
    )
    assert not release_candidate.state_is_ready({**ready, "status": "not_running"}, 4321)
    assert not release_candidate.state_is_ready({**ready, "detail": "HUD ready"}, 4321)
    assert not release_candidate.state_is_ready([], 4321)


def test_descendant_pids_follow_only_the_selected_process_tree():
    processes = {
        10: {"parent_pid": 1},
        11: {"parent_pid": 10},
        12: {"parent_pid": 11},
        20: {"parent_pid": 1},
        21: {"parent_pid": 20},
    }

    assert release_candidate.descendant_pids(10, processes) == {10, 11, 12}
    assert release_candidate.descendant_pids(99, processes) == set()


def test_descendant_pids_reject_stale_parent_pid_reuse(monkeypatch):
    processes = {
        10: {"parent_pid": 1},
        11: {"parent_pid": 10},
        20: {"parent_pid": 10},
        21: {"parent_pid": 20},
    }
    creation_times = {10: 100, 11: 110, 20: 50, 21: 60}
    monkeypatch.setattr(
        release_candidate,
        "_process_creation_time",
        creation_times.get,
    )

    assert release_candidate.descendant_pids(
        10,
        processes,
        minimum_creation_time=creation_times[10],
    ) == {10, 11}


def test_aggregation_reports_lifecycle_and_resource_peaks():
    results = [
        _cycle(1, startup_ms=100, shutdown_ms=40),
        _cycle(2, startup_ms=200, shutdown_ms=60),
    ]
    summary = release_candidate.aggregate_results(results)

    assert summary["passed_cycles"] == 2
    assert summary["startup_ms"]["p50"] == 150
    assert summary["startup_ms"]["p95"] == 195
    assert summary["post_ready_resource_peaks"]["private_bytes"] == 90 * release_candidate.MIB

    failed_summary = release_candidate.aggregate_results([*results, _cycle(3, status="fail")])
    assert failed_summary["passed_cycles"] == 2
    assert failed_summary["failed_cycles"] == 1


def test_report_is_human_readable_and_includes_cycle_failure():
    cycles = [_cycle(1), _cycle(2, status="fail")]
    summary = release_candidate.aggregate_results(cycles)
    manifest = {
        "run_id": "20260719T120000Z",
        "winsper_version": "0.2.2",
        "package_version": "0.2.2.0",
        "target_sha256": "abc123",
        "target": "Winsper.exe",
        "mode": "package",
    }
    metrics = {"passed": False, "summary": summary, "cycles": cycles}

    report = release_candidate.render_report(manifest, metrics)

    assert "# Winsper release-candidate lifecycle report" in report
    assert "Lifecycle result: **FAIL**" in report
    assert "90.0 MiB" in report
    assert "post-ready" in report
    assert "abc123" in report
    assert "readiness timeout" in report


def test_build_command_supports_source_and_package_targets(monkeypatch, tmp_path: Path):
    python = tmp_path / "python.exe"
    executable = tmp_path / "Winsper.exe"
    config = tmp_path / "config.yaml"
    monkeypatch.setattr(release_candidate.sys, "executable", str(python))

    assert release_candidate.build_command("source", config) == [
        str(python.resolve()),
        "-m",
        "voicepilot",
        "--config",
        str(config),
        "--skip-setup",
    ]
    assert release_candidate.build_command("package", config, executable) == [
        str(executable.resolve()),
        "--config",
        str(config),
        "--skip-setup",
    ]
    with pytest.raises(ValueError, match="package executable"):
        release_candidate.build_command("package", config)

    args = release_candidate.build_parser().parse_args(
        ["--mode", "package", "--package-exe", str(executable), "--output", str(tmp_path / "reports")]
    )
    assert (args.mode, args.package_exe, args.output) == ("package", executable, tmp_path / "reports")
    assert args.settle_seconds == 3.0


def test_hash_and_version_comparison_are_deterministic(tmp_path: Path):
    target = tmp_path / "Winsper.exe"
    target.write_bytes(b"winsper-package")

    assert (
        release_candidate.sha256_file(target)
        == "ba58fed8de53f5cc8a582092501a65338ea2a5aadbbb3136453cc3694d2f60ec"
    )
    assert release_candidate.versions_match("0.2.2", "0.2.2.0")
    assert not release_candidate.versions_match("0.2.2", "0.2.3")


def test_child_environment_isolates_mutable_app_state_without_changing_userprofile(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("USERPROFILE", r"C:\Users\certifier")
    monkeypatch.setenv("UNCHANGED_SENTINEL", "kept")

    environment = release_candidate._isolated_child_environment(tmp_path / "cycle")

    profile_root = tmp_path / "cycle" / "profile"
    assert environment["APPDATA"] == str(profile_root / "AppData" / "Roaming")
    assert environment["LOCALAPPDATA"] == str(profile_root / "AppData" / "Local")
    assert environment["TEMP"] == str(profile_root / "Temp")
    assert environment["TMP"] == str(profile_root / "Temp")
    assert environment["USERPROFILE"] == r"C:\Users\certifier"
    assert environment["UNCHANGED_SENTINEL"] == "kept"
    assert Path(environment["APPDATA"]).is_dir()
    assert Path(environment["LOCALAPPDATA"]).is_dir()
    assert Path(environment["TEMP"]).is_dir()


def test_shutdown_waits_for_every_process_in_the_job(monkeypatch):
    class FakeProcess:
        pid = 4321

        def poll(self):
            return 0

    class FakeJob:
        def __init__(self):
            self.counts = iter((1, 0))
            self.queries = 0

        def active_process_count(self):
            self.queries += 1
            return next(self.counts)

    job = FakeJob()
    monkeypatch.setattr(release_candidate, "snapshot_processes", lambda: {})
    monkeypatch.setattr(release_candidate.time, "sleep", lambda _seconds: None)

    release_candidate._wait_for_process_tree_exit(FakeProcess(), job, {4321}, 1.0)

    assert job.queries == 2


def test_cleanup_reports_forced_job_containment(monkeypatch, tmp_path: Path):
    class FakeProcess:
        pid = 4321

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    class FakeJob:
        closed = False

        def active_process_count(self):
            return 1

        def close(self):
            self.closed = True

    job = FakeJob()
    monkeypatch.setattr(
        release_candidate,
        "_wait_for_process_tree_exit",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("late child")),
    )

    error = release_candidate._cleanup_managed_process(
        FakeProcess(),
        job,
        tmp_path / "config.yaml",
        {4321},
        shutdown_timeout_seconds=0.1,
    )

    assert "Forced cleanup was required for 1 process" in error
    assert job.closed


def test_cleanup_reports_job_query_failure(tmp_path: Path):
    class FakeProcess:
        pid = 4321

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    class FakeJob:
        closed = False

        def active_process_count(self):
            raise OSError("query failed")

        def close(self):
            self.closed = True

    job = FakeJob()
    error = release_candidate._cleanup_managed_process(
        FakeProcess(),
        job,
        tmp_path / "config.yaml",
        {4321},
        shutdown_timeout_seconds=0.1,
    )

    assert "Could not query Winsper process job during cleanup" in error
    assert job.closed


def test_cleanup_does_not_hide_query_failure_while_waiting(monkeypatch, tmp_path: Path):
    class FakeProcess:
        pid = 4321

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    class FakeJob:
        closed = False

        def __init__(self):
            self.counts = iter((1, 0))

        def active_process_count(self):
            return next(self.counts)

        def close(self):
            self.closed = True

    job = FakeJob()
    monkeypatch.setattr(
        release_candidate,
        "_wait_for_process_tree_exit",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("query failed while waiting")),
    )

    error = release_candidate._cleanup_managed_process(
        FakeProcess(),
        job,
        tmp_path / "config.yaml",
        {4321},
        shutdown_timeout_seconds=0.1,
    )

    assert "Could not query Winsper process job while awaiting cleanup" in error
    assert job.closed


def test_certification_emits_the_three_review_artifacts(monkeypatch, tmp_path: Path):
    config = tmp_path / "source-config.yaml"
    config.write_text("schema_version: 5\n", encoding="utf-8")
    monkeypatch.setattr(release_candidate, "_require_windows", lambda: None)
    monkeypatch.setattr(release_candidate, "run_cycle", lambda **kwargs: _cycle(kwargs["cycle"]))
    monkeypatch.setattr(release_candidate, "__version__", "9.9.9")
    args = Namespace(
        mode="source",
        config=config,
        package_exe=tmp_path / "Winsper.exe",
        cycles=2,
        output=tmp_path / "artifacts",
        startup_timeout_seconds=10.0,
        shutdown_timeout_seconds=5.0,
        settle_seconds=0.1,
        sample_interval_seconds=0.05,
    )

    run_dir, metrics = release_candidate.run_certification(args)

    assert metrics["passed"]
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "metrics.json").is_file()
    assert (run_dir / "report.md").is_file()
    assert '"winsper_version": "9.9.9"' in (run_dir / "manifest.json").read_text(encoding="utf-8")


def test_package_certification_records_and_checks_package_identity(monkeypatch, tmp_path: Path):
    config = tmp_path / "source-config.yaml"
    executable = tmp_path / "Winsper.exe"
    config.write_text("schema_version: 5\n", encoding="utf-8")
    executable.write_bytes(b"current-package")
    monkeypatch.setattr(release_candidate, "_require_windows", lambda: None)
    monkeypatch.setattr(release_candidate, "executable_product_version", lambda _path: "9.9.9.0")
    monkeypatch.setattr(release_candidate, "run_cycle", lambda **kwargs: _cycle(kwargs["cycle"]))
    monkeypatch.setattr(release_candidate, "__version__", "9.9.9")
    args = Namespace(
        mode="package",
        config=config,
        package_exe=executable,
        cycles=1,
        output=tmp_path / "artifacts",
        startup_timeout_seconds=10.0,
        shutdown_timeout_seconds=5.0,
        settle_seconds=0.1,
        sample_interval_seconds=0.05,
    )

    run_dir, metrics = release_candidate.run_certification(args)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert metrics["passed"]
    assert manifest["checkout_version"] == "9.9.9"
    assert manifest["package_version"] == "9.9.9.0"
    assert manifest["winsper_version"] == "9.9.9.0"
    assert manifest["target_sha256"] == release_candidate.sha256_file(executable)

    monkeypatch.setattr(release_candidate, "executable_product_version", lambda _path: "9.9.8.0")
    with pytest.raises(RuntimeError, match="does not match checkout"):
        release_candidate.run_certification(args)


def test_keyboard_interrupt_still_closes_the_launch_job(monkeypatch, tmp_path: Path):
    source_config = tmp_path / "config.yaml"
    source_config.write_text("schema_version: 5\n", encoding="utf-8")

    class FakeProcess:
        pid = 4321
        _handle = 9876

        def __init__(self) -> None:
            self.exit_code = None
            self.killed = False

        def poll(self):
            return self.exit_code

        def wait(self, timeout=None):
            self.exit_code = 1
            return self.exit_code

        def kill(self):
            self.killed = True
            self.exit_code = 1

    process = FakeProcess()
    events = []
    popen_arguments = {}

    class FakeJob:
        def __init__(self) -> None:
            self.assigned = False
            self.closed = False

        def assign(self, assigned_process) -> None:
            assert assigned_process is process
            self.assigned = True
            events.append("assigned")

        def active_process_count(self) -> int:
            return 0

        def close(self) -> None:
            self.closed = True
            process.exit_code = 1

    job = FakeJob()
    monkeypatch.setattr(release_candidate.ProcessJob, "create", lambda: job)
    monkeypatch.setattr(
        release_candidate.subprocess,
        "Popen",
        lambda *args, **kwargs: (popen_arguments.update(kwargs), process)[1],
    )
    monkeypatch.setattr(
        release_candidate,
        "resume_suspended_process",
        lambda pid: events.append(f"resumed:{pid}"),
    )
    monkeypatch.setattr(release_candidate, "_process_creation_time", lambda _pid: 100)
    monkeypatch.setattr(
        release_candidate,
        "_wait_for_ready",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(release_candidate, "_request_stop_quietly", lambda _path: None)

    with pytest.raises(KeyboardInterrupt):
        release_candidate.run_cycle(
            cycle=1,
            mode="source",
            source_config=source_config,
            cycle_dir=tmp_path / "cycle",
            package_executable=None,
            startup_timeout_seconds=1.0,
            shutdown_timeout_seconds=1.0,
            settle_seconds=0.0,
            sample_interval_seconds=0.1,
        )

    assert job.assigned
    assert job.closed
    assert process.poll() is not None
    assert popen_arguments["creationflags"] & release_candidate.CREATE_SUSPENDED
    assert popen_arguments["env"]["APPDATA"].startswith(str(tmp_path / "cycle"))
    assert popen_arguments["env"]["LOCALAPPDATA"].startswith(str(tmp_path / "cycle"))
    assert events == ["assigned", "resumed:4321"]
