
from voicepilot.hotkeys import GlobalHoldHotkeys, normalize_key, parse_combo, validate_hotkey_bindings
from voicepilot.windows_hotkeys import (
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_WIN,
    WindowsRegisteredHotkeys,
    combo_is_down,
    registered_hotkey_values,
)
from voicepilot.polish_service import polish_completion_budget, rewrite_completion_budget


def test_completion_budgets_bound_short_outputs_and_scale_for_long_text():
    assert rewrite_completion_budget("stupid", "Replace this with a synonym.") == 192
    assert polish_completion_budget("Um, hello there.") == 128
    assert rewrite_completion_budget("x" * 3000, "Expand this.") == 900
    assert polish_completion_budget("x" * 3000) == 700


def test_parse_combo_aliases():
    assert parse_combo("control + alt + space") == {"ctrl", "alt", "space"}


def test_hotkey_validation_blocks_windows_conflicts_and_duplicates():
    assert validate_hotkey_bindings("alt+space", "ctrl+win+p", "ctrl+win+esc")
    assert validate_hotkey_bindings("ctrl+win+space", "ctrl+win+space", "ctrl+win+esc")
    assert validate_hotkey_bindings("ctrl+a+b", "ctrl+win+p", "ctrl+win+esc")
    assert validate_hotkey_bindings("ctrl+;", "ctrl+win+p", "ctrl+win+esc")
    assert validate_hotkey_bindings("ctrl+win+space", "ctrl+win+p", "ctrl+win+esc") == []


def test_hotkey_requires_non_modifier_completion_key():
    events = []
    hotkeys = GlobalHoldHotkeys(
        "ctrl+alt+space", "ctrl+alt+p", "ctrl+alt+shift+space", events.append, lambda mode: events.append(f"{mode}:stop")
    )
    hotkeys._pressed.add("space")
    hotkeys._pressed_at["space"] = 100.0
    hotkeys._handle_press("ctrl", now=100.1)
    hotkeys._handle_press("alt", now=100.2)
    assert events == []

    hotkeys._pressed.clear()
    hotkeys._pressed_at.clear()
    hotkeys._handle_press("ctrl", now=200.0)
    hotkeys._handle_press("alt", now=200.1)
    hotkeys._handle_press("space", now=200.2)
    assert events == ["dictate"]


def test_hotkey_release_clears_entire_active_combo():
    events = []
    hotkeys = GlobalHoldHotkeys(
        "ctrl+alt+space", "", "", lambda mode: events.append(f"{mode}:start"), lambda mode: events.append(f"{mode}:stop")
    )
    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("alt", now=1.1)
    hotkeys._handle_press("space", now=1.2)
    hotkeys._handle_release("ctrl")
    assert events == ["dictate:start", "dictate:stop"]
    assert "space" not in hotkeys._pressed
    assert "space" not in hotkeys._pressed_at


def test_async_hotkey_measures_physical_tap_while_start_is_slow():
    import threading

    import pytest

    start_entered = threading.Event()
    allow_start_to_finish = threading.Event()
    stop_called = threading.Event()

    def on_start(_mode: str) -> None:
        start_entered.set()
        allow_start_to_finish.wait(timeout=1)

    hotkeys = GlobalHoldHotkeys(
        "ctrl+space",
        "",
        "",
        on_start,
        lambda _mode: stop_called.set(),
        asynchronous_callbacks=True,
    )
    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("space", now=1.2)
    assert start_entered.wait(timeout=1)

    hotkeys._handle_release("space", now=1.3)

    assert hotkeys.last_activation_seconds == pytest.approx(0.1)
    assert not stop_called.is_set()
    allow_start_to_finish.set()
    assert stop_called.wait(timeout=1)


def test_modifier_only_hotkey_is_ignored():
    events = []
    hotkeys = GlobalHoldHotkeys("ctrl+alt", "", "", events.append, events.append)
    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("alt", now=1.1)
    assert events == []


def test_ctrl_modified_letter_normalizes_to_letter():
    from pynput import keyboard

    assert normalize_key(keyboard.KeyCode.from_char("\x10")) == "p"
    assert normalize_key(keyboard.KeyCode.from_vk(0x50)) == "p"


