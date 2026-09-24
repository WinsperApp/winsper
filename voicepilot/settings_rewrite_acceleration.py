from __future__ import annotations

import queue
from threading import Event, Thread
from types import SimpleNamespace

from .ai_catalog import runtime_candidates
from .ai_hardware import detect_ai_hardware_quick
from .ai_runtime import (
    RuntimeProgress,
    install_runtime,
    probe_runtime,
    runtime_executable,
    runtime_is_installed,
    runtime_probe_supports_bundle,
    select_runtime_device_entry,
)
from .llama_server import bundled_llama_server_available
from .settings_helpers import friendly_check_error
from .settings_widgets import ToggleSwitch
from .windows_ui import animate_progress_value


def build_polish_acceleration_controls(owner, embedded_card):
    from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton

    owner._line("rewrite.llama_device", owner.config.rewrite.llama_device)
    gpu_layers_widget = owner._line(
        "rewrite.llama_gpu_layers",
        str(owner.config.rewrite.llama_gpu_layers),
    )
    ai_hardware = detect_ai_hardware_quick()
    bundles = runtime_candidates(ai_hardware)
    bundled_cpu = bundled_llama_server_available()
    preferred_bundle = bundles[0] if bundles else None
    acceleration_bundle = preferred_bundle if preferred_bundle is not None and preferred_bundle.backend != "cpu" else None
    recommended_bundle = acceleration_bundle or (None if bundled_cpu else preferred_bundle)

    def recommended_gpu_name() -> str:
        if not ai_hardware.gpus:
            return "Windows GPU"
        if recommended_bundle is not None and recommended_bundle.device_vendor:
            matched = next(
                (gpu for gpu in ai_hardware.gpus if gpu.vendor == recommended_bundle.device_vendor),
                None,
            )
            if matched is not None:
                return matched.name
        return ai_hardware.gpus[0].name

    runtime_state = {
        "installed": recommended_bundle is not None and runtime_is_installed(recommended_bundle),
        "verified": None,
        "downloading": False,
        "device_name": "",
        "busy": False,
    }
    runtime_status = QLabel()
    runtime_status.setObjectName("HardwareAccelerationStatus")
    runtime_status.setWordWrap(True)
    embedded_card.addWidget(runtime_status)
    runtime_progress = QProgressBar()
    runtime_progress.setRange(0, 100)
    runtime_progress.setValue(0)
    runtime_progress.setObjectName("ModelDownloadProgress")
    runtime_progress.setVisible(False)
    embedded_card.addWidget(runtime_progress)
    if recommended_bundle is not None and recommended_bundle.backend == "cuda":
        runtime_action = "NVIDIA acceleration"
    elif acceleration_bundle is recommended_bundle:
        runtime_action = "GPU acceleration"
    else:
        runtime_action = "runtime"
    install_runtime_button = QPushButton()
    install_runtime_button.setObjectName("HardwareAccelerationButton")
    install_runtime_button.setEnabled(recommended_bundle is not None)
    embedded_card.addWidget(install_runtime_button)
    runtime_cancel_button = QPushButton("Cancel")
    runtime_cancel_button.setObjectName("DownloadControlButton")
    runtime_cancel_button.setAccessibleName("Cancel acceleration download")
    runtime_cancel_button.hide()
    embedded_card.addWidget(runtime_cancel_button)
    remove_runtime_button = QPushButton("Use CPU instead")
    remove_runtime_button.setObjectName("DownloadControlButton")
    remove_runtime_button.setEnabled(bool(runtime_state["installed"]))
    embedded_card.addWidget(remove_runtime_button)
    install_runtime_button.hide()
    remove_runtime_button.hide()
    acceleration_toggle = ToggleSwitch.create(
        checked=False,
        accent=owner.palette.accent,
        accent2=owner.palette.accent_2,
    )
    acceleration_toggle.setObjectName("HardwareAccelerationToggle")
    acceleration_toggle.setAccessibleName(f"Use {runtime_action}")
    acceleration_toggle.setAccessibleDescription("Use compatible graphics hardware for Polish. Turn this off to use CPU.")
    owner.theme_toggles.append(acceleration_toggle)
    embedded_card.addWidget(acceleration_toggle)

    def set_acceleration_toggle(checked: bool) -> None:
        acceleration_toggle.setCheckedInstantly(checked)

    def cpu_mode_selected() -> bool:
        return gpu_layers_widget.text().strip() == "0"

    def refresh_runtime_surface() -> None:
        installed = bool(runtime_state["installed"])
        verified = runtime_state["verified"]
        busy = bool(runtime_state["busy"])
        using_cpu = cpu_mode_selected()
        downloading = bool(runtime_state["downloading"])
        acceleration_toggle.setVisible(recommended_bundle is not None)
        acceleration_toggle.setEnabled(recommended_bundle is not None and not busy)
        set_acceleration_toggle(busy or (installed and not using_cpu and verified is not False))
        install_runtime_button.hide()
        remove_runtime_button.hide()
        runtime_cancel_button.setVisible(busy and downloading)
        if recommended_bundle is None:
            runtime_status.setText("CPU mode ready · no additional setup required")
            owner._set_tone(runtime_status, "neutral")
            install_runtime_button.setText("CPU mode active")
            install_runtime_button.setEnabled(False)
            remove_runtime_button.setEnabled(False)
            remove_runtime_button.hide()
            return
        if busy:
            owner._set_tone(runtime_status, "neutral")
            runtime_status.setText(
                f"{recommended_gpu_name()} · checking {runtime_action}"
                if installed
                else f"{recommended_gpu_name()} · installing {runtime_action}"
            )
            install_runtime_button.setText("Checking..." if installed else "Installing...")
        elif using_cpu:
            owner._set_tone(runtime_status, "neutral")
            runtime_status.setText(f"CPU mode active · {recommended_gpu_name()} acceleration remains available")
            install_runtime_button.setText(f"Use {runtime_action}")
        elif verified is True:
            owner._set_tone(runtime_status, "accent")
            device_name = str(runtime_state["device_name"] or recommended_gpu_name())
            label = "NVIDIA acceleration enabled" if recommended_bundle.backend == "cuda" else "GPU acceleration enabled"
            runtime_status.setText(f"{device_name} · {label}")
            install_runtime_button.setText("Check again")
        elif installed and verified is False:
            owner._set_tone(runtime_status, "warn")
            runtime_status.setText(f"{recommended_gpu_name()} · {runtime_action} needs repair · CPU remains active")
            install_runtime_button.setText(f"Repair {runtime_action}")
        elif installed:
            owner._set_tone(runtime_status, "neutral")
            runtime_status.setText(f"{recommended_gpu_name()} · {runtime_action} selected")
            install_runtime_button.setText("Check acceleration")
        else:
            owner._set_tone(runtime_status, "neutral")
            runtime_status.setText(f"{recommended_gpu_name()} · {runtime_action} available")
            verb = "Enable" if acceleration_bundle is recommended_bundle else "Install"
            install_runtime_button.setText(f"{verb} {runtime_action}")
        install_runtime_button.setEnabled(not busy)
        remove_runtime_button.setVisible(installed and not using_cpu)
        remove_runtime_button.setEnabled(installed and not busy and not using_cpu)

        install_runtime_button.hide()
        remove_runtime_button.hide()

    def cancel_runtime_install() -> None:
        cancel_event = owner.ai_runtime_cancel_event
        if cancel_event is None:
            return
        cancel_event.set()
        runtime_cancel_button.setEnabled(False)
        runtime_status.setText("Cancelling download...")

    runtime_cancel_button.clicked.connect(cancel_runtime_install)

    def start_runtime_install() -> None:
        if recommended_bundle is None:
            return
        from PySide6.QtCore import QTimer

        enable_after_probe = cpu_mode_selected()
        verify_only = bool(runtime_state["installed"]) and runtime_state["verified"] is not False
        events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        cancel_event = Event()
        owner.ai_runtime_cancel_event = cancel_event
        runtime_state["busy"] = True
        runtime_state["downloading"] = not verify_only
        runtime_progress.setVisible(not verify_only)
        runtime_cancel_button.setVisible(not verify_only)
        runtime_cancel_button.setEnabled(True)
        refresh_runtime_surface()

        def progress(value: RuntimeProgress) -> None:
            events.put(("progress", value))

        def worker() -> None:
            try:
                if not verify_only:
                    install_runtime(
                        recommended_bundle,
                        progress_callback=progress,
                        cancel_event=cancel_event,
                    )
                    runtime_state["installed"] = True
                probe = probe_runtime(runtime_executable(recommended_bundle))
                if not runtime_probe_supports_bundle(recommended_bundle, probe):
                    detail = probe.error or f"No compatible {recommended_bundle.backend} device found."
                    raise RuntimeError(detail)
                _device, device_name = select_runtime_device_entry(
                    recommended_bundle,
                    probe,
                    ai_hardware,
                )
                events.put(("done", device_name))
            except Exception as exc:
                events.put(("error", exc))

        timer = QTimer(owner.window)
        owner.ai_runtime_install_timer = timer

        def poll() -> None:
            while True:
                try:
                    event, payload = events.get_nowait()
                except queue.Empty:
                    return
                if event == "progress":
                    value = payload
                    if isinstance(value, RuntimeProgress):
                        runtime_status.setText(value.status)
                        if value.percent is not None:
                            animate_progress_value(runtime_progress, value.percent)
                    continue
                timer.stop()
                owner.ai_runtime_install_timer = None
                owner.ai_runtime_cancel_event = None
                runtime_state["busy"] = False
                runtime_state["downloading"] = False
                runtime_progress.setVisible(False)
                runtime_cancel_button.hide()
                if event == "done":
                    runtime_state["verified"] = True
                    runtime_state["device_name"] = str(payload or "")
                    if enable_after_probe:
                        gpu_layers_widget.setText("auto")
                        owner._save(silent=True)
                    refresh_runtime_surface()
                    owner.status.setText("Hardware acceleration enabled." if enable_after_probe else "Hardware acceleration verified.")
                else:
                    runtime_state["verified"] = False
                    refresh_runtime_surface()
                    if cancel_event.is_set():
                        runtime_status.setText("Acceleration download cancelled. CPU remains active.")
                        owner._set_tone(runtime_status, "neutral")
                        owner.status.setText("Acceleration download cancelled.")
                    else:
                        owner.status.setText(f"Acceleration unavailable; CPU remains active. {friendly_check_error(payload)}")

        timer.timeout.connect(poll)
        timer.start(100)
        Thread(target=worker, name="WinsperRuntimeInstaller", daemon=True).start()

    install_runtime_button.clicked.connect(start_runtime_install)

    def use_cpu() -> None:
        gpu_layers_widget.setText("0")
        owner._save(silent=True)
        refresh_runtime_surface()
        owner.status.setText("Polish now uses CPU. NVIDIA acceleration remains installed.")

    remove_runtime_button.clicked.connect(use_cpu)

    def toggle_acceleration(enabled: bool) -> None:
        if enabled:
            start_runtime_install()
        else:
            use_cpu()

    acceleration_toggle.toggled.connect(toggle_acceleration)
    refresh_runtime_surface()

    return SimpleNamespace(
        runtime_status=runtime_status,
        runtime_progress=runtime_progress,
        acceleration_toggle=acceleration_toggle,
        runtime_cancel_button=runtime_cancel_button,
        runtime_action=runtime_action,
    )
