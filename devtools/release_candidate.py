"""Windows GUI lifecycle and resource certification for a Winsper build.

This repository-only harness launches Winsper with an isolated copy of a real
configuration, waits for the same PID-bound readiness state used by the app,
measures the complete descendant process tree, and requests a normal shutdown
through Winsper's existing control file.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from voicepilot import __version__
from voicepilot.control import request_control_command
from voicepilot.storage import atomic_write_json, atomic_write_text

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPTHREAD = 0x00000004
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
THREAD_SUSPEND_RESUME = 0x0002
CREATE_SUSPENDED = 0x00000004
INVALID_SUSPEND_COUNT = 0xFFFFFFFF
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
MIB = 1024 * 1024


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    ]


class ProcessJob:
    """Own a Windows Job Object that contains and cleans up one launch tree."""

    def __init__(self, handle: int) -> None:
        self._handle = handle

    @classmethod
    def create(cls) -> ProcessJob:
        kernel32 = _kernel32()
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            kernel32.CloseHandle(handle)
            raise error
        return cls(handle)

    def assign(self, process: subprocess.Popen[Any]) -> None:
        if not _kernel32().AssignProcessToJobObject(self._handle, int(process._handle)):  # noqa: SLF001
            raise ctypes.WinError(ctypes.get_last_error())

    def active_process_count(self) -> int:
        if not self._handle:
            raise RuntimeError("Winsper process job is already closed.")
        accounting = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        returned_length = wintypes.DWORD()
        if not _kernel32().QueryInformationJobObject(
            self._handle,
            JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            ctypes.byref(returned_length),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(accounting.ActiveProcesses)

    def close(self) -> None:
        if not self._handle:
            return
        handle, self._handle = self._handle, 0
        if not _kernel32().CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def percentile(values: Iterable[float], percent: float) -> float | None:
    """Return an interpolated percentile without requiring a statistics package."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    bounded = min(100.0, max(0.0, float(percent)))
    rank = (len(ordered) - 1) * bounded / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def metric_stats(values: Iterable[float]) -> dict[str, float | int | None]:
    ordered = sorted(float(value) for value in values)
    return {
        "samples": len(ordered),
        "min": ordered[0] if ordered else None,
        "p50": percentile(ordered, 50),
        "p95": percentile(ordered, 95),
        "max": ordered[-1] if ordered else None,
    }


def state_is_ready(
    payload: object,
    expected_pid: int,
    *,
    allowed_descendant_pids: set[int] | None = None,
) -> bool:
    if not isinstance(payload, dict):
        return False
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    pid_matches = pid == expected_pid or (
        allowed_descendant_pids is not None and pid in allowed_descendant_pids
    )
    return (
        pid_matches
        and str(payload.get("status") or "").strip().casefold() == "listening"
        and str(payload.get("detail") or "").strip().casefold() == "hotkeys active"
    )


def descendant_pids(
    root_pid: int,
    processes: dict[int, dict[str, Any]],
    *,
    minimum_creation_time: int | None = None,
) -> set[int]:
    """Return the root and all descendants from one immutable process snapshot."""
    if root_pid not in processes:
        return set()
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, process in processes.items():
            if pid in descendants or int(process.get("parent_pid") or 0) not in descendants:
                continue
            if minimum_creation_time is not None:
                created_at = _process_creation_time(pid)
                if created_at is None or created_at < minimum_creation_time:
                    continue
            if pid not in descendants:
                descendants.add(pid)
                changed = True
    return descendants


def peak_resources(samples: Sequence[dict[str, Any]]) -> dict[str, int]:
    fields = ("process_count", "working_set_bytes", "private_bytes", "handles", "threads")
    return {field: max((int(sample.get(field) or 0) for sample in samples), default=0) for field in fields}