def test_hotkey_ignores_stale_modifiers_after_unlock():
    events = []
    hotkeys = GlobalHoldHotkeys("ctrl+alt+space", "ctrl+alt+p", "ctrl+alt+shift+space", events.append, events.append)
    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("alt", now=1.1)
    hotkeys._handle_press("space", now=65.0)
    assert events == []
    assert hotkeys._pressed == {"space"}


def test_hotkey_ignores_slow_chord():
    events = []
    hotkeys = GlobalHoldHotkeys("ctrl+alt+space", "", "", events.append, events.append)
    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("alt", now=1.2)
    hotkeys._handle_press("space", now=3.0)
    assert events == []


def test_cancel_hotkey_fires_without_stop_event():
    events = []
    hotkeys = GlobalHoldHotkeys(
        "ctrl+alt+space",
        "ctrl+alt+p",
        "",
        lambda mode: events.append(f"{mode}:start"),
        lambda mode: events.append(f"{mode}:stop"),
        cancel_combo="ctrl+alt+esc",
    )
    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("alt", now=1.1)
    hotkeys._handle_press("esc", now=1.2)
    hotkeys._handle_release("esc")
    assert events == ["cancel:start"]


def test_cancel_hotkey_clears_active_mode():
    events = []
    hotkeys = GlobalHoldHotkeys(
        "ctrl+alt+space",
        "",
        "",
        lambda mode: events.append(f"{mode}:start"),
        lambda mode: events.append(f"{mode}:stop"),
        cancel_combo="ctrl+alt+esc",
    )
    hotkeys._handle_press("ctrl", now=1.0)
    hotkeys._handle_press("alt", now=1.1)
    hotkeys._handle_press("space", now=1.2)
    hotkeys._handle_press("esc", now=1.3)
    hotkeys._handle_release("space")
    assert events == ["dictate:start", "cancel:start"]


def test_windows_registered_hotkey_translation_supports_product_shortcuts():
    assert registered_hotkey_values({"ctrl", "space"}) == (MOD_NOREPEAT | MOD_CONTROL, 0x20)
    assert registered_hotkey_values({"ctrl", "win", "esc"}) == (MOD_NOREPEAT | MOD_CONTROL | MOD_WIN, 0x1B)
    assert registered_hotkey_values({"ctrl", "a", "b"}) is None


def test_elevated_registered_hotkey_uses_press_again_to_finish():
    from unittest.mock import patch

    for mode in ("dictate", "polish"):
        events = []
        hotkeys = GlobalHoldHotkeys(
            "ctrl+space",
            "ctrl+alt+p",
            "",
            lambda event_mode: events.append(f"{event_mode}:start"),
            lambda event_mode: events.append(f"{event_mode}:stop"),
            cancel_combo="ctrl+win+esc",
        )

        with patch("voicepilot.hotkeys._foreground_target_is_elevated", return_value=True):
            hotkeys._on_registered_press(mode)
            assert hotkeys.elevated_toggle_active(mode)
            hotkeys._on_registered_press(mode)

        assert events == [f"{mode}:start", f"{mode}:stop"]
        assert not hotkeys.elevated_toggle_active(mode)
        assert hotkeys.last_activation_seconds >= 1.0


def test_registered_hotkey_preserves_normal_hold_and_release():
    from unittest.mock import patch

    events = []
    hotkeys = GlobalHoldHotkeys(
        "ctrl+space",
        "",
        "",
        lambda mode: events.append(f"{mode}:start"),
        lambda mode: events.append(f"{mode}:stop"),
    )

    with patch("voicepilot.hotkeys._foreground_target_is_elevated", return_value=False):
        assert hotkeys._on_registered_press("dictate")
        hotkeys._on_registered_release("dictate")

    assert events == ["dictate:start", "dictate:stop"]
    assert not hotkeys.elevated_toggle_active("dictate")


def test_windows_combo_state_requires_every_shortcut_key():
    state = {0x11: 0x8000, 0x20: 0x8000}

    assert not combo_is_down(set(), lambda _virtual_key: 0x8000)
    assert combo_is_down({"ctrl", "space"}, lambda virtual_key: state.get(virtual_key, 0))
    state[0x20] = 0
    assert not combo_is_down({"ctrl", "space"}, lambda virtual_key: state.get(virtual_key, 0))


