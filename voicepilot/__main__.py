from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app_context import ForegroundContext


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Winsper for Windows")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config YAML. Defaults to %%APPDATA%%\\Winsper\\config.yaml.",
    )
    parser.add_argument("--owner-pid", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--benchmark", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--model", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--models", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--device", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--compute-type", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--seconds", type=int, default=5, help=argparse.SUPPRESS)
    parser.add_argument("--audio-file", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--save-clip", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--expected-text", default="", help=argparse.SUPPRESS)
    parser.add_argument("--expected-file", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--warm-runs", type=int, default=5, help=argparse.SUPPRESS)
    parser.add_argument("--no-save", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print resolved config and exit.",
    )
    parser.add_argument(
        "--no-hud",
        action="store_true",
        help="Disable the floating Winsper HUD.",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Ask a running Winsper listener to quit cleanly.",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Ask a running Winsper listener to restart cleanly.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Ask a running Winsper listener to reload settings without restarting.",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="Ask a running Winsper listener to pause hotkey listening.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Ask a running Winsper listener to resume hotkey listening.",
    )
    parser.add_argument(
        "--test-hotkeys",
        action="store_true",
        help="Print hotkey start/stop events without recording or pasting.",
    )
    parser.add_argument(
        "--preview-hud",
        action="store_true",
        help="Show the HUD states briefly and exit.",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Open the Winsper settings window and exit when it closes.",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Open the Winsper history window and exit when it closes.",
    )
    parser.add_argument(
        "--preview-history",
        action="store_true",
        help="Show the history window briefly and exit.",
    )
    parser.add_argument(
        "--setup-wizard",
        action="store_true",
        help="Open the first-run setup wizard and exit when it closes.",
    )
    parser.add_argument(
        "--preview-onboarding",
        action="store_true",
        help="Show the first-run setup wizard briefly and exit.",
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Run Winsper without showing the first-run setup wizard.",
    )
    parser.add_argument(
        "--preview-settings",
        action="store_true",
        help="Show the settings window briefly and exit.",
    )
    parser.add_argument(
        "--print-app-context",
        action="store_true",
        help="Print the detected foreground app/window and matched profile.",
    )
    parser.add_argument(
        "--test-app-awareness",
        action="store_true",
        help="Wait briefly, then print a friendly foreground app, browser domain, and profile routing check.",
    )
    parser.add_argument(
        "--list-speech-models",
        action="store_true",
        help="Print speech model install status and exit.",
    )
    parser.add_argument(
        "--print-diagnostics",
        action="store_true",
        help="Print a local diagnostics report and exit.",
    )
    parser.add_argument(
        "--download-speech-model",
        default=None,
        help="Download a faster-whisper speech model and exit.",
    )
    return parser


def main() -> int:
    mp.freeze_support()
    from .branding import set_windows_app_user_model_id

    set_windows_app_user_model_id()
    args = build_parser().parse_args()
    if args.benchmark:
        from .benchmark import run_benchmark

        return run_benchmark(args)
    from .config import load_config, resolve_config_path

    config_path = resolve_config_path(args.config)
    config = load_config(config_path)
    from .model_storage import configure_model_storage

    configure_model_storage(config.model_storage.path)

    if args.no_hud:
        config.hud.enabled = False

    if args.stop:
        from .control import request_control_command
        from .instance import SingleInstanceGuard

        guard = SingleInstanceGuard(config_path)
        if guard.acquire():
            guard.release()
            print("Winsper is not running.")
            return 0
        path = request_control_command(config_path, "stop")
        print(f"Stop requested via {path}.")
        return 0

    if args.restart:
        from .control import request_control_command
        from .instance import SingleInstanceGuard

        guard = SingleInstanceGuard(config_path)
        if guard.acquire():
            guard.release()
            print("Winsper is not running. Starting it now.")
            _launch_main_instance(config_path, no_hud=args.no_hud)
            return 0
        path = request_control_command(config_path, "restart")
        print(f"Restart requested via {path}.")
        return 0

    if args.reload:
        from .control import request_control_command
        from .instance import SingleInstanceGuard

        guard = SingleInstanceGuard(config_path)
        if guard.acquire():
            guard.release()
            print("Winsper is not running.")
            return 0
        path = request_control_command(config_path, "reload")
        print(f"Reload requested via {path}.")
        return 0

    if args.pause:
        from .control import request_control_command
        from .instance import SingleInstanceGuard

        guard = SingleInstanceGuard(config_path)
        if guard.acquire():
            guard.release()
            print("Winsper is not running.")
            return 0
        path = request_control_command(config_path, "pause")
        print(f"Pause requested via {path}.")
        return 0

    if args.resume:
        from .control import request_control_command
        from .instance import SingleInstanceGuard

        guard = SingleInstanceGuard(config_path)
        if guard.acquire():
            guard.release()
            print("Winsper is not running.")
            return 0
        path = request_control_command(config_path, "resume")
        print(f"Resume requested via {path}.")
        return 0

    if args.print_config:
        from .config import config_to_dict

        print(json.dumps(config_to_dict(config), indent=2))
        return 0

    if args.print_diagnostics:
        from .diagnostics import collect_diagnostics, format_diagnostics_report

        print(format_diagnostics_report(collect_diagnostics(config, config_path)))
        return 0

    if args.print_app_context:
        from .app_context import AppContextDetector

        context = AppContextDetector(config).detect()
        print(
            json.dumps(
                {
                    "process_name": context.process_name,
                    "window_title": context.window_title,
                    "browser_domain": context.browser_domain,
                    "browser_label": context.browser_label,
                    "profile_name": context.profile_name,
                    "profile_label": context.profile.label,
                    "site_behavior": context.site_style.label if context.site_style else "",
                },
                indent=2,
            )
        )
        return 0

    if args.test_app_awareness:
        from .app_context import AppContextDetector

        print("Switch to the app or browser tab you want to test.")
        for seconds in [3, 2, 1]:
            print(f"Capturing in {seconds}...", flush=True)
            time.sleep(1)
        context = AppContextDetector(config).detect()
        print(format_app_awareness_report(context, config))
        return 0

    if args.list_speech_models:
        from .models import (
            detect_hardware,
            list_installed_models,
            recommended_model_for_hardware,
        )

        hardware = detect_hardware()
        recommended = recommended_model_for_hardware(hardware)
        print(
            json.dumps(
                {
                    "hardware": {
                        "cpu": hardware.cpu,
                        "ram_gb": hardware.ram_gb,
                        "gpus": list(hardware.gpus),
                        "has_nvidia": hardware.has_nvidia,
                        "has_intel_arc": hardware.has_intel_arc,
                    },
                    "recommended_model": recommended.model,
                    "models": [
                        {
                            "model": status.preset.model,
                            "label": status.preset.label,
                            "engine": status.preset.engine,
                            "tier": status.preset.tier,
                            "best_for": status.preset.best_for,
                            "device_hint": status.preset.device_hint,
                            "compute_hint": status.preset.compute_hint,
                            "repo_id": status.preset.repo_id,
                            "installed": status.installed,
                            "size_mb": status.size_mb,
                            "cache_path": str(status.cache_path) if status.cache_path else None,
                        }
                        for status in list_installed_models()
                    ],
                },
                indent=2,
            )
        )
        return 0

    if args.download_speech_model:
        from .models import (
            DownloadProgress,
            download_model,
            format_download_progress,
        )

        def report(progress: DownloadProgress) -> None:
            message = format_download_progress(progress)
            print(f"{progress.status}: {progress.model} - {message}", flush=True)

        path = download_model(args.download_speech_model, progress_callback=report)
        print(f"Downloaded {args.download_speech_model} to {path}")
        return 0

    if args.settings:
        from .settings_ui import run_settings_window

        run_settings_window(config_path, owner_process_id=args.owner_pid)
        return 0

    if args.history:
        from .settings_ui import run_settings_window

        run_settings_window(config_path, owner_process_id=args.owner_pid, initial_page="History")
        return 0

    if args.setup_wizard:
        from .onboarding_ui import run_onboarding_wizard

        run_onboarding_wizard(config_path)
        return 0

    if args.preview_onboarding:
        from .onboarding_ui import run_onboarding_wizard

        run_onboarding_wizard(config_path, auto_close_seconds=2.0)
        return 0

    if args.preview_settings:
        from .settings_ui import run_settings_window

        run_settings_window(config_path, auto_close_seconds=2.0)
        return 0

    if args.preview_history:
        from .settings_ui import run_settings_window

        run_settings_window(config_path, auto_close_seconds=2.0, initial_page="History")
        return 0

    if args.test_hotkeys:
        from .hotkeys import run_hotkey_test

        if not config.dictation.polish_enabled:
            print("Polish is disabled in config, so only Dictate is active in the main app.")
        run_hotkey_test(
            config.hotkeys.dictate,
            config.hotkeys.polish if config.dictation.polish_enabled else "",
            "",
            config.hotkeys.cancel,
        )
        return 0

    if args.preview_hud:
        from .hud_ui import create_status_hud

        hud = create_status_hud(config.hud)
        hud.start()
        time.sleep(0.3)
        hud.show("Listening", "Gmail - release to paste", "record")
        time.sleep(0.9)
        hud.show("Transcribing", "Gmail - tiny.en", "process")
        time.sleep(0.4)
        hud.show("Live transcript", "Hey, quick update from the design pass", "process")
        time.sleep(0.6)
        hud.show("Live transcript", "Hey, quick update from the design pass, the compact HUD feels cleaner", "process")
        time.sleep(0.7)
        hud.show("Polishing", "Claude - cleaning up", "rewrite")
        time.sleep(0.8)
        hud.show("Polished", "Claude - 42 words", "success")
        time.sleep(config.hud.auto_hide_seconds + 0.4)
        hud.stop()
        return 0

    if not args.skip_setup and not config.onboarding.completed:
        from .onboarding_ui import run_onboarding_wizard

        print("Opening Winsper first-run setup wizard.")
        completed = run_onboarding_wizard(config_path)
        if not completed:
            print("Setup was closed before completion. Re-run Winsper or pass --skip-setup to use defaults.")
            return 0
        config = load_config(config_path)
        configure_model_storage(config.model_storage.path)
        if args.no_hud:
            config.hud.enabled = False

    from .app import WinsperApp, _configure_logging
    from .instance import SingleInstanceGuard

    _configure_logging(config_path)
    guard = SingleInstanceGuard(config_path)
    if not guard.acquire():
        print("Winsper is already running.")
        return 0
    try:
        while True:
            app = WinsperApp(config, config_path)
            app.run()
            if not app.restart_requested:
                break
            config = load_config(config_path)
            configure_model_storage(config.model_storage.path)
            if args.no_hud:
                config.hud.enabled = False
    finally:
        guard.release()
    return 0


def _launch_main_instance(config_path: Path, no_hud: bool = False) -> None:
    from .process_launch import app_command, app_working_directory

    command = app_command(["--config", str(config_path), "--skip-setup"])
    if no_hud:
        command.append("--no-hud")
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    subprocess.Popen(command, cwd=str(app_working_directory()), close_fds=True, creationflags=creationflags)


def format_app_awareness_report(context: ForegroundContext, config: Any) -> str:
    domain = context.browser_domain or "Not detected"
    site = context.browser_label or "Not detected"
    source = app_awareness_source(context, config)
    status = app_awareness_status(context, config)
    lines = [
        "Winsper App Awareness",
        "",
        f"Active app: {context.app_label}",
        f"Process: {context.process_name or 'Unknown'}",
        f"Window title: {context.window_title or 'Unknown'}",
        f"Browser awareness: {'On' if config.browser_context.enabled else 'Off'}",
        f"Detected site: {site}",
        f"Detected domain: {domain}",
        f"Matched profile: {context.profile_name} ({context.profile.label})",
        f"Site behavior: {context.site_style.label if context.site_style else 'None'}",
        f"HUD label: {context.hud_context_label}",
        f"Matched by: {source}",
        f"Status: {status}",
    ]
    return "\n".join(lines) + "\n"


def app_awareness_source(context: ForegroundContext, config: Any) -> str:
    from .app_context import domain_matches, matches_process

    if context.browser_domain and config.browser_context.enabled:
        for rule in config.browser_context.rules:
            if any(domain_matches(context.browser_domain, pattern) for pattern in rule.domains):
                return "browser domain"

    process_lower = context.process_name.lower()
    title_lower = context.window_title.lower()
    for rule in config.profiles.rules:
        if any(matches_process(process_lower, pattern) for pattern in rule.processes):
            return "process rule"
        if any(pattern.lower() in title_lower for pattern in rule.title_contains):
            return "window title rule"
    return "default profile"


def app_awareness_status(context: ForegroundContext, config: Any) -> str:
    from .app_context import is_browser_process

    if not config.profiles.enabled:
        return "Profiles are off"
    if context.browser_domain:
        return "Good"
    if config.browser_context.enabled and is_browser_process(context.process_name, config.browser_context.browser_processes):
        return "Browser detected, but domain not readable"
    if context.process_name or context.window_title:
        return "Good"
    return "No foreground app detected"


if __name__ == "__main__":
    raise SystemExit(main())
