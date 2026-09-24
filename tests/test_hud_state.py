from inspect import signature

from voicepilot.hud_core import HudMessage
from voicepilot.hud_icons import HUD_ICON_SCALE, HUD_ICON_SCALES, draw_icon
from voicepilot.hud_layout import hud_hidden_y_offset, hud_window_origin
from voicepilot.action_state import ActionDetails, ActionEvent, ActionPhase, ActionStage
from voicepilot.hud_events import message_for_action_event
from voicepilot.hud_state import (
    clean_hud_text,
    display_title,
    format_elapsed,
    is_listening_message,
    is_timed_message,
    should_restart_animation,
    should_hide_compact_hud,
    should_show_status_pill,
    should_use_compact_hud,
    split_subtitle,
    status_label_for_kind,
)


def test_hud_positions_anchor_to_the_requested_primary_screen_edge():
    geometry = {
        "available_x": 100,
        "available_y": 50,
        "available_width": 1000,
        "available_height": 700,
        "hud_width": 336,
        "hud_height": 80,
    }

    assert hud_window_origin("center", **geometry) == (432, 628)
    assert hud_window_origin("left", **geometry) == (142, 628)
    assert hud_window_origin("right", **geometry) == (722, 628)
    assert hud_window_origin("top", **geometry) == (432, 92)
    assert hud_window_origin("unknown", **geometry) == (432, 628)
    assert hud_hidden_y_offset("top") == -18
    assert hud_hidden_y_offset("center") == 18


def test_hud_icons_are_slightly_reduced_inside_the_existing_pill():
    assert "large" not in signature(draw_icon).parameters
    assert HUD_ICON_SCALE == 0.90
    assert HUD_ICON_SCALES["record"] == 0.90
    assert all(HUD_ICON_SCALES[kind] < 0.90 for kind in HUD_ICON_SCALES if kind != "record")


def test_hud_titles_and_status_labels_are_human_readable():
    assert display_title(HudMessage("Inserted", "", "success")) == "Done"
    assert display_title(HudMessage("Live instruction", "", "rewrite")) == "Instruction"
    assert status_label_for_kind("process") == "Working"
    assert status_label_for_kind("preparing") == "Preparing"
    assert status_label_for_kind("warning") == "Note"
    assert should_show_status_pill(HudMessage("Too short", "", "warning"))
    assert not should_show_status_pill(HudMessage("Listening", "", "record"))


def test_hud_listening_and_timer_classification():
    listening = HudMessage("Listening", "General — release to insert", "record")
    selected_polish = HudMessage("Say your instruction", "Selected text — release to transform", "rewrite")
    polishing = HudMessage("Polishing text", "Improving clarity", "rewrite")
    preparing = HudMessage("Preparing Winsper", "Getting things ready", "preparing")
    ready = HudMessage("Ready", "Hold the hotkey to speak", "idle")

    assert is_listening_message(listening)
    assert is_listening_message(selected_polish)
    assert is_timed_message(listening)
    assert is_timed_message(polishing)
    assert not is_timed_message(ready)
    assert format_elapsed(61.9) == "1:01"
    assert should_use_compact_hud(listening, "compact")
    assert should_use_compact_hud(polishing, "compact")
    assert not should_use_compact_hud(listening, "standard")
    assert not should_hide_compact_hud(listening, "compact")
    assert not should_hide_compact_hud(selected_polish, "compact")
    assert not should_hide_compact_hud(preparing, "compact")
    assert should_hide_compact_hud(polishing, "compact")
    assert should_hide_compact_hud(ready, "compact")
    assert not should_hide_compact_hud(polishing, "standard")


def test_hud_transcript_split_and_animation_restart_are_deterministic():
    message = HudMessage("Live transcript", "A long enough transcript preview", "process")
    assert split_subtitle(message) == ("Live preview", "A long enough transcript preview")
    assert clean_hud_text("Ramble uses Local models for local AI cleanup") == "Dictation uses Models for cleaning up"

    previous = HudMessage("Listening", "General — release to insert", "record")
    current = HudMessage("Done", "14 words", "success")
    assert should_restart_animation(previous, current, False)
    assert should_restart_animation(current, current, True)


def test_action_events_drive_listening_hud_after_stream_activation():
    preparing = ActionEvent(1, "dictate", ActionPhase.CAPTURING, ActionStage.PREPARING_CAPTURE, ActionDetails())
    assert message_for_action_event(preparing) is None

    listening = ActionEvent(
        1,
        "dictate",
        ActionPhase.CAPTURING,
        ActionStage.CAPTURING,
        ActionDetails(context_label="Outlook"),
    )
    message = message_for_action_event(listening)
    assert message == HudMessage("Listening", "Outlook — release to insert", "record")


def test_hud_drops_stale_action_events():
    from voicepilot.hud_core import ConsoleHUD

    hud = ConsoleHUD()
    hud.show = lambda *_args: None
    current = ActionEvent(2, "dictate", ActionPhase.CAPTURING, ActionStage.CAPTURING, ActionDetails())
    stale = ActionEvent(1, "dictate", ActionPhase.IDLE, ActionStage.CANCELLED, ActionDetails())
    hud.show_action_event(current)
    hud.show_action_event(stale)
    assert hud._latest_action_id == 2


