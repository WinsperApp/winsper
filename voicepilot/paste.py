from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass
from pathlib import Path

from .config import PasteConfig
from .delivery import DeliveryStatus, ELEVATED_TARGET_REASON
from .destination import infer_destination
from .paste_windows import (
    clipboard_format_is_safe as _clipboard_format_is_safe,
    configure_clipboard_api as _configure_clipboard_api,
    configure_security_api as _configure_security_api,
    open_clipboard as _open_clipboard,
)
from .selection import SelectionResult, SelectionStatus
from .selection_windows import (
    UiaSelectionProbe,
    probe_uia_selection as _probe_uia_selection_native,
    send_copy_message as _send_copy_message_native,
    send_copy_shortcut as _send_copy_shortcut_native,
    wait_for_clipboard_text as _wait_for_clipboard_text,
)


@dataclass(frozen=True)
class InsertResult:
    sent: bool
    copied: bool
    strategy: str
    reason: str = ""
    verified: bool = False

    @property
    def delivery(self) -> DeliveryStatus:
        if self.strategy == "target_changed":
            return DeliveryStatus.TARGET_CHANGED
        if self.strategy == "target_elevated":
            return DeliveryStatus.TARGET_ELEVATED
        if self.verified:
            return DeliveryStatus.VERIFIED
        if self.sent:
            return DeliveryStatus.SENT
        if self.copied:
            return DeliveryStatus.COPIED
        return DeliveryStatus.BLOCKED if self.strategy == "blocked" else DeliveryStatus.FAILED

    @property
    def inserted(self) -> bool:
        """Compatibility alias. `sent` is the truthful cross-app guarantee."""
        return self.sent


@dataclass(frozen=True)
class ClipboardPayload:
    format_id: int
    data: bytes


class SelectionReadError(RuntimeError):
    """Winsper cannot safely read a selected-text Polish source."""


@dataclass
class ClipboardSnapshot:
    payloads: list[ClipboardPayload]
    sequence_number: int
    complete: bool = True

    @classmethod
    def capture(cls) -> "ClipboardSnapshot":
        if not _is_windows():
            pyperclip, _pyautogui = _clipboard_modules()
            return cls(
                payloads=[ClipboardPayload(13, pyperclip.paste().encode("utf-16-le") + b"\x00\x00")],
                sequence_number=0,
            )

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        _configure_clipboard_api(user32, kernel32)
        _open_clipboard(user32)
        payloads: list[ClipboardPayload] = []
        unsupported: set[int] = set()
        formats: list[int] = []
        try:
            format_id = 0
            while True:
                format_id = int(user32.EnumClipboardFormats(format_id))
                if not format_id:
                    break
                formats.append(format_id)

            for format_id in formats:
                if not _clipboard_format_is_safe(user32, format_id):
                    if format_id < 0xC000 and not (format_id == 2 and ({8, 17} & set(formats))):
                        unsupported.add(format_id)
                    continue
                handle = user32.GetClipboardData(format_id)
                if not handle:
                    continue
                size = int(kernel32.GlobalSize(handle))
                if size <= 0:
                    unsupported.add(format_id)
                    continue
                pointer = kernel32.GlobalLock(handle)
                if not pointer:
                    unsupported.add(format_id)
                    continue
                try:
                    payloads.append(ClipboardPayload(format_id, ctypes.string_at(pointer, size)))
                finally:
                    kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

        return cls(
            payloads=payloads,
            sequence_number=int(user32.GetClipboardSequenceNumber()),
            complete=not unsupported,
        )
    def restore(self) -> None:
        if not _is_windows():
            pyperclip, _pyautogui = _clipboard_modules()
            text = next((item.data for item in self.payloads if item.format_id == 13), b"")
            pyperclip.copy(text.decode("utf-16-le", errors="ignore").rstrip("\x00"))
            return

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        _configure_clipboard_api(user32, kernel32)
        gmem_moveable = 0x0002
        _open_clipboard(user32)
        allocated: list[int] = []
        try:
            if not user32.EmptyClipboard():
                raise OSError("Windows could not clear the clipboard for restoration.")
            for payload in self.payloads:
                size = max(1, len(payload.data))
                handle = kernel32.GlobalAlloc(gmem_moveable, size)
                if not handle:
                    raise MemoryError("Windows could not allocate clipboard memory.")
                pointer = kernel32.GlobalLock(handle)
                if not pointer:
                    kernel32.GlobalFree(handle)
                    raise OSError("Windows could not lock clipboard memory.")
                try:
                    ctypes.memmove(pointer, payload.data, len(payload.data))
                finally:
                    kernel32.GlobalUnlock(handle)
                if not user32.SetClipboardData(payload.format_id, handle):
                    kernel32.GlobalFree(handle)
                    raise OSError(f"Windows could not restore clipboard format {payload.format_id}.")
                allocated.append(handle)
        finally:
            user32.CloseClipboard()
        # Ownership of handles in allocated transfers to Windows after SetClipboardData.