def aggregate_results(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    passed = [result for result in results if result.get("status") == "pass"]
    peaks = [peak_resources(result.get("resource_samples") or []) for result in passed]
    return {
        "cycles": len(results),
        "passed_cycles": len(passed),
        "failed_cycles": len(results) - len(passed),
        "startup_ms": metric_stats(result["startup_ms"] for result in passed if result.get("startup_ms") is not None),
        "shutdown_ms": metric_stats(result["shutdown_ms"] for result in passed if result.get("shutdown_ms") is not None),
        "post_ready_resource_peaks": {
            field: max((peak[field] for peak in peaks), default=0)
            for field in ("process_count", "working_set_bytes", "private_bytes", "handles", "threads")
        },
    }


def render_report(manifest: dict[str, Any], metrics: dict[str, Any]) -> str:
    summary = metrics["summary"]
    lines = [
        "# Winsper release-candidate lifecycle report",
        "",
        f"- Run: `{manifest['run_id']}`",
        f"- Winsper: `{manifest['winsper_version']}`",
        f"- Target: `{manifest['target']}`",
        f"- Mode: `{manifest['mode']}`",
        f"- Lifecycle result: **{'PASS' if metrics['passed'] else 'FAIL'}**",
        "",
        "## Summary",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Cycles | {summary['passed_cycles']} / {summary['cycles']} passed |",
        f"| Startup p50 | {_format_ms(summary['startup_ms']['p50'])} |",
        f"| Startup p95 | {_format_ms(summary['startup_ms']['p95'])} |",
        f"| Shutdown p50 | {_format_ms(summary['shutdown_ms']['p50'])} |",
        f"| Shutdown p95 | {_format_ms(summary['shutdown_ms']['p95'])} |",
        f"| Post-ready peak process count | {summary['post_ready_resource_peaks']['process_count']} |",
        f"| Post-ready peak working set | {_format_bytes(summary['post_ready_resource_peaks']['working_set_bytes'])} |",
        f"| Post-ready peak private bytes | {_format_bytes(summary['post_ready_resource_peaks']['private_bytes'])} |",
        f"| Post-ready peak handles | {summary['post_ready_resource_peaks']['handles']} |",
        f"| Post-ready peak threads | {summary['post_ready_resource_peaks']['threads']} |",
    ]
    if manifest.get("package_version"):
        lines.extend(
            [
                f"| Packaged ProductVersion | {manifest['package_version']} |",
                f"| Packaged SHA-256 | `{manifest['target_sha256']}` |",
            ]
        )
    lines.extend(
        [
            "",
            "## Cycles",
            "",
            "| Cycle | Status | Startup | Shutdown | Peak private | Peak working set | Processes |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for result in metrics["cycles"]:
        peak = peak_resources(result.get("resource_samples") or [])
        lines.append(
            f"| {result['cycle']} | {str(result['status']).upper()} | {_format_ms(result.get('startup_ms'))} | "
            f"{_format_ms(result.get('shutdown_ms'))} | {_format_bytes(peak['private_bytes'])} | "
            f"{_format_bytes(peak['working_set_bytes'])} | {peak['process_count']} |"
        )
        if result.get("error"):
            lines.append(f"\nCycle {result['cycle']} error: `{_markdown_text(result['error'])}`")
    lines.extend(
        [
            "",
            "The harness uses Winsper's normal PID-bound readiness state and stop control file. "
            "It does not instrument the product or collect user telemetry.",
            "",
            "PASS certifies lifecycle correctness for these cycles. Performance values are informational, "
            "not pass/fail budgets. Resource peaks cover readiness and the configured post-ready settle window; "
            "they do not claim to represent pre-ready startup or shutdown peaks.",
            "",
        ]
    )
    return "\n".join(lines)


def build_command(mode: str, config_path: Path, package_executable: Path | None = None) -> list[str]:
    arguments = ["--config", str(config_path), "--skip-setup"]
    if mode == "source":
        return [str(Path(sys.executable).resolve()), "-m", "voicepilot", *arguments]
    if mode == "package":
        if package_executable is None:
            raise ValueError("A package executable is required in package mode.")
        return [str(package_executable.resolve()), *arguments]
    raise ValueError(f"Unsupported launch mode: {mode}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def executable_product_version(path: Path) -> str:
    """Read ProductVersion from a packaged Windows executable's version resource."""
    _require_windows()
    version = _version_dll()
    unused = wintypes.DWORD()
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(unused))
    if not size:
        raise RuntimeError(f"Packaged executable has no readable version resource: {path}")
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    value = ctypes.c_void_p()
    value_size = wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(value_size)):
        raise ctypes.WinError(ctypes.get_last_error())
    if value_size.value < ctypes.sizeof(VS_FIXEDFILEINFO):
        raise RuntimeError(f"Packaged executable has an invalid version resource: {path}")
    info = ctypes.cast(value, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
    if info.dwSignature != 0xFEEF04BD:
        raise RuntimeError(f"Packaged executable has an invalid version signature: {path}")
    parts = (
        info.dwProductVersionMS >> 16,
        info.dwProductVersionMS & 0xFFFF,
        info.dwProductVersionLS >> 16,
        info.dwProductVersionLS & 0xFFFF,
    )
    return ".".join(str(part) for part in parts)


def versions_match(left: str, right: str) -> bool:
    def numeric_parts(value: str) -> tuple[int, ...]:
        parts = tuple(int(part) for part in value.strip().split("."))
        return parts + ((0,) * max(0, 4 - len(parts)))

    try:
        return numeric_parts(left) == numeric_parts(right)
    except ValueError:
        return left.strip().casefold() == right.strip().casefold()


def snapshot_processes() -> dict[int, dict[str, Any]]:
    _require_windows()
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    processes: dict[int, dict[str, Any]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while has_entry:
            pid = int(entry.th32ProcessID)
            processes[pid] = {
                "pid": pid,
                "parent_pid": int(entry.th32ParentProcessID),
                "threads": int(entry.cntThreads),
                "name": str(entry.szExeFile),
            }
            has_entry = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


def resume_suspended_process(pid: int) -> None:
    """Resume every initial thread after the launch process is safely job-contained."""
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    thread_ids: list[int] = []
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = bool(kernel32.Thread32First(snapshot, ctypes.byref(entry)))
        while has_entry:
            if int(entry.th32OwnerProcessID) == pid:
                thread_ids.append(int(entry.th32ThreadID))
            has_entry = bool(kernel32.Thread32Next(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    if not thread_ids:
        raise RuntimeError(f"Could not find the suspended launch thread for Winsper process {pid}.")
    for thread_id in thread_ids:
        handle = kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, thread_id)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if kernel32.ResumeThread(handle) == INVALID_SUSPEND_COUNT:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel32.CloseHandle(handle)


def sample_process_tree(
    root_pid: int,
    *,
    minimum_creation_time: int | None = None,
) -> dict[str, Any]:
    processes = snapshot_processes()
    pids = descendant_pids(
        root_pid,
        processes,
        minimum_creation_time=minimum_creation_time,
    )
    if not pids:
        raise RuntimeError(f"Winsper process {root_pid} is no longer running.")
    rows = []
    for pid in sorted(pids):
        base = processes[pid]
        resource = _process_resources(pid)
        rows.append(
            {
                "pid": pid,
                "parent_pid": base["parent_pid"],
                "name": base["name"],
                "working_set_bytes": resource["working_set_bytes"],
                "private_bytes": resource["private_bytes"],
                "handles": resource["handles"],
                "threads": base["threads"],
                "readable": resource["readable"],
            }
        )
    unreadable = [row["pid"] for row in rows if not row["readable"]]
    if unreadable:
        raise RuntimeError(f"Could not read resource counters for Winsper process-tree PIDs: {unreadable}.")
    return {
        "process_count": len(rows),
        "working_set_bytes": sum(row["working_set_bytes"] for row in rows),
        "private_bytes": sum(row["private_bytes"] for row in rows),
        "handles": sum(row["handles"] for row in rows),
        "threads": sum(row["threads"] for row in rows),
        "processes": rows,
    }


def run_cycle(
    *,
    cycle: int,
    mode: str,
    source_config: Path,
    cycle_dir: Path,
    package_executable: Path | None,
    startup_timeout_seconds: float,
    shutdown_timeout_seconds: float,
    settle_seconds: float,
    sample_interval_seconds: float,
) -> dict[str, Any]:
    cycle_dir.mkdir(parents=True, exist_ok=False)
    config_path = cycle_dir / "config.yaml"
    shutil.copy2(source_config, config_path)
    state_path = cycle_dir / "voicepilot.state.json"
    control_path = cycle_dir / "voicepilot.control"
    state_path.unlink(missing_ok=True)
    control_path.unlink(missing_ok=True)
    command = build_command(mode, config_path, package_executable)
    child_environment = _isolated_child_environment(cycle_dir)
    log_path = cycle_dir / "process.log"
    result: dict[str, Any] = {
        "cycle": cycle,
        "status": "fail",
        "pid": None,
        "startup_ms": None,
        "shutdown_ms": None,
        "exit_code": None,
        "resource_samples": [],
        "error": "",
    }
    process: subprocess.Popen[Any] | None = None
    process_job: ProcessJob | None = None
    known_pids: set[int] = set()
    interrupted: BaseException | None = None
    started_at = time.perf_counter()
    try:
        process_job = ProcessJob.create()
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            process = subprocess.Popen(
                command,
                cwd=str(_working_directory(mode, package_executable)),
                stdout=log,
                stderr=subprocess.STDOUT,
                close_fds=True,
                env=child_environment,
                creationflags=(
                    (subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
                    | CREATE_SUSPENDED
                ),
            )
            try:
                process_job.assign(process)
                resume_suspended_process(process.pid)
            except BaseException:
                process.kill()
                process.wait(timeout=2)
                raise
            result["pid"] = process.pid
            known_pids.add(process.pid)
            root_creation_time = _process_creation_time(process.pid)
            if root_creation_time is None:
                raise RuntimeError(f"Could not read Winsper process {process.pid} creation time.")
            _wait_for_ready(
                process,
                state_path,
                startup_timeout_seconds,
                minimum_creation_time=root_creation_time,
            )
            ready_at = time.perf_counter()
            result["startup_ms"] = (ready_at - started_at) * 1000
            ready_sample = sample_process_tree(
                process.pid,
                minimum_creation_time=root_creation_time,
            )
            ready_sample.update({"phase": "ready", "elapsed_ms": result["startup_ms"]})
            result["resource_samples"].append(ready_sample)
            known_pids.update(row["pid"] for row in ready_sample["processes"])

            settle_deadline = time.perf_counter() + max(0.0, settle_seconds)
            while time.perf_counter() < settle_deadline:
                time.sleep(min(max(0.01, sample_interval_seconds), max(0.0, settle_deadline - time.perf_counter())))
                sample = sample_process_tree(
                    process.pid,
                    minimum_creation_time=root_creation_time,
                )
                sample.update({"phase": "settled", "elapsed_ms": (time.perf_counter() - started_at) * 1000})
                result["resource_samples"].append(sample)
                known_pids.update(row["pid"] for row in sample["processes"])

            shutdown_started_at = time.perf_counter()
            request_control_command(config_path, "stop")
            _wait_for_process_tree_exit(
                process,
                process_job,
                known_pids,
                shutdown_timeout_seconds,
                minimum_creation_time=root_creation_time,
            )
            result["shutdown_ms"] = (time.perf_counter() - shutdown_started_at) * 1000
            result["exit_code"] = process.poll()
            if result["exit_code"] != 0:
                raise RuntimeError(f"Winsper exited with code {result['exit_code']} after shutdown.")
            result["status"] = "pass"
    except Exception as exc:
        result["error"] = str(exc)
    except BaseException as exc:
        interrupted = exc
    finally:
        cleanup_error = _cleanup_managed_process(
            process,
            process_job,
            config_path,
            known_pids,
            shutdown_timeout_seconds=min(2.0, shutdown_timeout_seconds),
        )
        if process is not None:
            result["exit_code"] = process.poll()
        if cleanup_error:
            result["status"] = "fail"
            result["error"] = "; ".join(filter(None, (result["error"], cleanup_error)))
        _remove_isolated_config_files(cycle_dir)
    if interrupted is not None:
        raise interrupted.with_traceback(interrupted.__traceback__)
    return result


def run_certification(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    _require_windows()
    source_config = args.config.resolve()
    if not source_config.is_file():
        raise FileNotFoundError(f"Winsper config not found: {source_config}")
    package_executable = args.package_exe.resolve() if args.mode == "package" else None
    if package_executable is not None and not package_executable.is_file():
        raise FileNotFoundError(f"Packaged Winsper executable not found: {package_executable}")

    package_version = executable_product_version(package_executable) if package_executable is not None else None
    if package_version is not None and not versions_match(package_version, __version__):
        raise RuntimeError(
            f"Packaged Winsper ProductVersion {package_version} does not match checkout version {__version__}. "
            "Build the current checkout before certifying it."
        )
    target_sha256 = sha256_file(package_executable) if package_executable is not None else None
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = args.output.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    target = package_executable if package_executable is not None else Path(sys.executable).resolve()
    manifest = {
        "schema_version": 2,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "winsper_version": package_version or __version__,
        "checkout_version": __version__,
        "package_version": package_version,
        "mode": args.mode,
        "target": str(target),
        "target_sha256": target_sha256,
        "windows_version": platform.platform(),
        "cycles": args.cycles,
        "startup_timeout_seconds": args.startup_timeout_seconds,
        "shutdown_timeout_seconds": args.shutdown_timeout_seconds,
        "settle_seconds": args.settle_seconds,
        "sample_interval_seconds": args.sample_interval_seconds,
    }
    atomic_write_json(run_dir / "manifest.json", manifest)

    results = [
        run_cycle(
            cycle=index,
            mode=args.mode,
            source_config=source_config,
            cycle_dir=run_dir / f"cycle-{index:03d}",
            package_executable=package_executable,
            startup_timeout_seconds=args.startup_timeout_seconds,
            shutdown_timeout_seconds=args.shutdown_timeout_seconds,
            settle_seconds=args.settle_seconds,
            sample_interval_seconds=args.sample_interval_seconds,
        )
        for index in range(1, args.cycles + 1)
    ]
    summary = aggregate_results(results)
    metrics = {
        "schema_version": 1,
        "passed": summary["failed_cycles"] == 0,
        "summary": summary,
        "cycles": results,
    }
    atomic_write_json(run_dir / "metrics.json", metrics)
    atomic_write_text(run_dir / "report.md", render_report(manifest, metrics))
    return run_dir, metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure Winsper GUI startup, resources, and clean shutdown.")
    parser.add_argument("--mode", choices=("source", "package"), default="source")
    parser.add_argument("--config", type=Path, default=None, help="Existing Winsper config to copy into each isolated cycle.")
    parser.add_argument("--package-exe", type=Path, default=Path("dist/Winsper/Winsper.exe"))
    parser.add_argument("--cycles", type=_positive_int, default=3)
    parser.add_argument("--output", type=Path, default=Path("artifacts/release-candidate"))
    parser.add_argument("--startup-timeout-seconds", type=_positive_float, default=30.0)
    parser.add_argument("--shutdown-timeout-seconds", type=_positive_float, default=15.0)
    parser.add_argument("--settle-seconds", type=_non_negative_float, default=3.0)
    parser.add_argument("--sample-interval-seconds", type=_positive_float, default=0.2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.config is None:
        from voicepilot.config import resolve_config_path

        args.config = resolve_config_path()
    try:
        run_dir, metrics = run_certification(args)
    except Exception as exc:
        parser.exit(2, f"Release-candidate harness failed: {exc}\n")
    print(f"Release-candidate report: {run_dir / 'report.md'}")
    return 0 if metrics["passed"] else 1


@cache
def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.Thread32First.argtypes = (wintypes.HANDLE, ctypes.POINTER(THREADENTRY32))
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = (wintypes.HANDLE, ctypes.POINTER(THREADENTRY32))
    kernel32.Thread32Next.restype = wintypes.BOOL
    kernel32.OpenThread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetProcessHandleCount.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetProcessHandleCount.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.K32GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
        wintypes.DWORD,
    )
    kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    return kernel32


@cache
def _version_dll():
    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p)
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = (
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    )
    version.VerQueryValueW.restype = wintypes.BOOL
    return version


def _process_resources(pid: int) -> dict[str, int | bool]:
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return {"working_set_bytes": 0, "private_bytes": 0, "handles": 0, "readable": False}
    try:
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        handle_count = wintypes.DWORD()
        memory_ok = bool(kernel32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb))
        handles_ok = bool(kernel32.GetProcessHandleCount(handle, ctypes.byref(handle_count)))
        return {
            "working_set_bytes": int(counters.WorkingSetSize) if memory_ok else 0,
            "private_bytes": int(counters.PrivateUsage) if memory_ok else 0,
            "handles": int(handle_count.value) if handles_ok else 0,
            "readable": memory_ok and handles_ok,
        }
    finally:
        kernel32.CloseHandle(handle)


def _process_creation_time(pid: int) -> int | None:
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        return (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    finally:
        kernel32.CloseHandle(handle)


def _wait_for_ready(
    process: subprocess.Popen[Any],
    state_path: Path,
    timeout_seconds: float,
    *,
    minimum_creation_time: int | None = None,
) -> None:
    deadline = time.perf_counter() + timeout_seconds
    mismatched_pid: int | None = None
    while time.perf_counter() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"Winsper exited before readiness with code {exit_code}.")
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            payload = None
        processes = snapshot_processes()
        launch_tree = descendant_pids(
            process.pid,
            processes,
            minimum_creation_time=minimum_creation_time,
        )
        if state_is_ready(payload, process.pid, allowed_descendant_pids=launch_tree):
            return
        if isinstance(payload, dict) and payload.get("pid"):
            try:
                mismatched_pid = int(payload["pid"])
            except (TypeError, ValueError):
                pass
        time.sleep(0.05)
    mismatch = f" State was written by PID {mismatched_pid}." if mismatched_pid is not None else ""
    raise TimeoutError(f"Winsper did not report Hotkeys active within {timeout_seconds:g} seconds.{mismatch}")


def _wait_for_process_tree_exit(
    process: subprocess.Popen[Any],
    process_job: ProcessJob,
    known_pids: set[int],
    timeout_seconds: float,
    *,
    minimum_creation_time: int | None = None,
) -> None:
    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        processes = snapshot_processes()
        known_pids.update(
            descendant_pids(
                process.pid,
                processes,
                minimum_creation_time=minimum_creation_time,
            )
        )
        active_processes = process_job.active_process_count()
        if process.poll() is not None and active_processes == 0:
            return
        time.sleep(0.05)
    alive = sorted(_alive_pids(known_pids))
    active_processes = process_job.active_process_count()
    raise TimeoutError(
        f"Winsper did not shut down cleanly within {timeout_seconds:g} seconds; "
        f"job active processes: {active_processes}; sampled remaining PIDs: {alive}."
    )


def _request_stop_quietly(config_path: Path) -> None:
    try:
        request_control_command(config_path, "stop")
    except OSError:
        pass


def _alive_pids(pids: Iterable[int]) -> set[int]:
    try:
        current = snapshot_processes()
    except OSError:
        return set()
    return set(pids).intersection(current)


def _cleanup_managed_process(
    process: subprocess.Popen[Any] | None,
    process_job: ProcessJob | None,
    config_path: Path,
    known_pids: set[int],
    *,
    shutdown_timeout_seconds: float,
) -> str:
    """Request normal shutdown, then close the owned Job Object to contain leftovers."""
    errors: list[str] = []
    if process is not None and process_job is not None:
        try:
            active_processes = process_job.active_process_count()
        except (OSError, RuntimeError) as exc:
            active_processes = None
            errors.append(f"Could not query Winsper process job during cleanup: {exc}")
        if active_processes:
            _request_stop_quietly(config_path)
            try:
                _wait_for_process_tree_exit(process, process_job, known_pids, shutdown_timeout_seconds)
            except (OSError, RuntimeError) as exc:
                errors.append(f"Could not query Winsper process job while awaiting cleanup: {exc}")
            except TimeoutError:
                pass
        try:
            remaining_processes = process_job.active_process_count()
        except (OSError, RuntimeError) as exc:
            remaining_processes = None
            if active_processes is not None:
                errors.append(f"Could not verify Winsper process job during cleanup: {exc}")
        if remaining_processes:
            errors.append(
                f"Forced cleanup was required for {remaining_processes} process(es) still active in the Winsper job."
            )
    elif process is not None and process.poll() is None:
        errors.append(f"Winsper root process {process.pid} was launched without an owned process job.")
    try:
        if process_job is not None:
            process_job.close()
    except OSError as exc:
        errors.append(f"Could not close Winsper process job: {exc}")
    if process is not None:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f"Could not stop Winsper root process {process.pid}: {exc}")
    return "; ".join(errors)


def _isolated_child_environment(cycle_dir: Path) -> dict[str, str]:
    """Isolate mutable app state without changing the user's USERPROFILE."""
    profile_root = cycle_dir / "profile"
    roaming = profile_root / "AppData" / "Roaming"
    local = profile_root / "AppData" / "Local"
    temp = profile_root / "Temp"
    for directory in (roaming, local, temp):
        directory.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "APPDATA": str(roaming),
            "LOCALAPPDATA": str(local),
            "TEMP": str(temp),
            "TMP": str(temp),
        }
    )
    return environment


def _remove_isolated_config_files(cycle_dir: Path) -> None:
    for path in cycle_dir.glob("config.yaml*"):
        if path.is_file():
            path.unlink(missing_ok=True)


def _working_directory(mode: str, package_executable: Path | None) -> Path:
    if mode == "package" and package_executable is not None:
        return package_executable.resolve().parent
    return Path(__file__).resolve().parents[1]


def _format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.1f} ms"


def _format_bytes(value: int) -> str:
    return f"{int(value) / MIB:.1f} MiB"


def _markdown_text(value: object) -> str:
    return str(value).replace("|", "\\|").replace("`", "'").replace("\r", " ").replace("\n", " ")


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("The release-candidate GUI lifecycle harness requires Windows.")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