def test_hud_rejects_late_detail_after_action_terminal_event():
    from voicepilot.hud_core import ConsoleHUD

    shown = []
    hud = ConsoleHUD()
    hud.show = lambda *args: shown.append(args)
    listening = ActionEvent(4, "dictate", ActionPhase.CAPTURING, ActionStage.CAPTURING, ActionDetails())
    completed = ActionEvent(4, "dictate", ActionPhase.IDLE, ActionStage.COMPLETED, ActionDetails(outcome="completed"))

    hud.show_action_event(listening)
    hud.show_action_event(completed)
    hud.show_action_message(4, "Late transcript", "must not appear", "process")
    hud.show_action_message(5, "Listening", "new action", "record")

    assert not any(item[0] == "Late transcript" for item in shown)
    assert shown[-1][0] == "Listening"


def test_failed_action_event_has_specific_truthful_microcopy():
    failed = ActionEvent(
        7,
        "dictate",
        ActionPhase.IDLE,
        ActionStage.FAILED,
        ActionDetails(outcome="too_short"),
    )
    assert message_for_action_event(failed) == HudMessage(
        "Too short",
        "Hold a little longer and try again",
        "warning",
    )


def test_muted_microphone_has_specific_recovery_hud():
    failed = ActionEvent(
        8,
        "dictate",
        ActionPhase.IDLE,
        ActionStage.FAILED,
        ActionDetails(outcome="microphone_muted"),
    )
    assert message_for_action_event(failed) == HudMessage(
        "Microphone muted",
        "Unmute it in Windows and try again",
        "warning",
    )


def test_polish_icon_is_static_and_reduced_motion_freezes_indicator():
    from PySide6.QtGui import QImage, QPainter

    from voicepilot.hud_icons import draw_icon
    from voicepilot.hud_render import draw_top_indicator
    from voicepilot.theme import DARK

    def render_icon(phase: int) -> bytes:
        image = QImage(80, 80, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        draw_icon(painter, "rewrite", DARK.accent_2, phase)
        painter.end()
        return bytes(image.constBits())

    def render_indicator(phase: int, *, reduced: bool, listening: bool = False) -> bytes:
        image = QImage(180, 24, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        draw_top_indicator(painter, DARK, "rewrite", phase, reduced, listening=listening)
        painter.end()
        return bytes(image.constBits())

    assert render_icon(0) == render_icon(24)
    assert render_indicator(0, reduced=True) == render_indicator(24, reduced=True)
    assert render_indicator(0, reduced=False) != render_indicator(24, reduced=False)
    assert render_indicator(0, reduced=False, listening=True) != render_indicator(24, reduced=False, listening=True)


def test_standard_hud_restores_original_geometry_without_text_overlap():
    from voicepilot.hud_core import HUD_HEIGHT, HUD_WIDTH
    from voicepilot.hud_layout import accessory_rect, subtitle_rect, title_rect

    assert (HUD_WIDTH, HUD_HEIGHT) == (336, 80)
    timer = accessory_rect(64)
    heading = title_rect(96)
    detail = subtitle_rect(96)

    assert heading.right() < timer.left()
    assert detail.right() < timer.left()
    assert heading.bottom() <= detail.top() + 1


def test_live_wave_keeps_both_tails_low_and_the_centre_prominent():
    from voicepilot.hud_render import wave_bar_metrics

    heights = [wave_bar_metrics(index, 24, phase=8, max_height=22)[0] for index in range(24)]

    assert max(heights[:3] + heights[-3:]) <= 4.0
    assert max(heights[9:15]) >= 19.0
    assert min(heights[11:13]) >= 17.5
    assert max(heights) >= 5 * max(heights[0], heights[-1])


def test_full_and_compact_wave_peaks_use_the_same_travelling_shape():
    from voicepilot.hud_render import wave_bar_metrics

    full_left = [wave_bar_metrics(index, 24, phase=86, max_height=22, travel=True)[0] for index in range(24)]
    full_right = [wave_bar_metrics(index, 24, phase=29, max_height=22, travel=True)[0] for index in range(24)]
    compact_left = [wave_bar_metrics(index, 19, phase=86, max_height=18.5, travel=True)[0] for index in range(19)]
    compact_right = [wave_bar_metrics(index, 19, phase=29, max_height=18.5, travel=True)[0] for index in range(19)]

    assert full_left.index(max(full_left)) <= 7
    assert full_right.index(max(full_right)) >= 16
    assert compact_left.index(max(compact_left)) <= 6
    assert compact_right.index(max(compact_right)) >= 12


def test_standard_hud_renderer_covers_light_dark_and_semantic_states():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from voicepilot.hud_core import HUD_HEIGHT, HUD_WIDTH
    from voicepilot.hud_render import draw_standard_hud
    from voicepilot.theme import DARK, LIGHT

    app = QApplication.instance() or QApplication([])
    messages = (
        HudMessage("Listening", "Firefox — release to insert", "record"),
        HudMessage("Listening for polish", "Outlook — release to polish", "rewrite"),
        HudMessage("Too short", "Hold a little longer and try again", "warning"),
        HudMessage("Microphone error", "Check your mic and try again", "error"),
        HudMessage("Inserted", "18 words", "success"),
    )
    for palette in (LIGHT, DARK):
        for message in messages:
            image = QImage(HUD_WIDTH, HUD_HEIGHT, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)
            draw_standard_hud(painter, message, palette, phase=8, elapsed=1.0, reduced_motion=False)
            painter.end()

            assert image.pixelColor(HUD_WIDTH // 2, HUD_HEIGHT // 2).alpha() > 0
            assert image.pixelColor(12, HUD_HEIGHT // 2).alpha() > 0
    assert app is not None