def test_windows_registered_hotkey_release_monitor_is_nonblocking():
    import threading

    state = {0x11: 0x8000, 0x20: 0x8000}
    released = threading.Event()
    backend = WindowsRegisteredHotkeys(
        [("dictate", {"ctrl", "space"})],
        lambda _mode: True,
        lambda _mode: released.set(),
        key_state=lambda virtual_key: state.get(virtual_key, 0),
        release_poll_seconds=0.001,
    )
    backend._stopping.clear()

    try:
        backend._start_release_monitor("dictate", {"ctrl", "space"})
        assert not released.wait(0.02)
        state[0x20] = 0
        assert released.wait(1)
    finally:
        backend.stop()


def test_windows_poll_only_probe_preserves_rapid_tap_without_registration():
    import threading
    from unittest.mock import patch

    state = {0x11: 0, 0x20: 0}
    pressed = threading.Event()
    released = threading.Event()
    backend = WindowsRegisteredHotkeys(
        [("dictate", {"ctrl", "space"})],
        lambda _mode: pressed.set() or True,
        lambda _mode: released.set(),
        key_state=lambda virtual_key: state.get(virtual_key, 0),
        release_poll_seconds=0.001,
        poll_only=True,
    )
    with patch("voicepilot.windows_hotkeys.sys.platform", "win32"):
        backend.start()
        try:
            state.update({0x11: 0x8000, 0x20: 0x8000})
            assert pressed.wait(1)
            state[0x20] = 0
            assert released.wait(1)
        finally:
            backend.stop()


def test_windows_runtime_never_starts_pynput_listener():
    from unittest.mock import patch

    instances = []

    class NativeHotkeys:
        def __init__(self, bindings, on_press, on_release, *, poll_only=False):
            self.bindings = bindings
            self.on_press = on_press
            self.on_release = on_release
            self.poll_only = poll_only
            self.started = False
            self.stopped = False
            instances.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    hotkeys = GlobalHoldHotkeys("ctrl+space", "", "", lambda _mode: None, lambda _mode: None)
    with (
        patch("voicepilot.hotkeys.sys.platform", "win32"),
        patch("voicepilot.windows_hotkeys.WindowsRegisteredHotkeys", NativeHotkeys),
    ):
        hotkeys.start()
        assert hotkeys._listener is None
        assert instances[0].started
        hotkeys.stop()

    assert instances[0].stopped


def test_windows_poll_only_tester_does_not_register_duplicate_shortcut():
    from unittest.mock import patch

    instances = []

    class NativeHotkeys:
        def __init__(self, _bindings, _on_press, _on_release, *, poll_only=False):
            self.poll_only = poll_only
            instances.append(self)

        def start(self):
            return None

        def stop(self):
            return None

    hotkeys = GlobalHoldHotkeys(
        "ctrl+space",
        "",
        "",
        lambda _mode: None,
        lambda _mode: None,
        windows_poll_only=True,
    )
    with (
        patch("voicepilot.hotkeys.sys.platform", "win32"),
        patch("voicepilot.windows_hotkeys.WindowsRegisteredHotkeys", NativeHotkeys),
    ):
        hotkeys.start()
        hotkeys.stop()

    assert instances[0].poll_only is True


def test_windows_hotkey_start_surfaces_registration_failure():
    import pytest
    from unittest.mock import patch

    backend = WindowsRegisteredHotkeys(
        [("dictate", {"ctrl", "space"})],
        lambda _mode: True,
        lambda _mode: None,
    )

    def fail_registration():
        backend._start_error = RuntimeError(
            "Windows could not reserve configured shortcut(s): dictate."
        )
        backend._ready.set()

    with (
        patch("voicepilot.windows_hotkeys.sys.platform", "win32"),
        patch.object(backend, "_message_loop", fail_registration),
        pytest.raises(RuntimeError, match="could not reserve.*dictate"),
    ):
        backend.start()