class TextInserter:
    def __init__(self, config: PasteConfig) -> None:
        self.config = config

    def paste_text(
        self,
        text: str,
        *,
        process_name: str = "",
        window_title: str = "",
        window_hwnd: int = 0,
    ) -> InsertResult:
        pyperclip, pyautogui = _clipboard_modules()
        if window_hwnd and _target_is_elevated(window_hwnd):
            if not _target_is_current(window_hwnd):
                pyperclip.copy(text)
                return InsertResult(False, True, "target_changed", "Target app changed before paste.")
            pyperclip.copy(text)
            return InsertResult(False, True, "target_elevated", ELEVATED_TARGET_REASON)
        if not _target_is_current(window_hwnd):
            pyperclip.copy(text)
            return InsertResult(False, True, "target_changed", "Target app changed before paste.")

        snapshot = ClipboardSnapshot.capture() if self.config.restore_clipboard else None
        if snapshot is not None and not snapshot.complete:
            if not _target_is_current(window_hwnd):
                pyperclip.copy(text)
                return InsertResult(False, True, "target_changed", "Target app changed before paste.")
            if _type_unicode(text):
                return InsertResult(True, False, "unicode-input")
            return InsertResult(
                False,
                False,
                "blocked",
                "Winsper could not safely preserve the clipboard or type the result directly.",
            )

        if not _target_is_current(window_hwnd):
            pyperclip.copy(text)
            return InsertResult(False, True, "target_changed", "Target app changed before paste.")

        strategy, keys = _paste_strategy(process_name, window_title)
        pyperclip.copy(text)
        transcript_sequence = _clipboard_sequence_number()
        try:
            time.sleep(self.config.paste_delay_ms / 1000)
            if not _target_is_current(window_hwnd):
                return InsertResult(False, True, "target_changed", "Target app changed before paste.")
            pyautogui.hotkey(*keys)
            if snapshot is not None:
                if not _pump_local_qt_events(self.config.paste_delay_ms / 1000):
                    time.sleep(self.config.paste_delay_ms / 1000)
        except Exception as exc:
            return InsertResult(False, True, "clipboard", f"Automatic paste failed: {exc}")


        restore_mode = self._restore_mode()
        if snapshot is not None and restore_mode == "delayed":
            restore_delay = max(0, self.config.restore_delay_ms) / 1000
            if restore_delay and not _pump_local_qt_events(restore_delay):
                time.sleep(restore_delay)
        if snapshot is not None and restore_mode != "never" and _clipboard_sequence_number() == transcript_sequence:
            try:
                snapshot.restore()
            except Exception as exc:
                return InsertResult(
                    True,
                    True,
                    strategy,
                    f"Text was sent, but the original clipboard could not be restored: {exc}",
                )
        return InsertResult(True, False, strategy)

    def _restore_mode(self) -> str:
        if not self.config.restore_clipboard:
            return "never"
        configured = str(getattr(self.config, "restore_mode", "delayed") or "delayed").strip().lower()
        return configured if configured in {"immediate", "delayed", "never"} else "delayed"

    def copy_text(self, text: str) -> None:
        pyperclip, _pyautogui = _clipboard_modules()
        pyperclip.copy(text)

    def press_key(self, key: str) -> None:
        _pyperclip, pyautogui = _clipboard_modules()
        time.sleep(max(0.04, self.config.paste_delay_ms / 1000))
        pyautogui.press(key, presses=1, interval=0)
        time.sleep(self.config.paste_delay_ms / 1000)

    def insert_below_selection(
        self,
        text: str,
        *,
        process_name: str = "",
        window_title: str = "",
        window_hwnd: int = 0,
        destination_kind: str = "",
    ) -> InsertResult:
        pyperclip, pyautogui = _clipboard_modules()
        if window_hwnd and _target_is_elevated(window_hwnd):
            if not _target_is_current(window_hwnd):
                pyperclip.copy(text)
                return InsertResult(False, True, "target_changed", "Target app changed before paste.")
            pyperclip.copy(text)
            return InsertResult(False, True, "target_elevated", ELEVATED_TARGET_REASON)
        if not _target_is_current(window_hwnd):
            pyperclip.copy(text)
            return InsertResult(False, True, "target_changed", "Target app changed before paste.")
        resolved_kind = destination_kind or infer_destination(process_name, window_title, "", "").kind
        if resolved_kind == "spreadsheet":
            pyperclip.copy(text)
            return InsertResult(
                False,
                True,
                "clipboard",
                "Insert below is not safe in spreadsheets. The result was copied instead.",
            )
        pyautogui.press("right")
        time.sleep(self.config.paste_delay_ms / 1000)
        return self.paste_text(
            f"\n{text}",
            process_name=process_name,
            window_title=window_title,
            window_hwnd=window_hwnd,
        )

    def get_selected_text(self) -> str:
        result = self.read_selection()
        if result.status is not SelectionStatus.CAPTURED and result.status is not SelectionStatus.NO_SELECTION:
            raise SelectionReadError(result.reason)
        return result.text

    def read_selection(self, *, window_hwnd: int = 0) -> SelectionResult:
        """Read selection only when Winsper can legally automate target input."""
        if window_hwnd and _target_is_elevated(window_hwnd):
            return SelectionResult.target_elevated()
        if not _target_is_current(window_hwnd):
            return SelectionResult.target_changed()
        uia = _probe_uia_selection(window_hwnd)
        if uia.supported:
            if uia.text.strip():
                return SelectionResult.captured(uia.text, method="uia")
            return SelectionResult.no_selection(method="uia")
        pyperclip, pyautogui = _clipboard_modules()
        try:
            # Selection capture is an internal read operation. It must always
            # preserve the user's clipboard, independent of paste preferences.
            snapshot = ClipboardSnapshot.capture()
        except Exception as exc:
            return SelectionResult.unavailable(f"Winsper could not preserve the clipboard: {exc}")
        if not snapshot.complete:
            return SelectionResult.unavailable("Winsper could not safely preserve every clipboard format while reading the selection.")
        if not _target_is_current(window_hwnd):
            return SelectionResult.target_changed()
        selection_sequence = 0
        try:
            if not _target_is_current(window_hwnd):
                return SelectionResult.target_changed()
            pyperclip.copy("")
            selection_sequence = _clipboard_sequence_number()
            if not _target_is_current(window_hwnd):
                return SelectionResult.target_changed()

            if _send_copy_message(window_hwnd):
                result = _wait_for_clipboard_text(pyperclip, timeout_seconds=0.18)
                if result and _target_is_current(window_hwnd):
                    selection_sequence = _clipboard_sequence_number()
                    return SelectionResult.captured(result, method="wm_copy")

            if not _target_is_current(window_hwnd):
                return SelectionResult.target_changed()
            if not _send_copy_shortcut(pyautogui):
                return SelectionResult.unavailable(
                    "Windows could not send a clean Copy shortcut to the selected text.",
                    method="send_input",
                )
            result = _wait_for_clipboard_text(
                pyperclip,
                timeout_seconds=max(0.6, self.config.copy_delay_ms / 1000),
            )
            if not _target_is_current(window_hwnd):
                return SelectionResult.target_changed()
            selection_sequence = _clipboard_sequence_number()
            return (
                SelectionResult.captured(result, method="send_input")
                if result.strip()
                else SelectionResult.no_selection(method="send_input")
            )
        except Exception as exc:
            return SelectionResult.unavailable(f"Winsper could not read selected text: {exc}")
        finally:
            if _clipboard_sequence_number() == selection_sequence:
                snapshot.restore()

    def undo_then_paste(self, text: str) -> InsertResult:
        self.undo_last_paste()
        return self.paste_text(text)

    def undo_last_paste(self) -> None:
        _pyperclip, pyautogui = _clipboard_modules()
        pyautogui.hotkey("ctrl", "z")
        time.sleep(self.config.paste_delay_ms / 1000)


