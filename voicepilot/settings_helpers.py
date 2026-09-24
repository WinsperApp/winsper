from __future__ import annotations

from .audio import AudioRecorder
from .config import ProfileStyle
from .models import find_speech_model, installed_status
from .ollama import OLLAMA_DOWNLOAD_URL


def apply_qt_palette(app, palette, QColor, QPalette) -> None:
    qt_palette = QPalette()
    colors = {
        QPalette.Window: palette.bg,
        QPalette.WindowText: palette.text,
        QPalette.Base: palette.field,
        QPalette.AlternateBase: palette.surface_2,
        QPalette.ToolTipBase: palette.surface,
        QPalette.ToolTipText: palette.text,
        QPalette.Text: palette.text,
        QPalette.Button: palette.surface_2,
        QPalette.ButtonText: palette.text,
        QPalette.BrightText: palette.coral,
        QPalette.Highlight: palette.accent_2,
        QPalette.HighlightedText: palette.on_accent,
        QPalette.Link: palette.accent,
        QPalette.PlaceholderText: palette.subtle,
    }
    for role, value in colors.items():
        qt_palette.setColor(role, QColor(value))
    qt_palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(palette.subtle))
    qt_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(palette.subtle))
    qt_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(palette.subtle))
    qt_palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor(palette.surface_3))
    qt_palette.setColor(QPalette.Disabled, QPalette.HighlightedText, QColor(palette.muted))
    app.setPalette(qt_palette)


def small_label(text: str):
    from PySide6.QtWidgets import QLabel

    label = QLabel(text)
    label.setObjectName("Muted")
    return label


def text_value(widget) -> str:
    if hasattr(widget, "currentText"):
        return widget.currentText().strip()
    return widget.text().strip()


def combo_value(widget) -> str:
    return widget.currentText().strip()


def bool_value(widget) -> bool:
    return widget.isChecked()


def ollama_combo_values(installed: tuple[str, ...] | list[str], current: str = "") -> list[str]:
    values: list[str] = []
    for model in installed:
        model = (model or "").strip()
        if model and model not in values:
            values.append(model)
    return values


def ollama_selected_model(health, current: str = "") -> str:
    current = (current or "").strip()
    if health.models and any(model_matches(current, model) for model in health.models):
        return current
    return ""


def model_matches(requested: str, candidate: str) -> bool:
    requested = (requested or "").strip()
    candidate = (candidate or "").strip()
    if not requested or not candidate:
        return False
    return candidate == requested or (":" not in requested and candidate.split(":", 1)[0] == requested)


def ollama_status_text(health) -> str:
    if not health.reachable:
        return health.message or "Ollama background service is not reachable"
    if health.models and health.model_available:
        return f"Ollama connection established · {health.model}"
    if health.models:
        return "Ollama background service is running. Choose a detected local model."
    return "Ollama background service is running, but no models are installed"


def ollama_detail_text(health, _selected_model: str) -> str:
    if not health.reachable:
        return health.detail or (f"Start the Ollama background service, then check again. If needed, get it from {OLLAMA_DOWNLOAD_URL}.")
    if health.models:
        preview = ", ".join(health.models[:5])
        suffix = "" if len(health.models) <= 5 else f", +{len(health.models) - 5} more"
        latency = f" Response: {health.latency_ms} ms." if health.latency_ms is not None else ""
        available = "Polish is available." if health.model_available else "Select a detected model or pull the chosen model."
        return f"Detected local models: {preview}{suffix}. {available}{latency} Ollama can keep running after its window closes."
    return "No local models are installed. Install one in Ollama, then check again."


def ollama_tone(health) -> str:
    if health.reachable and health.model_available:
        return "accent"
    if health.reachable:
        return "warn"
    return "bad"


def ollama_status_bar_text(health) -> str:
    if health.reachable and health.model_available:
        return "Ollama background service verified. Polish is available."
    if health.reachable and health.models:
        return "Ollama background service is running. Choose one of the detected models."
    if health.reachable:
        return "Ollama background service is running, but no local models are installed."
    return "Ollama background service is not ready yet."


def add_list_item(list_widget, entry) -> None:
    value = entry.text().strip()
    if not value:
        return
    existing = {list_widget.item(index).text().lower() for index in range(list_widget.count())}
    if value.lower() not in existing:
        list_widget.addItem(value)
    entry.clear()


def remove_selected(list_widget) -> None:
    for item in list_widget.selectedItems():
        list_widget.takeItem(list_widget.row(item))