def test_windows_hotkey_start_rejects_unsupported_shortcut():
    import pytest
    from unittest.mock import patch

    backend = WindowsRegisteredHotkeys(
        [("dictate", {"ctrl", "a", "b"})],
        lambda _mode: True,
        lambda _mode: None,
    )

    with (
        patch("voicepilot.windows_hotkeys.sys.platform", "win32"),
        pytest.raises(RuntimeError, match="cannot register.*dictate"),
    ):
        backend.start()


def test_stale_release_monitor_cannot_stop_newer_action():
    import threading

    state = {0x11: 0x8000, 0x12: 0x8000, 0x20: 0x8000, 0x50: 0x8000}
    released_modes = []
    released = threading.Event()
    backend = WindowsRegisteredHotkeys(
        [
            ("dictate", {"ctrl", "space"}),
            ("polish", {"ctrl", "alt", "p"}),
        ],
        lambda _mode: True,
        lambda mode: (released_modes.append(mode), released.set()),
        key_state=lambda virtual_key: state.get(virtual_key, 0),
        release_poll_seconds=0.001,
    )
    backend._stopping.clear()

    try:
        backend._start_release_monitor("dictate", {"ctrl", "space"})
        backend._start_release_monitor("polish", {"ctrl", "alt", "p"})
        state[0x20] = 0
        assert not released.wait(0.02)
        state[0x50] = 0
        assert released.wait(1)
    finally:
        backend.stop()

    assert released_modes == ["polish"]


def test_elevated_registered_cancel_clears_active_toggle():
    from unittest.mock import patch

    events = []
    hotkeys = GlobalHoldHotkeys(
        "ctrl+space",
        "",
        "",
        lambda mode: events.append(f"{mode}:start"),
        lambda mode: events.append(f"{mode}:stop"),
        cancel_combo="ctrl+win+esc",
    )

    with patch("voicepilot.hotkeys._foreground_target_is_elevated", return_value=True):
        hotkeys._on_registered_press("dictate")
        hotkeys._on_registered_press("cancel")

    assert events == ["dictate:start", "cancel:start"]
    assert not hotkeys.elevated_toggle_active("dictate")


def test_elevated_listening_hud_explains_press_again_behavior():
    from voicepilot.lifecycle_capture import CaptureLifecycleMixin

    shown = []

    class Hud:
        def show(self, title, detail, state):
            shown.append((title, detail, state))

    class Hotkeys:
        @staticmethod
        def elevated_toggle_active(mode):
            return mode == "dictate"

    class Harness(CaptureLifecycleMixin):
        hud = Hud()
        hotkeys = Hotkeys()

    Harness()._show_listening_hud("dictate", "Administrator window", 1)

    assert shown == [
        ("Listening", "Administrator window - press the shortcut again to copy", "record"),
    ]


def test_listening_hud_does_not_replay_start_readiness_chime():
    from voicepilot.lifecycle_capture import CaptureLifecycleMixin

    events = []

    class Hud:
        @staticmethod
        def show(title, _detail, _state):
            events.append(("hud", title))

    class Chime:
        @staticmethod
        def play_start_before_capture(action_id):
            events.append(("chime", action_id))

    class Harness(CaptureLifecycleMixin):
        hud = Hud()
        recording_chime = Chime()

    harness = Harness()
    harness._show_listening_hud("dictate", "General", 12)
    harness._show_listening_hud("rewrite", "Selected text", 13)

    assert events == [("hud", "Listening"), ("hud", "Say your instruction")]


def test_elevated_polish_hud_explains_speech_only_behavior():
    from voicepilot.lifecycle_capture import CaptureLifecycleMixin

    shown = []

    class Hud:
        def show(self, title, detail, state):
            shown.append((title, detail, state))

    class Hotkeys:
        @staticmethod
        def elevated_toggle_active(mode):
            return mode == "polish"

    class Harness(CaptureLifecycleMixin):
        hud = Hud()
        hotkeys = Hotkeys()

    Harness()._show_listening_hud("polish", "Administrator window", 1)

    assert shown == [
        ("Listening", "Admin app - speech Polish only - press again to copy", "rewrite"),
    ]
