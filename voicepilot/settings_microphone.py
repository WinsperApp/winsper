from __future__ import annotations

from threading import Thread

from .audio_safety import is_bluetooth_microphone_name
from .system_audio import display_audio_device_name, resolve_microphone_route

_AUTOMATIC = "Windows default"
_NO_MICROPHONE = "__winsper_no_microphone__"


def microphone_preference_value(widget) -> str:
    """Return the saved route even when the control is showing a live fallback."""

    preferred = widget.property("preferredMicrophone")
    if preferred is not None:
        return str(preferred)
    data = widget.currentData() if hasattr(widget, "currentData") else None
    return str(data if data is not None else widget.currentText()).strip()


def microphone_home_status(
    preferred: str | int | None,
    available: list[str],
) -> tuple[str, str, str]:
    route = resolve_microphone_route(preferred, available)
    if route.active:
        return display_audio_device_name(route.active), "", "neutral"
    return "No microphone found", "Check Windows sound settings.", "bad"


def build_microphone_selector(owner, page, voice_layout, list_devices):
    from PySide6.QtCore import QObject, QTimer, Signal
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    from .settings_widgets import create_settings_combo

    configured = str(owner.config.audio.input_device or "")
    preferred = (
        _AUTOMATIC
        if not configured or is_bluetooth_microphone_name(configured)
        else configured
    )
    device_combo = create_settings_combo(lambda: owner.palette)
    device_combo.addItem(
        "Automatic — Recommended" if preferred == _AUTOMATIC else display_audio_device_name(preferred),
        preferred,
    )
    device_combo.setProperty("preferredMicrophone", preferred)
    device_combo.setAccessibleName("Microphone")
    owner.widgets["audio.input_device"] = device_combo

    microphone_status = QLabel()
    microphone_status.setObjectName("MicrophoneRouteStatus")
    microphone_status.setWordWrap(True)
    microphone_status.setMinimumWidth(280)
    microphone_status.setMaximumWidth(368)
    microphone_status.setAccessibleName("Microphone problem")
    microphone_status.hide()

    microphone_control = QWidget()
    microphone_control_layout = QVBoxLayout(microphone_control)
    microphone_control_layout.setContentsMargins(0, 0, 0, 0)
    microphone_control_layout.setSpacing(6)
    microphone_control_layout.addWidget(device_combo)
    microphone_control_layout.addWidget(microphone_status)
    owner._simple_row(
        voice_layout,
        "Microphone",
        "Automatic is recommended.",
        microphone_control,
        compact=True,
    )

    class AudioDeviceLoader(QObject):
        loaded = Signal(object)

    device_loader = AudioDeviceLoader(owner.window)
    available_devices: list[str] = []
    scan_in_progress = False
    def set_items(items: list[tuple[str, str]]) -> None:
        existing = [
            (device_combo.itemText(index), str(device_combo.itemData(index) or ""))
            for index in range(device_combo.count())
        ]
        if existing == items:
            return
        device_combo.blockSignals(True)
        device_combo.clear()
        for label, value in items:
            device_combo.addItem(label, value)
        device_combo.blockSignals(False)

    def refresh_control() -> None:
        saved = str(device_combo.property("preferredMicrophone") or _AUTOMATIC)
        route = resolve_microphone_route(
            None if saved == _AUTOMATIC else saved,
            available_devices,
        )
        if not route.active:
            set_items([("No microphone found", _NO_MICROPHONE)])
            device_combo.setCurrentIndex(0)
            device_combo.setEnabled(False)
            device_combo.setAccessibleDescription(
                "No microphone is available. Check Windows sound settings."
            )
            microphone_status.setText("Check Windows sound settings.")
            microphone_status.setAccessibleDescription(
                "No microphone is available. Check Windows sound settings."
            )
            owner._set_tone(microphone_status, "bad")
            microphone_status.show()
            return

        items = [("Automatic — Recommended", _AUTOMATIC)]
        items.extend((display_audio_device_name(device), device) for device in available_devices)
        set_items(items)
        active_index = device_combo.findData(route.active)
        device_combo.blockSignals(True)
        device_combo.setCurrentIndex(active_index if active_index >= 0 else 0)
        device_combo.blockSignals(False)
        device_combo.setEnabled(True)
        active_name = display_audio_device_name(route.active)
        description = f"Currently using {active_name}."
        if route.using_fallback:
            description += " Winsper will return to your preferred microphone when it is available."
        device_combo.setAccessibleDescription(description)
        microphone_status.clear()
        microphone_status.hide()

    def select_microphone(index: int) -> None:
        value = str(device_combo.itemData(index) or "")
        if not value or value == _NO_MICROPHONE:
            return
        device_combo.setProperty("preferredMicrophone", value)
        owner._auto_save()
        refresh_control()

    def apply_audio_devices(discovered: object) -> None:
        nonlocal scan_in_progress
        scan_in_progress = False
        if not isinstance(discovered, list):
            return
        available_devices[:] = discovered
        refresh_control()

    def load_audio_devices() -> None:
        try:
            discovered = list_devices()
        except Exception:
            discovered = []
        try:
            device_loader.loaded.emit(discovered)
        except RuntimeError:
            pass

    def start_audio_device_scan() -> None:
        nonlocal scan_in_progress
        if scan_in_progress or not page.isVisible():
            return
        scan_in_progress = True
        Thread(target=load_audio_devices, name="WinsperAudioDeviceScan", daemon=True).start()

    device_loader.loaded.connect(apply_audio_devices)
    device_combo.activated.connect(select_microphone)
    owner._audio_device_loader = device_loader
    device_scan_timer = QTimer(owner.window)
    device_scan_timer.setInterval(2000)
    device_scan_timer.timeout.connect(start_audio_device_scan)
    device_scan_timer.start()
    owner._audio_device_scan_timer = device_scan_timer
    scan_in_progress = True
    Thread(target=load_audio_devices, name="WinsperAudioDeviceScan", daemon=True).start()
    return device_combo
