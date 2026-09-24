from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from collections.abc import Callable


MODIFIER_KEYS = {"ctrl", "alt", "shift", "win"}
CHORD_STALE_SECONDS = 1.25
SLOW_CALLBACK_SECONDS = 0.25
WINDOWS_RESERVED_COMBOS = {
    frozenset({"alt", "space"}),
    frozenset({"alt", "esc"}),
    frozenset({"alt", "tab"}),
    frozenset({"alt", "f4"}),
    frozenset({"ctrl", "alt", "delete"}),
    frozenset({"ctrl", "shift", "esc"}),
    frozenset({"win", "d"}),
    frozenset({"win", "e"}),
    frozenset({"win", "i"}),
    frozenset({"win", "l"}),
    frozenset({"win", "r"}),
    frozenset({"win", "s"}),
    frozenset({"win", "tab"}),
}
logger = logging.getLogger(__name__)


class GlobalHoldHotkeys:
    def __init__(
        self,
        dictate_combo: str,
        polish_combo: str,
        rewrite_combo: str,
        on_start: Callable[[str], None],
        on_stop: Callable[[str], None],
        cancel_combo: str = "",
        asynchronous_callbacks: bool = False,
        windows_poll_only: bool = False,
    ) -> None:
        self.dictate_combo = parse_combo(dictate_combo)
        self.polish_combo = parse_combo(polish_combo)
        self.rewrite_combo = parse_combo(rewrite_combo)
        self.cancel_combo = parse_combo(cancel_combo)
        self.on_start = on_start
        self.on_stop = on_stop
        self.asynchronous_callbacks = asynchronous_callbacks
        self.windows_poll_only = windows_poll_only
        self._pressed: set[str] = set()
        self._pressed_at: dict[str, float] = {}
        self._active_mode: str | None = None
        self._cancel_active = False
        self._active_started_at = 0.0
        self.last_activation_seconds = 0.0
        self._listener = None
        self._registered_hotkeys = None
        self._event_lock = threading.RLock()
        self._callback_lock = threading.Lock()
        self._callback_generation = 0
        self._callbacks_stopped = False
        self._callback_queue: queue.Queue[tuple[int, str, str, float] | None] = queue.Queue()
        self._callback_thread: threading.Thread | None = None
        self._elevated_toggle_mode: str | None = None
        self._running = threading.Event()

    def run(self) -> None:
        self.start()
        while self._running.is_set():
            time.sleep(0.2)

    def start(self) -> None:
        if self._running.is_set():
            return
        self._resume_callback_dispatch()
        self._running.set()
        if sys.platform == "win32":
            from .windows_hotkeys import WindowsRegisteredHotkeys

            try:
                self._registered_hotkeys = WindowsRegisteredHotkeys(
                    [*self._mode_combos(), ("cancel", self.cancel_combo)],
                    self._on_registered_press,
                    self._on_registered_release,
                    poll_only=self.windows_poll_only,
                )
                self._registered_hotkeys.start()
                logger.info(
                    "Windows shortcuts active through RegisterHotKey; "
                    "no low-level keyboard hook is installed."
                )
            except Exception:
                self._registered_hotkeys = None
                self._running.clear()
                self._invalidate_callback_dispatch()
                raise
            return

        # Keep pynput as the non-Windows compatibility path. On Windows,
        # RegisterHotKey avoids joining the system keyboard-hook chain.
        from pynput import keyboard

        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self) -> None:
        self._running.clear()
        self._invalidate_callback_dispatch()
        registered_hotkeys = self._registered_hotkeys
        self._registered_hotkeys = None
        if registered_hotkeys is not None:
            registered_hotkeys.stop()
        with self._event_lock:
            self._pressed.clear()
            self._pressed_at.clear()
            self._active_mode = None
            self._cancel_active = False
            self._elevated_toggle_mode = None
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        listener.stop()
        if listener is not threading.current_thread():
            try:
                listener.join(timeout=1.0)
            except RuntimeError:
                pass

    def _on_press(self, key) -> None:
        name = normalize_key(key)
        with self._event_lock:
            self._handle_press(name)

    def _on_release(self, key) -> None:
        name = normalize_key(key)
        with self._event_lock:
            self._handle_release(name)

    def elevated_toggle_active(self, mode: str) -> bool:
        with self._event_lock:
            return self._elevated_toggle_mode == mode

    def _on_registered_press(self, mode: str) -> bool:
        elevated_target = _foreground_target_is_elevated()
        now = time.monotonic()
        with self._event_lock:
            if mode == "cancel":
                self._elevated_toggle_mode = None
                self._synthesize_registered_combo(mode, now)
                return False

            if self._elevated_toggle_mode == mode and self._active_mode == mode:
                # Elevated targets can hide key state from an unelevated
                # process. A second shortcut press is the explicit stop signal.
                self._active_started_at = min(self._active_started_at, now - 1.0)
                completion = next(iter(dict(self._mode_combos())[mode] - MODIFIER_KEYS))
                self._handle_release(completion, now=now)
                self._elevated_toggle_mode = None
                return False

            if self._active_mode is not None:
                return False
            self._elevated_toggle_mode = mode if elevated_target else None
            self._synthesize_registered_combo(mode, now)
            return not elevated_target and self._active_mode == mode

    def _on_registered_release(self, mode: str) -> None:
        now = time.monotonic()
        with self._event_lock:
            if self._elevated_toggle_mode == mode:
                return
            combo = dict(self._mode_combos()).get(mode, set())
            completion_keys = combo - MODIFIER_KEYS
            if completion_keys:
                self._handle_release(next(iter(completion_keys)), now=now)

    def _synthesize_registered_combo(self, mode: str, now: float) -> None:
        combos = dict(self._mode_combos())
        combo = self.cancel_combo if mode == "cancel" else combos.get(mode, set())
        if not is_valid_combo(combo):
            return
        self._pressed.clear()
        self._pressed_at.clear()
        for modifier in ("ctrl", "alt", "shift", "win"):
            if modifier in combo:
                self._handle_press(modifier, now=now)
        completion = next(iter(combo - MODIFIER_KEYS))
        self._handle_press(completion, now=now)
        if mode == "cancel":
            self._handle_release(completion, now=now)

    def _handle_press(self, name: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self._active_mode is None:
            self._purge_stale(now)
        if not name:
            return
        self._pressed.add(name)
        self._pressed_at[name] = now

        if self._cancel_combo_is_pressed(name, now):
            self._cancel_active = True
            self._clear_active_combo()
            self._dispatch_callback("start", "cancel")
            return

        if self._cancel_active:
            return

        if self._active_mode is not None:
            return

        for mode, combo in self._mode_combos():
            if (
                name not in MODIFIER_KEYS
                and name in combo
                and combo.issubset(self._pressed)
                and self._combo_is_fresh(combo, now)
            ):
                self._active_mode = mode
                self._active_started_at = now
                self._dispatch_callback("start", mode)
                return

    def _handle_release(self, name: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self._cancel_active and name in self.cancel_combo:
            self._cancel_active = False

        active = self._active_mode
        combos = dict(self._mode_combos())
        active_combo = combos.get(active, set()) if active is not None else set()
        if active is not None and name in active_combo:
            self.last_activation_seconds = max(0.0, now - self._active_started_at)
            self._active_mode = None
            self._pressed.difference_update(active_combo)
            for key in active_combo:
                self._pressed_at.pop(key, None)
            self._dispatch_callback("stop", active)

        if name:
            self._pressed.discard(name)
            self._pressed_at.pop(name, None)

    def _dispatch_callback(self, kind: str, mode: str) -> None:
        if not self.asynchronous_callbacks:
            callback = self.on_start if kind == "start" else self.on_stop
            callback(mode)
            return

        with self._callback_lock:
            if self._callbacks_stopped:
                return
            callback_queue = self._callback_queue
            generation = self._callback_generation
            thread = self._callback_thread
            if thread is None or not thread.is_alive():
                thread = threading.Thread(
                    target=self._run_callback_queue,
                    args=(callback_queue,),
                    name="WinsperHotkeyCallbacks",
                    daemon=True,
                )
                self._callback_thread = thread
                thread.start()
            callback_queue.put((generation, kind, mode, time.perf_counter()))

    def _run_callback_queue(
        self,
        callback_queue: queue.Queue[tuple[int, str, str, float] | None],
    ) -> None:
        while True:
            item = callback_queue.get()
            try:
                if item is None:
                    return
                generation, kind, mode, queued_at = item
                with self._callback_lock:
                    active = (
                        not self._callbacks_stopped
                        and callback_queue is self._callback_queue
                        and generation == self._callback_generation
                    )
                if not active:
                    continue
                callback = self.on_start if kind == "start" else self.on_stop
                try:
                    callback_started_at = time.perf_counter()
                    queue_delay = callback_started_at - queued_at
                    if queue_delay >= SLOW_CALLBACK_SECONDS:
                        logger.warning(
                            "Hotkey %s callback for %s waited %.0f ms for app dispatch.",
                            kind,
                            mode,
                            queue_delay * 1000,
                        )
                    callback(mode)
                    callback_seconds = time.perf_counter() - callback_started_at
                    if callback_seconds >= SLOW_CALLBACK_SECONDS:
                        logger.warning(
                            "Hotkey %s callback for %s took %.0f ms.",
                            kind,
                            mode,
                            callback_seconds * 1000,
                        )
                except Exception:
                    logger.exception("Winsper hotkey %s callback failed for %s.", kind, mode)
            finally:
                callback_queue.task_done()

    def _invalidate_callback_dispatch(self) -> None:
        if not self.asynchronous_callbacks:
            return
        with self._callback_lock:
            if self._callbacks_stopped:
                return
            self._callbacks_stopped = True
            self._callback_generation += 1
            self._callback_queue.put(None)

    def _resume_callback_dispatch(self) -> None:
        if not self.asynchronous_callbacks:
            return
        with self._callback_lock:
            if not self._callbacks_stopped:
                return
            self._callbacks_stopped = False
            self._callback_generation += 1
            self._callback_queue = queue.Queue()
            self._callback_thread = None



    def _mode_combos(self) -> list[tuple[str, set[str]]]:
        combos = [
            ("rewrite", self.rewrite_combo),
            ("polish", self.polish_combo),
            ("dictate", self.dictate_combo),
        ]
        return [(mode, combo) for mode, combo in sorted(combos, key=lambda item: len(item[1]), reverse=True) if is_valid_combo(combo)]

    def _combo_is_fresh(self, combo: set[str], now: float) -> bool:
        pressed_times = [self._pressed_at.get(key) for key in combo]
        if any(value is None for value in pressed_times):
            return False
        oldest = min(value for value in pressed_times if value is not None)
        return now - oldest <= CHORD_STALE_SECONDS

    def _purge_stale(self, now: float) -> None:
        stale = [key for key, pressed_at in self._pressed_at.items() if now - pressed_at > CHORD_STALE_SECONDS]
        for key in stale:
            self._pressed.discard(key)
            self._pressed_at.pop(key, None)

    def _cancel_combo_is_pressed(self, name: str, now: float) -> bool:
        return (
            not self._cancel_active
            and is_valid_combo(self.cancel_combo)
            and name not in MODIFIER_KEYS
            and name in self.cancel_combo
            and self.cancel_combo.issubset(self._pressed)
            and self._combo_is_fresh(self.cancel_combo, now)
        )

    def _clear_active_combo(self) -> None:
        active = self._active_mode
        if active is None:
            return
        combos = dict(self._mode_combos())
        active_combo = combos.get(active, set())
        self._active_mode = None
        # Preserve held modifiers shared with cancel. Dropping Ctrl/Win here
        # makes the next shortcut appear dead until every key is released.
        completion_keys = active_combo - MODIFIER_KEYS
        self._pressed.difference_update(completion_keys)
        for key in completion_keys:
            self._pressed_at.pop(key, None)


def parse_combo(combo: str) -> set[str]:
    parts = {part.strip().lower() for part in combo.replace(" ", "").split("+") if part.strip()}
    aliases = {
        "control": "ctrl",
        "ctl": "ctrl",
        "option": "alt",
        "cmd": "win",
        "windows": "win",
    }
    return {aliases.get(part, part) for part in parts}


def is_valid_combo(combo: set[str]) -> bool:
    return bool(combo and any(key not in MODIFIER_KEYS for key in combo))


def validate_hotkey_bindings(dictate: str, polish: str, cancel: str) -> list[str]:
    from .windows_hotkeys import registered_hotkey_values

    bindings = {
        "Dictate": parse_combo(dictate),
        "Polish": parse_combo(polish),
        "Cancel": parse_combo(cancel),
    }
    errors: list[str] = []
    for label, combo in bindings.items():
        if not is_valid_combo(combo):
            errors.append(f"{label} shortcut needs at least one non-modifier key.")
        elif frozenset(combo) in WINDOWS_RESERVED_COMBOS:
            errors.append(f"{label} shortcut conflicts with a reserved Windows shortcut.")
        elif registered_hotkey_values(combo) is None:
            errors.append(
                f"{label} shortcut needs modifiers and exactly one supported letter, "
                "number, function, navigation, Space, Tab, Enter, or Escape key."
            )

    labels = list(bindings)
    for index, first in enumerate(labels):
        for second in labels[index + 1 :]:
            if bindings[first] and bindings[first] == bindings[second]:
                errors.append(f"{first} and {second} shortcuts must be different.")
    return errors


def normalize_key(key) -> str:
    from pynput import keyboard

    if isinstance(key, keyboard.KeyCode):
        char = key.char or ""
        if len(char) == 1:
            code = ord(char)
            if 1 <= code <= 26:
                return chr(ord("a") + code - 1)
            return char.lower()
        vk = getattr(key, "vk", None)
        if isinstance(vk, int):
            if 0x41 <= vk <= 0x5A:
                return chr(vk).lower()
            if 0x30 <= vk <= 0x39:
                return chr(vk)
        return ""

    mapping = {
        keyboard.Key.ctrl: "ctrl",
        keyboard.Key.ctrl_l: "ctrl",
        keyboard.Key.ctrl_r: "ctrl",
        keyboard.Key.alt: "alt",
        keyboard.Key.alt_l: "alt",
        keyboard.Key.alt_r: "alt",
        keyboard.Key.alt_gr: "alt",
        keyboard.Key.shift: "shift",
        keyboard.Key.shift_l: "shift",
        keyboard.Key.shift_r: "shift",
        keyboard.Key.space: "space",
        keyboard.Key.cmd: "win",
        keyboard.Key.cmd_l: "win",
        keyboard.Key.cmd_r: "win",
        keyboard.Key.esc: "esc",
        keyboard.Key.enter: "enter",
        keyboard.Key.tab: "tab",
        keyboard.Key.backspace: "backspace",
    }
    return mapping.get(key, "")


def _foreground_target_is_elevated() -> bool:
    if sys.platform != "win32":
        return False
    try:
        from .app_context import get_foreground_window_details
        from .paste import _target_is_elevated

        window = get_foreground_window_details()
        return bool(window.hwnd and _target_is_elevated(window.hwnd))
    except Exception:
        # Elevation detection must never break shortcut delivery.
        return False


def run_hotkey_test(dictate_combo: str, polish_combo: str, rewrite_combo: str, cancel_combo: str = "") -> None:
    def on_start(mode: str) -> None:
        print(f"{mode}: start")

    def on_stop(mode: str) -> None:
        print(f"{mode}: stop")

    hotkeys = GlobalHoldHotkeys(
        dictate_combo=dictate_combo,
        polish_combo=polish_combo,
        rewrite_combo=rewrite_combo,
        on_start=on_start,
        on_stop=on_stop,
        cancel_combo=cancel_combo,
    )
    print("Winsper hotkey test is running.")
    print(f"Hold {dictate_combo} to see dictate start/stop.")
    if polish_combo:
        print(f"Hold {polish_combo} to see polish start/stop.")
    else:
        print("Polish hotkey is disabled.")
    if rewrite_combo:
        print(f"Hold {rewrite_combo} to see rewrite start/stop.")
    if cancel_combo:
        print(f"Press {cancel_combo} to see cancel.")
    print("Press Ctrl+C in this terminal to quit.")
    try:
        hotkeys.run()
    except KeyboardInterrupt:
        print("\nStopping hotkey test.")
    finally:
        hotkeys.stop()
