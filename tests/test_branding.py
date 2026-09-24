from voicepilot.brand import BRAND_NAME, window_title
from voicepilot.branding import create_app_icon_image, create_logo_image, create_tray_icon_image
from voicepilot.app_icons import app_icon_path
from voicepilot.settings_style import RECOMMENDED_TEXT_COLOR, RECOMMENDED_TEXT_WEIGHT, settings_stylesheet
from voicepilot.theme import DARK, LIGHT


def test_canonical_brand_name_is_winsper():
    assert BRAND_NAME == "Winsper"
    assert window_title("Settings") == "Winsper Settings"


def test_onboarding_app_marks_are_owned_by_app_package():
    for app_id in ("outlook", "slack", "chatgpt", "vscode", "terminal"):
        path = app_icon_path(app_id)
        assert path is not None and path.is_file()
        assert path.parent.name == "apps"
        assert path.parent.parent.name == "assets"


def test_tray_icon_uses_large_canonical_w_with_safe_inset():
    icon = create_tray_icon_image(64)
    assert icon.size == (64, 64)
    alpha = icon.getchannel("A").point(lambda value: 255 if value > 8 else 0)
    bounds = alpha.getbbox()
    assert bounds is not None
    assert bounds[2] - bounds[0] >= 56
    assert bounds[3] - bounds[1] >= 38
    assert bounds[0] >= 2 and bounds[1] >= 2
    assert bounds[2] <= 62 and bounds[3] <= 62
    assert all(icon.getpixel(point)[3] == 0 for point in ((0, 0), (63, 0), (0, 63), (63, 63)))


def test_taskbar_icon_is_not_stretched_or_clipped():
    icon = create_app_icon_image(32)
    alpha = icon.getchannel("A").point(lambda value: 255 if value > 8 else 0)
    bounds = alpha.getbbox()
    assert bounds is not None
    assert bounds[2] - bounds[0] >= 28
    assert bounds[3] - bounds[1] >= 18
    assert bounds[0] >= 1 and bounds[1] >= 1
    assert bounds[2] <= 31 and bounds[3] <= 31
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    assert 1.35 <= width / height <= 1.65


def test_window_icon_preserves_square_size():
    assert create_logo_image(128).size == (128, 128)


def test_settings_accents_follow_the_logo_palette():
    assert DARK.bg == "#0c0d10"
    assert DARK.sidebar == "#111318"
    assert DARK.accent == LIGHT.accent == "#007fd4"
    assert DARK.accent_2 == LIGHT.accent_2 == "#5b43f2"
    assert DARK.on_accent == LIGHT.on_accent == "#ffffff"
    stylesheet = settings_stylesheet(LIGHT)
    assert LIGHT.accent in stylesheet
    assert LIGHT.accent_2 in stylesheet
    assert "border-radius: 18px" in stylesheet
    assert f"border-left: 3px solid {LIGHT.accent}" in stylesheet


def test_settings_recommendations_keep_the_light_treatment_in_every_theme():
    expected = f"color: {RECOMMENDED_TEXT_COLOR}; font-weight: {RECOMMENDED_TEXT_WEIGHT};"
    assert RECOMMENDED_TEXT_COLOR == LIGHT.accent
    assert expected in settings_stylesheet(LIGHT)
    assert expected in settings_stylesheet(DARK)


def test_ready_labels_use_the_blue_accent_treatment():
    stylesheet = settings_stylesheet(LIGHT)
    assert 'QLabel#HomeSummary[tone="accent"]' in stylesheet
    assert 'QLabel#ModelStateBadge[tone="accent"]' in stylesheet


def test_personalize_selection_hierarchy_is_preserved():
    stylesheet = settings_stylesheet(LIGHT)
    assert "QTabWidget#PersonalizeTabs::pane" in stylesheet
    assert f"border-top: 1px solid {LIGHT.border_soft}" in stylesheet
    assert "QTabWidget#PersonalizeTabs QTabBar::tab:selected" in stylesheet
    assert f"border-bottom-color: {LIGHT.accent}" in stylesheet
    assert "QTabWidget#PersonalizeInnerTabs QTabBar::tab:selected" in stylesheet
    assert f"color: {LIGHT.accent}; background: {LIGHT.surface}" in stylesheet
    assert "QFrame#PersonalizeTabSeparator" in stylesheet
    assert f"background: {LIGHT.border}" in stylesheet