def audio_levels(samples) -> tuple[float, float]:
    import numpy as np

    if samples is None or len(samples) == 0:
        return 0.0, 0.0
    absolute = np.abs(samples)
    peak = float(np.max(absolute))
    rms = float(np.sqrt(np.mean(np.square(samples))))
    return peak, rms


def stop_recorder_quietly(recorder: AudioRecorder) -> None:
    try:
        if getattr(recorder, "_recording", False):
            recorder.stop()
    except Exception:
        pass
    finally:
        try:
            recorder.close()
        except Exception:
            pass


def dictation_model_status(model: str) -> tuple[str, str]:
    preset = find_speech_model(model)
    if preset is None:
        return f"Preparing {model}", "Custom models can take a while the first time they load."
    status = installed_status(preset, include_size=False)
    if status.installed:
        return f"Loading {model}", "Model is cached locally. First load can still take a little while."
    return f"Downloading {model}", "First-time model download can take a few minutes. This happens once."


def friendly_check_error(exc: BaseException) -> str:
    text = str(exc).strip()
    lowered = text.lower()
    if not text:
        return "Try again."
    if "microphone" in lowered or "audio" in lowered or "input device" in lowered:
        return "Check the microphone selection and Windows microphone permission."
    if "hotkey" in lowered or "keyboard" in lowered or "pynput" in lowered:
        return "Try a different hotkey, or restart Winsper and test again."
    if "cuda" in lowered or "cublas" in lowered or "cudnn" in lowered:
        return "CUDA is not available on this machine. Use CPU/int8 for dictation, or install the NVIDIA runtime later."
    if "model" in lowered or "download" in lowered or "huggingface" in lowered:
        return "Check the selected speech model or internet connection for the first download."
    return text[:180]


def list_items(list_widget) -> list[str]:
    return [list_widget.item(index).text().strip() for index in range(list_widget.count()) if list_widget.item(index).text().strip()]


def profile_templates() -> dict[str, tuple[str, ProfileStyle]]:
    return {
        "Email": (
            "email",
            ProfileStyle(
                label="Polished email",
                dictation_prompt="Prefer complete sentences and a polished professional email tone.",
                rewrite_prompt="Use a polished but direct professional tone suitable for email.",
            ),
        ),
        "Chat": (
            "chat",
            ProfileStyle(
                label="Chat concise",
                dictation_prompt="Prefer concise conversational phrasing suitable for chat messages.",
                rewrite_prompt="Keep the response short, friendly, and easy to scan.",
            ),
        ),
        "Code": (
            "code",
            ProfileStyle(
                label="Code-aware",
                dictation_prompt="Preserve code identifiers, file names, CLI flags, and technical terms exactly when possible.",
                rewrite_prompt="Preserve code identifiers, file paths, API names, and technical terms. Avoid smart quotes around code.",
                vocabulary=["API", "CLI", "JSON", "YAML", "PowerShell", "VS Code", "Cursor"],
            ),
        ),
        "Docs": (
            "docs",
            ProfileStyle(
                label="Docs polished",
                dictation_prompt="Prefer structured prose suitable for notes or documentation.",
                rewrite_prompt="Make the text structured, clear, and documentation-friendly.",
            ),
        ),
        "Notes": (
            "notes",
            ProfileStyle(
                label="Notes",
                dictation_prompt=(
                    "Clean spoken notes into compact, scannable text. Preserve intentional fragments, headings, "
                    "checklists, ordering, and line breaks. Add structure only when spoken or clearly list-like."
                ),
                rewrite_prompt=(
                    "Follow the requested edit while preserving note structure, facts, unfinished thoughts, "
                    "checkboxes, ordering, and intentional line breaks. Do not add unsupported details."
                ),
            ),
        ),
        "AI prompt": (
            "prompt",
            ProfileStyle(
                label="Prompt-aware",
                dictation_prompt=(
                    "Transform rough speech into a direct AI-assistant prompt. Preserve constraints, examples, "
                    "desired output, filenames, code identifiers, and quoted text. Do not answer the prompt."
                ),
                rewrite_prompt=(
                    "Make the text a precise AI-assistant prompt with task, context, constraints, and desired output. "
                    "Do not invent missing requirements."
                ),
            ),
        ),
        "Task": (
            "task",
            ProfileStyle(
                label="Task capture",
                dictation_prompt="Turn spoken notes into concise tasks with clear owners, dates, and next actions when mentioned.",
                rewrite_prompt="Rewrite as a crisp action item list without inventing missing details.",
                vocabulary=["TODO", "ETA", "owner", "blocker"],
            ),
        ),
    }
