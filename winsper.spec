import importlib.metadata
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

from voicepilot import __version__

root = Path(SPECPATH)
version_parts = tuple(int(part) for part in __version__.split("."))
version_quad = (*version_parts, *(0 for _ in range(4 - len(version_parts))))[:4]
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_quad, prodvers=version_quad),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Winsper"),
                        StringStruct("FileDescription", "Winsper for Windows"),
                        StringStruct("FileVersion", __version__),
                        StringStruct("InternalName", "Winsper"),
                        StringStruct("OriginalFilename", "Winsper.exe"),
                        StringStruct("ProductName", "Winsper"),
                        StringStruct("ProductVersion", __version__),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
runtime_assets = [
    "assets/check-dark.svg",
    "assets/check-light.svg",
    "assets/chevron-down-dark.svg",
    "assets/chevron-down-light.svg",
    "assets/winsper-app-icon.png",
    "assets/winsper-icon.png",
    "assets/winsper-logo.png",
]
assets = collect_data_files("voicepilot", includes=runtime_assets)
assets += collect_data_files("faster_whisper", includes=["assets/*"])
for app_mark in ("outlook.svg", "slack.png", "chatgpt.png", "vscode.png", "terminal.png"):
    source = root / "voicepilot" / "assets" / "apps" / app_mark
    if not source.is_file():
        raise RuntimeError(f"Onboarding app mark is missing: {source}")
    assets.append((str(source), str(Path("voicepilot") / "assets" / "apps")))
for legal_notice in ("LICENSE", "THIRD_PARTY_NOTICES.md", "LGPL_SOURCE_OFFER.md"):
    source = root / legal_notice
    if not source.is_file():
        raise RuntimeError(f"Required distribution notice is missing: {source}")
    assets.append((str(source), "."))
pystray_distribution = importlib.metadata.distribution("pystray")
for license_name in ("COPYING", "COPYING.LGPL"):
    license_entry = next(
        (entry for entry in pystray_distribution.files or () if entry.name == license_name),
        None,
    )
    source = pystray_distribution.locate_file(license_entry) if license_entry else None
    if source is None or not Path(source).is_file():
        raise RuntimeError(f"Required LGPL/GPL distribution text is missing: {license_name}")
    assets.append((str(source), "licenses"))
embedded_polish_runtime = root / "build" / "embedded-polish-runtime"
embedded_polish_server = embedded_polish_runtime / "llama-server.exe"
native_audio_dll = root / "build" / "native-audio" / "winsper_audio.dll"
if not embedded_polish_server.is_file():
    raise RuntimeError(
        "Embedded Polish runtime is missing. Run "
        "scripts/prepare_embedded_polish_runtime.py before PyInstaller."
    )
if not native_audio_dll.is_file():
    raise RuntimeError(
        "Native Windows microphone component is missing. Run "
        "scripts/build-native-audio.ps1 before PyInstaller."
    )
for runtime_file in embedded_polish_runtime.rglob("*"):
    if runtime_file.is_file():
        relative_parent = runtime_file.parent.relative_to(embedded_polish_runtime)
        assets.append(
            (
                str(runtime_file),
                str(Path("voicepilot") / "runtime" / "llama" / relative_parent),
            )
        )
hiddenimports = [
    "comtypes",
    "comtypes.client",
    "PySide6.QtSvg",
    "PySide6.QtWidgets",
    "PIL.Image",
    "ctranslate2",
    "faster_whisper",
    "huggingface_hub",
    "numpy",
    "pyautogui",
    "pyperclip",
    "pystray",
    "pywinauto",
    "sounddevice",
    "tokenizers",
    "yaml",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
]
sherpa_datas, sherpa_binaries, sherpa_hiddenimports = collect_all("sherpa_onnx")
hiddenimports += sherpa_hiddenimports

a = Analysis(
    [str(root / "winsper_launcher.py")],
    pathex=[str(root)],
    binaries=sherpa_binaries
    + [(str(native_audio_dll), str(Path("voicepilot") / "runtime" / "audio"))],
    datas=assets + sherpa_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "pytest",
        "ruff",
        "mouseinfo",  # Optional PyAutoGUI utility; not used by Winsper.
        "tkinter",
        "_tkinter",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtVirtualKeyboard",
    ],
    noarchive=False,
)

# PyInstaller promotes dependencies discovered beside the bundled llama-server
# into the root binary collection. The complete runtime is already preserved
# under voicepilot/runtime/llama, so those root-level copies are redundant.
embedded_polish_root = embedded_polish_runtime.resolve()
a.binaries = [
    entry
    for entry in a.binaries
    if not (
        len(Path(entry[0]).parts) == 1
        and Path(entry[1]).resolve().is_relative_to(embedded_polish_root)
        and (embedded_polish_root / entry[0]).is_file()
    )
]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Winsper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "build" / "winsper.ico"),
    version=version_info,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Winsper",
)
