from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from collections.abc import Callable, Iterable
from ctypes import wintypes


logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIER_FLAGS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}

_MODIFIER_VIRTUAL_KEYS = {
    "alt": (0x12,),
    "ctrl": (0x11,),
    "shift": (0x10,),
    "win": (0x5B, 0x5C),
}

_NAMED_VIRTUAL_KEYS = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "esc": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
}

RELEASE_POLL_SECONDS = 0.008
SLOW_DISPATCH_SECONDS = 0.050


def registered_hotkey_values(combo: set[str]) -> tuple[int, int] | None:
    """Translate a Winsper shortcut into RegisterHotKey flags and a virtual key."""
    completion_keys = combo - set(_MODIFIER_FLAGS)
    if len(completion_keys) != 1:
        return None
    completion = next(iter(completion_keys))
    virtual_key = _virtual_key(completion)
    if virtual_key is None:
        return None
    modifiers = MOD_NOREPEAT
    for modifier in combo & set(_MODIFIER_FLAGS):
        modifiers |= _MODIFIER_FLAGS[modifier]
    return modifiers, virtual_key


def _virtual_key(name: str) -> int | None:
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit():
        number = int(name[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    return _NAMED_VIRTUAL_KEYS.get(name)


def combo_is_down(combo: set[str], key_state: Callable[[int], int]) -> bool:
    """Return whether every physical key in a registered shortcut is down."""
    if not combo:
        return False
    for name in combo:
        virtual_keys = _MODIFIER_VIRTUAL_KEYS.get(name)
        if virtual_keys is None:
            virtual_key = _virtual_key(name)
            if virtual_key is None:
                return False
            virtual_keys = (virtual_key,)
        if not any(key_state(virtual_key) & 0x8000 for virtual_key in virtual_keys):
            return False
    return True


class WindowsRegisteredHotkeys:
    """Receive Windows shortcuts without installing a low-level keyboard hook."""

    def __init__(
        self,
        bindings: Iterable[tuple[str, set[str]]],
        on_press: Callable[[str], bool],
        on_release: Callable[[str], None],
        *,
        key_state: Callable[[int], int] | None = None,
        release_poll_seconds: float = RELEASE_POLL_SECONDS,
        poll_only: bool = False,
        allow_partial: bool = False,
    ) -> None:
        self._bindings = [(mode, set(combo)) for mode, combo in bindings]
        self._on_press = on_press
        self._on_release = on_release
        self._key_state = key_state
        self._release_poll_seconds = max(0.001, float(release_poll_seconds))
        self._poll_only = poll_only
        self._allow_partial = allow_partial
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._registered_modes: set[str] = set()
        self._failed_modes: set[str] = set()
        self._stopping = threading.Event()
        self._release_lock = threading.Lock()
        self._release_generation = 0
        self._release_thread: threading.Thread | None = None
        self._fallback_thread: threading.Thread | None = None
        self._start_error: RuntimeError | None = None

    @property
    def registered_modes(self) -> frozenset[str]:
        return frozenset(self._registered_modes)

    @property
    def failed_modes(self) -> frozenset[str]:
        return frozenset(self._failed_modes)

    def start(self) -> None:
        if sys.platform != "win32" or self._thread is not None or self._fallback_thread is not None:
            return
        self._ready.clear()
        self._stopping.clear()
        self._start_error = None
        self._failed_modes.clear()
        unsupported_modes = [
            mode
            for mode, combo in self._bindings
            if combo and registered_hotkey_values(combo) is None
        ]
        if unsupported_modes:
            names = ", ".join(unsupported_modes)
            raise RuntimeError(
                f"Windows cannot register configured shortcut(s): {names}. "
                "Use modifiers with exactly one supported letter, number, function, "
                "navigation, Space, Tab, Enter, or Escape key."
            )
        if self._poll_only:
            bindings = [(mode, combo) for mode, combo in self._bindings if combo]
            if not bindings:
                self._ready.set()
                return
            self._start_fallback_polling(bindings)
            if not self._ready.wait(timeout=1.0):
                self.stop()
                raise RuntimeError("Windows shortcut test polling timed out.")
            return
        self._thread = threading.Thread(
            target=self._message_loop,
            name="WinsperRegisteredHotkeys",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=1.0):
            self.stop()
            raise RuntimeError("Windows hotkey registration timed out.")
        if self._start_error is not None:
            error = self._start_error
            self.stop()
            raise error

    def stop(self) -> None:
        self._stopping.set()
        with self._release_lock:
            self._release_generation += 1
            release_thread = self._release_thread
            self._release_thread = None
        fallback_thread = self._fallback_thread
        self._fallback_thread = None
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread_id = self._thread_id
            if thread_id:
                ctypes.windll.user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            if thread is not threading.current_thread():
                thread.join(timeout=1.0)
        if release_thread is not None and release_thread is not threading.current_thread():
            release_thread.join(timeout=0.25)
        if fallback_thread is not None and fallback_thread is not threading.current_thread():
            fallback_thread.join(timeout=0.25)

    def _start_release_monitor(self, mode: str, combo: set[str]) -> None:
        with self._release_lock:
            self._release_generation += 1
            generation = self._release_generation
            thread = threading.Thread(
                target=self._monitor_release,
                args=(mode, set(combo), generation),
                name="WinsperHotkeyRelease",
                daemon=True,
            )
            self._release_thread = thread
            thread.start()

    def _monitor_release(self, mode: str, combo: set[str], generation: int) -> None:
        key_state = self._key_state
        if key_state is None:
            key_state = ctypes.windll.user32.GetAsyncKeyState
        while not self._stopping.is_set():
            with self._release_lock:
                if generation != self._release_generation:
                    return
            if not combo_is_down(combo, key_state):
                with self._release_lock:
                    if generation != self._release_generation or self._stopping.is_set():
                        return
                    self._release_thread = None
                try:
                    self._on_release(mode)
                except Exception:
                    logger.exception("Windows shortcut release handling failed for %s.", mode)
                return
            self._stopping.wait(self._release_poll_seconds)

    def _start_fallback_polling(self, bindings: list[tuple[str, set[str]]]) -> None:
        if not bindings:
            return
        thread = threading.Thread(
            target=self._poll_bindings,
            args=([(mode, set(combo)) for mode, combo in bindings],),
            name="WinsperHotkeyFallback",
            daemon=True,
        )
        self._fallback_thread = thread
        thread.start()

    def _poll_bindings(self, bindings: list[tuple[str, set[str]]]) -> None:
        key_state = self._key_state
        if key_state is None:
            key_state = ctypes.windll.user32.GetAsyncKeyState
        was_down = {mode: combo_is_down(combo, key_state) for mode, combo in bindings}
        self._ready.set()
        active_modes: set[str] = set()
        while not self._stopping.is_set():
            for mode, combo in bindings:
                down = combo_is_down(combo, key_state)
                if down and not was_down[mode]:
                    try:
                        if self._on_press(mode):
                            active_modes.add(mode)
                    except Exception:
                        logger.exception("Windows shortcut fallback failed for %s.", mode)
                elif not down and was_down[mode] and mode in active_modes:
                    active_modes.discard(mode)
                    try:
                        self._on_release(mode)
                    except Exception:
                        logger.exception("Windows shortcut fallback release failed for %s.", mode)
                was_down[mode] = down
            self._stopping.wait(self._release_poll_seconds)

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL

        self._thread_id = int(kernel32.GetCurrentThreadId())
        registered_ids: list[int] = []
        id_to_mode: dict[int, str] = {}
        mode_to_combo = dict(self._bindings)
        failed_modes: list[str] = []
        try:
            for hotkey_id, (mode, combo) in enumerate(self._bindings, start=1):
                values = registered_hotkey_values(combo)
                if values is None:
                    if combo:
                        failed_modes.append(mode)
                    continue
                modifiers, virtual_key = values
                if user32.RegisterHotKey(None, hotkey_id, modifiers, virtual_key):
                    registered_ids.append(hotkey_id)
                    id_to_mode[hotkey_id] = mode
                    self._registered_modes.add(mode)
                else:
                    failed_modes.append(mode)
            if failed_modes:
                self._failed_modes.update(failed_modes)
                names = ", ".join(failed_modes)
                if not self._allow_partial:
                    self._start_error = RuntimeError(
                        f"Windows could not reserve configured shortcut(s): {names}. "
                        "Close the conflicting app or choose different shortcuts."
                    )
                    return
                logger.warning("Windows could not reserve configured shortcut(s): %s.", names)
            self._ready.set()

            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message != WM_HOTKEY:
                    continue
                mode = id_to_mode.get(int(message.wParam))
                if mode:
                    try:
                        started_at = time.perf_counter()
                        monitor_release = self._on_press(mode)
                        elapsed_seconds = time.perf_counter() - started_at
                        if elapsed_seconds >= SLOW_DISPATCH_SECONDS:
                            logger.warning(
                                "Windows hotkey dispatch was slow for %s: %.1f ms.",
                                mode,
                                elapsed_seconds * 1000.0,
                            )
                        if monitor_release:
                            self._start_release_monitor(mode, mode_to_combo[mode])
                    except Exception:
                        logger.exception("Windows shortcut handling failed for %s.", mode)
        finally:
            for hotkey_id in registered_ids:
                user32.UnregisterHotKey(None, hotkey_id)
            self._registered_modes.clear()
            self._thread_id = 0
            self._ready.set()