def _paste_strategy(process_name: str, window_title: str) -> tuple[str, tuple[str, ...]]:
    process = Path(process_name).name.lower()
    title = window_title.lower()
    if process in {"windowsterminal.exe", "wt.exe"}:
        return "terminal", ("ctrl", "shift", "v")
    if process in {"code.exe", "cursor.exe", "windsurf.exe"} and "terminal" in title:
        return "ide-terminal", ("shift", "insert")
    if any(token in title for token in ("terminal", "powershell", "command prompt")):
        return "terminal", ("ctrl", "shift", "v")
    return "standard", ("ctrl", "v")


def _target_is_elevated(hwnd: int) -> bool:
    if not _is_windows() or not hwnd:
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    _configure_security_api(kernel32, advapi32)
    process_id = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    if not process_id.value:
        return False
    process = kernel32.OpenProcess(0x1000, False, process_id.value)
    if not process:
        # Access Denied (5) typically indicates target process is elevated/protected relative to us
        if kernel32.GetLastError() == 5:
            try:
                current_elevated = _process_is_elevated(kernel32.GetCurrentProcess())
                return not current_elevated
            except Exception:
                return True
        return False
    try:
        target_elevated = _process_is_elevated(process)
        current_elevated = _process_is_elevated(kernel32.GetCurrentProcess())
        return target_elevated and not current_elevated
    finally:
        kernel32.CloseHandle(process)


def _target_is_current(hwnd: int) -> bool:
    """True when an HWND-scoped operation still targets the focused window."""
    if not hwnd or not _is_windows():
        return True
    try:
        return int(ctypes.windll.user32.GetForegroundWindow()) == int(hwnd)
    except Exception:
        return False


def _probe_uia_selection(window_hwnd: int) -> UiaSelectionProbe:
    return _probe_uia_selection_native(window_hwnd, is_windows=_is_windows())


def _send_copy_message(window_hwnd: int) -> bool:
    return _send_copy_message_native(window_hwnd, is_windows=_is_windows())


def _send_copy_shortcut(pyautogui) -> bool:
    return _send_copy_shortcut_native(pyautogui, is_windows=_is_windows())



def _type_unicode(text: str) -> bool:
    if not _is_windows():
        return False
    try:
        import pyautogui

        user32 = ctypes.windll.user32
        keyeventf_keyup = 0x0002
        keyeventf_unicode = 0x0004
        ulong_ptr = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class KeybdInput(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ulong_ptr),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [("ki", KeybdInput)]

        class Input(ctypes.Structure):
            _anonymous_ = ("union",)
            _fields_ = [("type", ctypes.c_ulong), ("union", InputUnion)]

        pending: list[Input] = []

        def flush() -> bool:
            if not pending:
                return True
            array = (Input * len(pending))(*pending)
            sent = int(user32.SendInput(len(array), array, ctypes.sizeof(Input)))
            pending.clear()
            return sent == len(array)

        for character in text:
            if character in {"\n", "\r", "\t"}:
                if not flush():
                    return False
                pyautogui.press("tab" if character == "\t" else "enter")
                continue
            encoded = character.encode("utf-16-le")
            for index in range(0, len(encoded), 2):
                code_unit = int.from_bytes(encoded[index : index + 2], "little")
                pending.append(Input(type=1, ki=KeybdInput(0, code_unit, keyeventf_unicode, 0, 0)))
                pending.append(Input(type=1, ki=KeybdInput(0, code_unit, keyeventf_unicode | keyeventf_keyup, 0, 0)))
        return flush()
    except Exception:
        return False


def _process_is_elevated(process_handle: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    _configure_security_api(kernel32, advapi32)
    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(process_handle, 0x0008, ctypes.byref(token)):
        return False
    try:
        elevated = ctypes.c_ulong()
        returned = ctypes.c_ulong()
        if not advapi32.GetTokenInformation(
            token,
            20,
            ctypes.byref(elevated),
            ctypes.sizeof(elevated),
            ctypes.byref(returned),
        ):
            return False
        return bool(elevated.value)
    finally:
        kernel32.CloseHandle(token)


def _clipboard_sequence_number() -> int:
    if not _is_windows():
        return 0
    return int(ctypes.windll.user32.GetClipboardSequenceNumber())


def _is_windows() -> bool:
    return hasattr(ctypes, "windll")


def _clipboard_modules():
    try:
        import pyautogui
        import pyperclip
    except ImportError as exc:
        raise RuntimeError("Install pyautogui and pyperclip from requirements.txt.") from exc

    pyautogui.PAUSE = 0.02
    return pyperclip, pyautogui


def _pump_local_qt_events(duration_seconds: float) -> bool:
    """Let a Winsper-owned target consume paste before clipboard restoration."""
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False
        deadline = time.monotonic() + max(0.04, duration_seconds)
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        return True
    except ImportError:
        return False
