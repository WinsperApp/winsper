from __future__ import annotations

from pathlib import Path

RECOMMENDED_TEXT_COLOR = "#007fd4"
RECOMMENDED_TEXT_WEIGHT = 650


def settings_stylesheet(p) -> str:
    assets = Path(__file__).resolve().parent / "assets"
    arrow_icon = (assets / f"chevron-down-{p.mode}.svg").as_posix()
    check_icon = (assets / f"check-{p.mode}.svg").as_posix()
    primary_start = p.accent
    primary_end = p.accent_2
    primary_text = "#ffffff"
    primary_bg = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {primary_start}, stop:1 {primary_end})"
    primary_hover = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {primary_end}, stop:1 {primary_start})"
    return f"""
    QMainWindow, QWidget#AppCanvas {{ background: {p.bg}; color: {p.text}; font-family: "Segoe UI"; font-size: 14px; }}
    QDialog#SettingsModal {{ background: {p.surface}; color: {p.text}; }}
    QDialog#SettingsModal QScrollArea#Page,
    QDialog#SettingsModal QScrollArea#Page > QWidget > QWidget#qt_scrollarea_viewport,
    QDialog#SettingsModal QWidget#PageContent {{ background: {p.surface}; border: none; }}
    QWidget {{ color: {p.text}; font-family: "Segoe UI"; selection-background-color: {p.accent}; selection-color: {p.on_accent}; }}
    QWidget:disabled {{ color: {p.subtle}; }}
    QLabel {{ background: transparent; }}

    /* Product shell */
    QFrame#Sidebar {{
        background: {p.sidebar}; border: 1px solid {p.border_soft}; border-radius: 18px;
    }}
    QScrollArea#NavScroll, QScrollArea#NavScroll > QWidget > QWidget#qt_scrollarea_viewport,
    QWidget#NavContainer {{
        background: transparent; border: none;
    }}
    QFrame#ContentPanel {{
        background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 18px;
    }}
    QStackedWidget#PageStack, QScrollArea#Page, QScrollArea#Page > QWidget > QWidget {{
        background: transparent; border: none;
    }}
    QLabel#LogoTile {{ background: transparent; border: none; padding: 0px; }}
    QLabel#BrandLogo {{ background: transparent; border: none; padding: 0px; }}
    QLabel#BrandName {{ color: {p.text}; font-size: 17px; font-weight: 650; padding: 0px; }}

    /* Navigation */
    QPushButton#NavButton {{
        text-align: left; border: none; background: transparent;
        padding: 10px 12px; min-height: 22px; font-size: 13px; font-weight: 500;
        color: {p.muted}; border-radius: 11px; margin: 1px 0px;
    }}
    QPushButton#NavButton:hover {{ background: {p.surface_2}; color: {p.text}; border: none; }}
    QPushButton#NavButton:checked {{
        background: {p.sidebar_active}; color: {p.accent}; font-weight: 600;
        border: 1px solid {p.border_soft}; border-left: 3px solid {p.accent};
        border-radius: 11px; padding-left: 10px;
    }}
    QPushButton#NavButton[group="secondary"] {{ color: {p.muted}; }}
    /* Page content */
    QLabel#PageTitle {{ color: {p.text}; font-size: 26px; font-weight: 600; }}
    QLabel#PageSubtitle {{ color: {p.muted}; font-size: 13px; font-weight: 400; }}
    QLabel#StatNumber {{ color: {p.text}; font-size: 27px; font-weight: 550; background: transparent; border: none; }}
    QLabel#StatLabel {{ color: {p.muted}; font-size: 11px; font-weight: 500; background: transparent; border: none; }}
    QLabel#SectionLabel {{ color: {p.muted}; font-size: 10px; font-weight: 500; letter-spacing: 0.08em; }}
    QLabel#RowTitle {{ color: {p.text}; font-size: 14px; font-weight: 600; }}
    QLabel#Muted {{ color: {p.muted}; font-size: 13px; }}
    QLabel#Tiny {{ color: {p.muted}; font-size: 12px; }}
    QLabel#CardTitle {{ color: {p.text}; font-size: 16px; font-weight: 600; }}
    QLabel#Badge {{ color: {primary_text}; background: {primary_bg}; border-radius: 9px; padding: 5px 11px; font-size: 11px; font-weight: 600; }}
    QLabel#HomeSummary {{ color: {p.text}; font-size: 24px; font-weight: 650; }}
    QLabel#HomeSummary[tone="good"] {{
        color: {p.success}; font-weight: 600;
    }}
    QLabel#HomeSummary[tone="accent"] {{ color: {p.accent}; font-weight: 600; }}
    QLabel#HomeSummary[tone="warn"] {{ color: {p.amber}; }}
    QLabel#HomeSummary[tone="bad"] {{ color: {p.coral}; }}

    QLabel#StatValue {{ color: {p.text}; font-size: 28px; font-weight: 500; }}

    /* Quiet, consumer-facing About page */
    QFrame#AboutHeader {{ background: transparent; border: none; }}
    QLabel#AboutHeading {{
        color: {p.text}; background: transparent; border: none;
        font-size: 26px; font-weight: 650;
    }}
    QLabel#AboutTagline {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 13px; font-weight: 400;
    }}
    QLabel#AboutUpdateStatus {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 11px; font-weight: 600;
    }}
    QFrame#AboutIdentity {{
        background: {p.surface_2}; border: 1px solid {p.border_soft};
        border-radius: 16px;
    }}
    QFrame#AboutLogoTile {{
        background: transparent; border: none;
    }}
    QLabel#AboutLogo {{
        background: transparent; border: none;
    }}
    QLabel#AboutProductName {{ color: {p.text}; font-size: 21px; font-weight: 650; }}
    QLabel#AboutMeta {{ color: {p.muted}; font-size: 12px; }}
    QWidget#AboutWaveform {{ background: transparent; border: none; }}
    QLabel#AboutMeta[tone="good"] {{
        color: {p.success}; font-weight: 600;
    }}
    QLabel#AboutMeta[tone="bad"] {{ color: {p.coral}; }}
    QLabel#LocalBadge {{
        color: {p.muted}; background: {p.surface}; border: 1px solid {p.border_soft};
        border-radius: 9px; padding: 5px 10px; font-size: 10px;
        font-weight: 600;
    }}
    QLabel#MicrophoneRouteStatus {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 11px; font-weight: 500;
    }}
    QLabel#MicrophoneRouteStatus[tone="bad"] {{ color: {p.coral}; font-weight: 600; }}
    QFrame#HistoryPrivacyBadge {{
        background: transparent; border: 1px solid {p.border_soft}; border-radius: 10px;
    }}
    QLabel#HistoryPrivacyIcon {{
        background: transparent; border: none; padding: 0;
    }}
    QLabel#HistoryPrivacyText {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 11px; font-weight: 600; padding: 0;
    }}
    QLabel#HistoryCount {{
        color: {p.text}; background: transparent; border: none;
        font-size: 12px; font-weight: 600;
    }}
    QPushButton#HistoryExportButton {{
        background: transparent; color: {p.muted}; border: 1px solid {p.border_soft};
        border-radius: 10px; padding: 8px 13px; font-weight: 600;
    }}
    QPushButton#HistoryExportButton:hover {{
        color: {p.text}; background: {p.surface_2}; border-color: {p.border};
    }}
    QPushButton#HistoryClearButton {{
        background: transparent; color: {p.muted}; border: 1px solid transparent;
        border-radius: 10px; padding: 8px 11px; font-weight: 600;
    }}
    QPushButton#HistoryClearButton:hover {{
        color: {p.text}; background: {p.surface_2}; border-color: {p.border_soft};
    }}
    QPushButton#HistoryLoadMoreButton {{
        background: transparent; color: {p.muted}; border: 1px solid {p.border_soft};
        border-radius: 10px; padding: 8px 16px; margin: 14px 0 10px 0;
        font-size: 11px; font-weight: 600;
    }}
    QPushButton#HistoryLoadMoreButton:hover {{
        color: {p.text}; background: {p.surface}; border-color: {p.border};
    }}
    QPushButton#HistoryLoadMoreButton:focus {{ border-color: {p.accent}; }}
    QFrame#HistoryListSurface {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 14px;
    }}
    QFrame#HistoryDateHeader {{
        background: transparent; border: none;
    }}
    QLabel#HistoryDateLabel {{
        color: {p.text}; background: transparent; border: none;
        font-size: 12px; font-weight: 650; padding: 0;
    }}
    QFrame#HistoryDateDivider {{
        background: {p.border_soft}; border: none;
    }}
    QFrame#HistoryGroup {{
        background: transparent; border: none;
    }}
    QFrame#HistoryRow {{
        background: transparent; border: none; border-bottom: 1px solid {p.border_soft};
    }}
    QFrame#HistoryRow:hover {{ background: {p.surface_3}; }}
    QFrame#HistoryRow[last="true"] {{ border-bottom: none; }}
    QLabel#HistoryTranscript {{
        color: {p.text}; background: transparent; border: none;
        font-size: 13px; font-weight: 400;
    }}
    QLabel#HistoryMeta {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 11px; font-weight: 400;
    }}
    QPushButton#HistoryDetailsButton, QPushButton#HistoryCopyButton, QPushButton#HistoryDeleteButton {{
        background: transparent; border: 1px solid transparent; border-radius: 9px; padding: 0;
    }}
    QPushButton#HistoryDetailsButton:hover, QPushButton#HistoryCopyButton:hover {{
        background: {p.surface}; border-color: {p.border_soft};
    }}
    QPushButton#HistoryDeleteButton:hover {{
        background: {p.surface}; border-color: {p.border_soft};
    }}
    QPushButton#HistoryDetailsButton:focus, QPushButton#HistoryCopyButton:focus, QPushButton#HistoryDeleteButton:focus {{
        border-color: {p.accent};
    }}
    QDialog#HistoryDetailsDialog, QDialog#HistoryCorrectionDialog {{
        background: {p.surface}; color: {p.text};
    }}
    QLabel#HistoryDetailsTitle {{
        color: {p.text}; font-size: 19px; font-weight: 650;
    }}
    QLabel#HistoryDetailsMeta {{
        color: {p.muted}; font-size: 12px; font-weight: 400;
    }}
    QLabel#HistoryDetailsSectionLabel {{
        color: {p.text}; font-size: 12px; font-weight: 650;
    }}
    QTextEdit#HistoryDetailsOutput, QTextEdit#HistoryDetailsOriginal {{
        background: {p.surface_2}; color: {p.text}; border: 1px solid {p.border_soft};
        border-radius: 12px; padding: 12px; selection-background-color: {p.accent};
    }}
    QTextEdit#HistoryDetailsOutput:focus {{ border-color: {p.accent}; }}
    QFrame#HistoryDetailsTechnical {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 10px;
    }}
    QToolButton#HistoryDetailsToggle {{
        background: transparent; color: {p.muted}; border: none; padding: 2px 0;
        font-size: 11px; font-weight: 600;
    }}
    QToolButton#HistoryDetailsToggle:hover {{ color: {p.text}; }}
    QToolButton#HistoryDetailsToggle:focus {{ color: {p.accent}; }}
    QLabel#HistoryDetailsTechnicalText {{
        color: {p.muted}; background: transparent; border: none; font-size: 11px;
    }}
    QPushButton#HistoryDetailsClose, QPushButton#HistoryDetailsSecondary {{
        background: transparent; color: {p.muted}; border: 1px solid {p.border_soft};
        border-radius: 10px; padding: 8px 12px; font-weight: 600;
    }}
    QPushButton#HistoryDetailsClose:hover, QPushButton#HistoryDetailsSecondary:hover {{
        color: {p.text}; background: {p.surface_2}; border-color: {p.border};
    }}
    QFrame#HistoryEmptyPanel {{
        background: transparent; border: none;
    }}
    QLabel#HistoryEmptyIcon {{
        background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 12px;
    }}
    QLabel#HistoryEmptyTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 14px; font-weight: 600;
    }}
    QLabel#HistoryEmptyDetail {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 12px; font-weight: 400;
    }}
    QDialog#SettingsConfirmDialog {{
        background: {p.surface}; color: {p.text};
    }}
    QFrame#SettingsConfirmIconTile {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 12px;
    }}
    QLabel#SettingsConfirmTitle {{
        color: {p.text}; font-size: 17px; font-weight: 650;
    }}
    QLabel#SettingsConfirmMessage {{
        color: {p.muted}; font-size: 12px; font-weight: 400;
    }}
    QDialog#SettingsUpdateDialog {{ background: transparent; }}
    QFrame#SettingsUpdateDialogShell {{
        background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 22px;
    }}
    QFrame#SettingsUpdateDragHeader {{
        background: transparent; border: none;
    }}
    QLabel#SettingsUpdateHeaderLogo {{
        background: transparent; border: none; padding: 0;
    }}
    QLabel#SettingsUpdateHeaderTitle {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 13px; font-weight: 650;
    }}
    QPushButton#SettingsUpdateClose {{
        color: {p.muted}; background: {p.surface_2}; border: 1px solid transparent;
        border-radius: 11px; padding: 0; min-width: 32px; max-width: 32px;
        min-height: 32px; max-height: 32px; font-size: 25px; font-weight: 350;
    }}
    QPushButton#SettingsUpdateClose:hover,
    QPushButton#SettingsUpdateClose:hover:focus {{
        color: #ffffff; background: {p.coral}; border-color: {p.coral};
    }}
    QPushButton#SettingsUpdateClose:pressed {{
        color: #ffffff; background: {p.coral}; border-color: {p.coral};
    }}
    QPushButton#SettingsUpdateClose:focus {{
        color: {p.muted}; background: {p.surface_2}; border-color: transparent;
    }}
    QLabel#SettingsUpdateHeroIcon {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 22px;
    }}
    QLabel#SettingsUpdateTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 21px; font-weight: 650;
    }}
    QLabel#SettingsUpdateVersion {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 13px; font-weight: 400;
    }}
    QLabel#SettingsUpdateVersionAccent {{
        color: {p.text}; background: transparent; border: none;
        font-size: 13px; font-weight: 650;
    }}
    QFrame#SettingsUpdateChanges {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 15px;
    }}
    QFrame#SettingsUpdateChangeRow {{ background: transparent; border: none; }}
    QLabel#SettingsUpdateChangeTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 13px; font-weight: 650;
    }}
    QLabel#SettingsUpdateChangeDetail {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 12px; font-weight: 400;
    }}
    QFrame#SettingsUpdateDivider {{ background: {p.border_soft}; border: none; }}
    QPushButton#SettingsUpdateLater {{
        color: {p.muted}; background: {p.surface_2}; border: 1px solid {p.border_soft};
        border-radius: 22px; padding: 0 20px; min-height: 44px; max-height: 44px;
        font-size: 13px; font-weight: 600;
    }}
    QPushButton#SettingsUpdateLater:hover {{
        color: {p.text}; background: {p.surface_3}; border-color: {p.border};
        border-radius: 22px;
    }}
    QPushButton#SettingsUpdateLater:pressed {{
        color: {p.text}; background: {p.surface}; border-color: {p.border};
        border-radius: 22px;
    }}
    QPushButton#SettingsUpdateDownload {{
        color: {primary_text}; background: {primary_bg}; border: none;
        border-radius: 22px; padding: 0 20px; min-height: 46px; max-height: 46px;
        font-size: 13px; font-weight: 650;
    }}
    QPushButton#SettingsUpdateDownload:hover {{
        color: {primary_text}; background: {primary_hover}; border: none;
        border-radius: 22px;
    }}
    QPushButton#SettingsUpdateDownload:pressed {{
        color: {primary_text}; background: {primary_bg}; border: none;
        border-radius: 22px;
    }}
    QPushButton#SettingsUpdateLater:focus,
    QPushButton#SettingsUpdateDownload:focus {{
        border: 2px solid {p.accent}; border-radius: 22px;
    }}
    QLabel#SettingsUpdateFooterIcon {{
        background: transparent; border: none; padding: 0;
    }}
    QLabel#SettingsUpdateFooter {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 11px; font-weight: 500;
    }}
    QPushButton#SettingsConfirmCancel {{
        background: transparent; color: {p.muted}; border: 1px solid {p.border_soft};
        border-radius: 11px; padding: 9px 16px; min-width: 76px; font-weight: 600;
    }}
    QPushButton#SettingsConfirmCancel:hover {{
        color: {p.text}; background: {p.surface_2}; border-color: {p.border};
    }}
    QPushButton#SettingsConfirmAccept {{
        background: transparent; color: {p.text}; border: 1px solid {p.border_soft};
        border-radius: 11px; padding: 9px 16px; min-width: 76px; font-weight: 600;
    }}
    QPushButton#SettingsConfirmAccept:hover {{
        background: transparent; color: {p.text}; border-color: {p.border};
    }}
    QPushButton#SettingsConfirmAccept:focus {{
        background: transparent; border-color: {p.accent};
    }}
    QFrame#AboutSupportHub {{
        background: transparent; border: none;
    }}
    QLabel#AboutSupportIcon {{
        background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 18px;
    }}
    QLabel#AboutSupportTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 18px; font-weight: 650;
    }}
    QLabel#AboutSupportDetail {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 13px; font-weight: 400;
    }}
    QPushButton#AboutSecondaryButton {{
        color: {p.text}; background: {p.surface}; border: 1px solid {p.border_soft};
        border-radius: 22px; min-height: 42px; max-height: 42px;
        padding: 0px 18px; font-size: 13px; font-weight: 600;
    }}
    QPushButton#AboutSecondaryButton:hover {{
        color: {p.text}; background: {p.sidebar_active}; border-color: {p.border};
    }}
    QPushButton#AboutSecondaryButton:focus {{ border: 2px solid {p.accent}; }}
    QFrame#AboutLinks {{ background: transparent; border: none; }}
    QPushButton#AboutLinkButton {{
        background: transparent; color: {p.muted}; border: 1px solid transparent;
        border-radius: 10px; padding: 8px 10px; min-height: 18px; font-size: 12px; font-weight: 600;
    }}
    QPushButton#AboutLinkButton:hover {{ background: {p.surface_2}; color: {p.text}; border-color: transparent; }}
    QPushButton#AboutLinkButton:focus {{ border-color: {p.accent}; }}

    QPushButton#PrimaryButton {{
        color: {primary_text}; background: {primary_bg}; border: none; border-radius: 22px;
        min-height: 44px; max-height: 44px; padding: 0px 18px;
        font-size: 14px; font-weight: 650;
    }}
    QPushButton#PrimaryButton:hover {{
        background: {primary_hover}; color: {primary_text};
    }}
    QPushButton#PrimaryButton:focus {{
        border: 2px solid {p.accent};
    }}
    QPushButton#PrimaryButton:disabled {{
        background: {p.surface_2}; color: {p.subtle}; border: 1px solid {p.border_soft};
    }}
    QPushButton#ModelDownloadButton {{
        color: {primary_text}; background: {primary_bg}; border: none; border-radius: 18px;
        min-height: 36px; max-height: 36px; padding: 0px 14px;
        font-size: 13px; font-weight: 650;
    }}
    QPushButton#ModelDownloadButton:hover {{
        background: {primary_hover}; color: {primary_text};
    }}
    QPushButton#ModelDownloadButton:focus {{ border: 2px solid {p.accent}; }}
    QPushButton#ModelDownloadButton:disabled {{
        background: {p.surface_2}; color: {p.subtle}; border: 1px solid {p.border_soft};
    }}

    QPushButton#LinkButton {{
        background: transparent; color: {p.muted}; border: 1px solid transparent;
        border-radius: 9px; padding: 7px 9px; min-height: 16px; font-size: 12px;
    }}
    QPushButton#LinkButton:hover {{ background: {p.surface_2}; color: {p.text}; border-color: transparent; }}
    QPushButton#RowActionButton {{
        background: transparent; color: {p.muted}; border: 1px solid transparent;
        border-radius: 9px; padding: 7px 9px; min-height: 18px; font-size: 12px;
    }}
    QPushButton#RowActionButton:hover {{ background: {p.surface_2}; color: {p.text}; border-color: transparent; }}
    QPushButton#RowActionButton:focus {{ border-color: {p.accent}; }}
    QPushButton#QualityAdvancedButton {{
        background: transparent; color: {p.muted}; border: 1px solid transparent;
        border-radius: 9px; padding: 7px 10px; min-width: 70px; min-height: 18px;
        font-size: 12px;
    }}
    QPushButton#QualityAdvancedButton:hover {{
        background: {p.surface_2}; color: {p.text}; border-color: transparent;
    }}
    QPushButton#QualityAdvancedButton:focus {{ border-color: {p.accent}; }}
    /* ── Cards / Frames ── */
    QFrame#Card {{
        background: transparent; border: none;
    }}
    QFrame#SettingsSectionPanel {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 16px;
    }}
    QFrame#HomeHero, QFrame#StatsStrip, QFrame#CheckStrip, QFrame#StatusTile {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 18px;
    }}
    QFrame#WinsperControl {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 15px;
    }}
    QFrame#WinsperStateDot {{
        background: {p.subtle}; border: none; border-radius: 5px;
    }}
    QFrame#WinsperStateDot[tone="active"] {{ background: {p.success}; }}
    QFrame#WinsperStateDot[tone="paused"] {{ background: {p.amber}; }}
    QFrame#WinsperStateDot[tone="offline"] {{ background: {p.coral}; }}
    QLabel#WinsperStateTitle {{
        color: {p.text}; font-size: 14px; font-weight: 650; border: none;
    }}
    QLabel#WinsperStateDetail {{
        color: {p.muted}; font-size: 12px; font-weight: 400; border: none;
    }}
    QPushButton#WinsperStateButton {{
        color: {p.text}; background: {p.surface}; border: 1px solid {p.border_soft};
        border-radius: 11px; padding: 8px 14px; min-height: 20px; min-width: 74px;
        font-size: 12px; font-weight: 600;
    }}
    QPushButton#WinsperStateButton:hover {{
        color: {p.text}; background: {p.surface_3}; border-color: {p.border};
    }}
    QPushButton#WinsperStateButton[action="resume"] {{
        color: {primary_text}; background: {primary_bg}; border: none;
    }}
    QPushButton#WinsperStateButton[action="resume"]:hover {{
        color: {primary_text}; background: {primary_hover}; border: none;
    }}
    QPushButton#WinsperStateButton:disabled {{
        color: {p.subtle}; background: {p.surface}; border-color: {p.border_soft};
    }}
    QFrame#GeneralSettingsList {{
        background: transparent; border: none;
    }}
    QFrame#PrivacyTrustPanel {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 15px;
    }}
    QLabel#PrivacyTrustIcon {{
        background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 11px;
        padding: 0;
    }}
    QLabel#PrivacyTrustTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 15px; font-weight: 650;
    }}
    QLabel#PrivacyTrustDetail {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 12px; font-weight: 400;
    }}
    QFrame#PrivacySettingsList {{
        background: transparent; border: none;
    }}
    QFrame#DictationPanel {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 16px;
    }}
    QLabel#DictationPanelTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 15px; font-weight: 650;
    }}
    QTabWidget#PersonalizeTabs::pane {{
        background: transparent; border: none; border-top: 1px solid {p.border_soft}; top: -1px;
    }}
    QTabWidget#PersonalizeTabs QTabBar::tab {{
        background: transparent; color: {p.muted}; border: none;
        border-bottom: 2px solid transparent; border-radius: 0px;
        padding: 10px 4px 9px 4px; margin: 0 24px 8px 0;
        font-size: 13px; font-weight: 600;
    }}
    QTabWidget#PersonalizeTabs QTabBar::tab:hover {{
        color: {p.text}; background: transparent;
    }}
    QTabWidget#PersonalizeTabs QTabBar::tab:selected {{
        color: {p.accent}; background: transparent;
        border-bottom-color: {p.accent};
    }}
    QWidget#PersonalizeEmbeddedPage {{
        background: transparent; border: none;
    }}
    QFrame#PersonalizeSectionIntro {{
        background: transparent; border: none;
    }}
    QLabel#PersonalizeSectionTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 15px; font-weight: 650;
    }}
    QLabel#PersonalizeSectionDetail {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 12px; font-weight: 400;
    }}
    QLabel#PersonalizeListHeading {{
        color: {p.text}; background: transparent; border: none;
        font-size: 13px; font-weight: 650;
    }}
    QLabel#PersonalizeFieldLabel {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 11px; font-weight: 550;
    }}
    QLabel#PersonalizeDirection {{
        color: {p.muted}; background: transparent; border: none;
        padding-bottom: 11px; font-size: 18px; font-weight: 500;
    }}
    QFrame#PersonalizeComposer {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 15px;
    }}
    QLabel#PersonalizeComposerTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 14px; font-weight: 650;
    }}
    QFrame#PersonalizeListRow {{
        background: {p.surface_2}; border: 1px solid transparent; border-radius: 13px;
    }}
    QFrame#PersonalizeListRow:hover {{
        background: {p.surface_3}; border-color: {p.border_soft};
    }}
    QLabel#PersonalizeRowMark {{
        color: {p.muted}; background: {p.surface};
        border: 1px solid {p.border_soft}; border-radius: 9px;
        font-size: 11px; font-weight: 600;
    }}
    QFrame#PersonalizeEmptyState {{
        background: {p.surface_2}; border: 1px dashed {p.border_soft}; border-radius: 14px;
    }}
    QTabWidget#PersonalizeInnerTabs::pane {{
        background: transparent; border: none; top: -1px;
    }}
    QTabWidget#PersonalizeInnerTabs QTabBar::tab {{
        background: transparent; color: {p.muted};
        border: 1px solid transparent; border-radius: 11px;
        padding: 9px 18px; margin-right: 24px;
        font-size: 12px; font-weight: 600;
    }}
    QTabWidget#PersonalizeInnerTabs QTabBar::tab:hover {{
        color: {p.text}; background: {p.surface_2};
    }}
    QTabWidget#PersonalizeInnerTabs QTabBar::tab:selected {{
        color: {p.accent}; background: {p.surface};
        border-color: {p.border_soft};
    }}
    QFrame#PersonalizeTabSeparator {{
        background: {p.border}; border: none;
        min-width: 1px; max-width: 1px; min-height: 18px; max-height: 18px;
    }}
    QFrame#QualitySelector {{
        background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 12px;
    }}
    QPushButton#QualityOption {{
        color: {p.muted}; background: transparent; border: 1px solid transparent;
        border-radius: 9px; padding: 9px 16px; min-height: 22px;
        font-size: 12px; font-weight: 600;
    }}
    QPushButton#QualityOption:hover {{
        color: {p.text}; background: {p.surface_2}; border-color: transparent;
    }}
    QPushButton#QualityOption:checked {{
        color: {p.text}; background: {p.surface_3}; border: 1px solid {p.border};
    }}
    QPushButton#QualityOption:focus {{
        border-color: {p.accent};
    }}
    QPushButton#QualityOption[unavailable="true"],
    QPushButton#QualityOption[unavailable="true"]:hover,
    QPushButton#QualityOption[unavailable="true"]:checked {{
        color: {p.subtle}; background: transparent; border-color: transparent;
    }}
    QPushButton#PolishQualityOption {{
        color: {p.muted}; background: transparent; border: 1px solid transparent;
        border-radius: 9px; padding: 10px 16px; min-height: 24px;
        font-size: 12px; font-weight: 600;
    }}
    QPushButton#PolishQualityOption:hover {{
        color: {p.text}; background: {p.surface_2}; border-color: transparent;
    }}
    QPushButton#PolishQualityOption:checked {{
        color: {p.text}; background: {p.surface_3}; border: 1px solid {p.border};
    }}
    QPushButton#PolishQualityOption:focus {{ border-color: {p.accent}; }}
    QFrame#ProviderIntro, QFrame#NvidiaAccelerationRow, QFrame#CommandSafeguardsPanel {{ background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 16px; }}
    QFrame#WinsperProviderConnection, QFrame#OllamaProviderConnection, QFrame#OllamaProviderSettings {{ background: transparent; border: none; }}
    QLabel#ProviderTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 14px; font-weight: 650;
    }}
    QPushButton#ProviderOption {{
        color: {p.muted}; background: transparent; border: 1px solid transparent;
        border-radius: 9px; padding: 10px 16px; min-height: 24px;
        font-size: 12px; font-weight: 600;
    }}
    QPushButton#ProviderOption:hover {{
        color: {p.text}; background: {p.surface_2}; border-color: transparent;
    }}
    QPushButton#ProviderOption:checked {{
        color: {p.text}; background: {p.surface_3}; border: 1px solid {p.border};
    }}
    QPushButton#AdvancedToggle {{
        color: {p.muted}; background: transparent; border: none;
        border-radius: 8px; padding: 10px 2px; text-align: left;
        font-size: 11px; font-weight: 600;
    }}
    QPushButton#AdvancedToggle:hover {{
        color: {p.text}; background: transparent;
    }}
    QPushButton#AdvancedToggle:focus {{
        color: {p.text}; border: 1px solid {p.accent};
    }}
    QLabel#QualitySummary {{
        color: {p.muted}; background: transparent; border: none; font-size: 12px;
    }}
    QLabel#QualitySummary[recommended="true"] {{
        color: {RECOMMENDED_TEXT_COLOR}; font-weight: {RECOMMENDED_TEXT_WEIGHT};
    }}
    QFrame#DictationShortcutPanel {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 16px;
    }}
    QFrame#Composer {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 18px;
    }}
    QFrame#ListCard {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 16px;
    }}
    QFrame#ListCard:hover {{
        border-color: {p.border};
        background: {p.surface_3};
    }}
    QLabel#ListTitle {{ color: {p.text}; font-size: 14px; font-weight: 600; }}
    QLabel#ListMeta {{ color: {p.muted}; font-size: 12px; }}
    QFrame#EmptyStatePanel {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 16px;
    }}
    QLabel#EmptyStateMark {{ color: {p.accent}; font-size: 18px; border: none; background: transparent; }}
    QLabel#EmptyStateTitle {{ color: {p.text}; font-size: 14px; font-weight: 600; border: none; background: transparent; }}
    QLabel#EmptyStateDetail {{ color: {p.muted}; font-size: 12px; border: none; background: transparent; }}
    QLabel#InlineNotice {{
        color: {p.muted}; background: {p.surface_2}; border: 1px solid {p.border_soft};
        border-radius: 12px; padding: 12px 14px; font-size: 13px;
    }}
    QLabel#InlineNotice[tone="bad"] {{ color: {p.coral}; border-color: {p.coral}; }}
    QLabel#InlineNotice[tone="warn"] {{ color: {p.amber}; border-color: {p.amber}; }}

    /* ── Status panel labels ── */
    QLabel#StatusPanel {{ color: {p.text}; background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 10px; padding: 10px 12px; font-weight: 500; }}
    QLabel#StatusPanel[tone="accent"] {{ color: {p.accent}; border-color: {p.border_soft}; font-weight: 600; }}
    QLabel#StatusPanel[tone="good"] {{
        color: {p.success}; border-color: {p.border_soft}; font-weight: 600;
    }}
    QLabel#StatusPanel[tone="warn"] {{ color: {p.amber}; border-color: {p.amber}; }}
    QLabel#StatusPanel[tone="bad"] {{ color: {p.coral}; border-color: {p.coral}; }}
    QLabel#StatusPanel[tone="neutral"] {{ color: {p.text}; border-color: {p.border_soft}; }}
    QFrame#ModelCurrentPanel {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 17px;
    }}
    QFrame#ModelPanel,
    QFrame#ModelStoragePanel,
    QFrame#HardwareAccelerationPanel {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 16px;
    }}
    QLabel#ModelEyebrow {{
        color: {p.muted}; font-size: 10px; font-weight: 650; letter-spacing: 0.09em;
    }}
    QLabel#ModelCurrentTitle {{ color: {p.text}; font-size: 17px; font-weight: 650; }}
    QLabel#ModelStateBadge {{
        color: {p.muted}; background: {p.surface}; border: 1px solid {p.border_soft};
        border-radius: 10px; padding: 6px 11px; font-size: 11px; font-weight: 650;
    }}
    QLabel#ModelStateBadge[tone="accent"] {{ color: {p.accent}; font-weight: 600; }}
    QLabel#ModelStateBadge[tone="good"] {{
        color: {p.success}; font-weight: 600;
    }}
    QLabel#ModelStateBadge[tone="warn"] {{ color: {p.amber}; }}
    QLabel#ModelRecommendation {{
        color: {RECOMMENDED_TEXT_COLOR}; background: transparent; border: none;
        padding: 2px 0; font-size: 11px; font-weight: {RECOMMENDED_TEXT_WEIGHT};
    }}
    QLabel#ModelGuidance {{
        color: {p.muted}; background: transparent; border: none;
        padding: 0 0 4px 0; font-size: 12px;
    }}
    QFrame#ModelSummary {{
        color: {p.text}; background: {p.surface}; border: 1px solid {p.border_soft};
        border-radius: 12px;
    }}
    QLabel#ModelSummaryText {{
        color: {p.text}; background: transparent; border: none; font-weight: 500;
    }}
    QLabel#HardwareAccelerationStatus {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 12px;
    }}
    QLabel#HardwareAccelerationStatus[tone="accent"] {{ color: {p.accent}; font-size: 11px; font-weight: 600; }}
    QLabel#HardwareAccelerationStatus[tone="good"] {{
        color: {p.success}; font-size: 11px; font-weight: 600;
    }}
    QLabel#HardwareAccelerationStatus[tone="warn"] {{ color: {p.amber}; }}
    QPushButton#HardwareAccelerationButton {{
        color: {p.text}; background: {p.surface}; border: 1px solid {p.border_soft};
        border-radius: 11px; min-height: 32px; padding: 5px 13px;
        font-size: 11px; font-weight: 600;
    }}
    QPushButton#HardwareAccelerationButton:hover {{
        background: {p.surface_3}; border-color: {p.border};
    }}
    QPushButton#HardwareAccelerationButton:pressed {{
        background: {p.surface_2}; border-color: {p.accent};
    }}
    QPushButton#HardwareAccelerationButton:disabled {{
        color: {p.subtle}; background: transparent; border-color: {p.border_soft};
    }}

    QFrame#ModelDownloadFeedback {{
        background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 12px;
    }}
    QLabel#ModelDownloadStatus {{
        color: {p.text}; background: transparent; border: none;
        font-size: 12px; font-weight: 650;
    }}
    QLabel#ModelDownloadStatus[tone="accent"] {{ color: {p.accent}; font-weight: 600; }}
    QLabel#ModelDownloadStatus[tone="good"] {{
        color: {p.success}; font-weight: 600;
    }}
    QLabel#ModelDownloadStatus[tone="bad"] {{ color: {p.coral}; }}
    QLabel#ModelDownloadValue {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 11px; font-weight: 650;
    }}
    QLabel#ModelDownloadValue[tone="accent"] {{ color: {p.accent}; }}
    QLabel#ModelDownloadMeta {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 11px;
    }}
    QProgressBar#ModelDownloadProgress {{
        background: {p.surface_3}; border: none; border-radius: 3px;
        min-height: 6px; max-height: 6px; text-align: center;
    }}
    QProgressBar#ModelDownloadProgress::chunk {{
        background: {primary_bg}; border: none; border-radius: 3px;
    }}
    QPushButton#DownloadControlButton {{
        color: {p.text}; background: transparent; border: 1px solid {p.border_soft};
        border-radius: 9px; min-height: 18px; padding: 5px 12px;
        font-size: 11px; font-weight: 600;
    }}
    QPushButton#DownloadControlButton:hover {{
        color: {p.text}; background: {p.surface_2}; border-color: {p.border};
    }}
    QPushButton#DownloadControlButton:disabled {{
        color: {p.subtle}; background: transparent; border-color: {p.border_soft};
    }}
    QFrame#ModelStorageField {{
        background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 14px;
    }}
    QLabel#ModelStorageIcon,
    QLabel#ModelStoragePath,
    QLabel#ModelStorageBadge {{
        background: transparent; border: none;
    }}
    QLabel#ModelStoragePath {{
        color: {p.text}; font-size: 13px;
    }}
    QLabel#ModelStorageBadge {{
        color: {p.muted}; font-size: 10px; font-weight: 650; letter-spacing: 0.06em;
    }}
    QPushButton#StorageBrowseButton,
    QPushButton#StorageDefaultButton {{
        color: {p.text}; background: {p.surface}; border: 1px solid {p.border_soft};
        border-radius: 14px; min-height: 38px; padding: 6px 16px;
        font-size: 12px; font-weight: 600;
    }}
    QPushButton#StorageBrowseButton:hover,
    QPushButton#StorageDefaultButton:hover {{
        background: {p.surface_3}; border-color: {p.border};
    }}
    QPushButton#StorageBrowseButton:pressed,
    QPushButton#StorageDefaultButton:pressed {{
        background: {p.surface_2}; border-color: {p.accent};
    }}
    QPushButton#StorageBrowseButton:disabled,
    QPushButton#StorageDefaultButton:disabled {{
        color: {p.subtle}; background: {p.surface_2}; border-color: {p.border_soft};
    }}
    QLabel#HealthState {{ color: {p.text}; background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 8px; padding: 7px 10px; font-weight: 600; }}
    QLabel#HealthState[tone="accent"] {{ color: {p.accent}; border-color: {p.border_soft}; font-weight: 600; }}
    QLabel#HealthState[tone="good"] {{
        color: {p.success}; border-color: {p.success}; font-weight: 600;
    }}
    QLabel#HealthState[tone="warn"] {{ color: {p.amber}; border-color: {p.amber}; }}
    QLabel#HealthState[tone="bad"] {{ color: {p.coral}; border-color: {p.coral}; }}
    QLabel#HealthState[tone="neutral"] {{ color: {p.muted}; }}
    QFrame#ModePanel {{
        background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 13px;
    }}
    QFrame#PolishStatusCard {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 18px;
    }}
    QLabel#PolishStatusTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 15px; font-weight: 650;
    }}
    QFrame#PolishModePanel {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 16px;
    }}
    QLabel#PolishModeEyebrow {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
    }}
    QLabel#PolishModeTitle {{
        color: {p.text}; background: transparent; border: none;
        font-size: 14px; font-weight: 650;
    }}
    QLabel#PolishModeDetail {{
        color: {p.muted}; background: transparent; border: none;
        font-size: 12px;
    }}
    QFrame#PolishAppAwareness {{ background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 14px; }}
    QLabel#PolishAppTitle {{ color: {p.text}; background: transparent; border: none; font-size: 13px; font-weight: 650; }}
    QLabel#PolishAppDetail {{ color: {p.muted}; background: transparent; border: none; font-size: 11px; }}
    QLabel#PolishAppMark {{ background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 8px; }}
    QFrame#PolishControlsCard {{
        background: {p.surface_2}; border: 1px solid {p.border_soft}; border-radius: 18px;
    }}
    QLabel#ShortcutSummary {{
        color: {p.text}; background: {p.surface}; border: 1px solid {p.border_soft};
        border-radius: 12px; padding: 12px 14px;
        font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px;
    }}
    /* ── Status bar at window bottom ── */
    QFrame#StatusBar {{ background: {p.sidebar}; border-top: 1px solid {p.border_soft}; }}
    QLabel#StatusBarText {{ color: {p.muted}; font-size: 11px; }}
    QLabel#StatusBarAccent {{ color: {p.accent}; font-size: 11px; }}

    /* ── Hotkey chip ── */
    QLabel#KeyChip {{
        color: {p.text}; background: {p.surface_2};
        border: 1px solid {p.border}; border-radius: 6px;
        padding: 3px 9px; font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 11px; font-weight: 500;
    }}
    QLabel#KeyChipMuted {{
        color: {p.muted}; background: {p.surface_2};
        border: 1px solid {p.border_soft}; border-radius: 6px;
        padding: 3px 9px; font-size: 11px;
    }}
    QLabel#KeyPlus {{ color: {p.muted}; font-size: 11px; padding: 0 3px; }}

    /* ── Segmented pill control ── */
    QPushButton#SegmentLeft {{
        border-radius: 0px; border-top-left-radius: 7px; border-bottom-left-radius: 7px;
        background: {p.surface_2}; color: {p.muted}; border: 1px solid {p.border_soft};
        padding: 5px 14px; font-size: 12px; font-weight: 400;
    }}
    QPushButton#SegmentLeft:checked {{
        background: {p.accent}; color: {p.on_accent}; border-color: {p.accent}; font-weight: 500;
    }}
    QPushButton#SegmentRight {{
        border-radius: 0px; border-top-right-radius: 7px; border-bottom-right-radius: 7px;
        background: {p.surface_2}; color: {p.muted}; border: 1px solid {p.border_soft};
        border-left: none; padding: 5px 14px; font-size: 12px; font-weight: 400;
    }}
    QPushButton#SegmentRight:checked {{
        background: {p.accent}; color: {p.on_accent}; border-color: {p.accent}; font-weight: 500;
    }}
    QPushButton#SegmentMid {{
        border-radius: 0px; background: {p.surface_2}; color: {p.muted};
        border: 1px solid {p.border_soft}; border-left: none;
        padding: 5px 14px; font-size: 12px; font-weight: 400;
    }}
    QPushButton#SegmentMid:checked {{
        background: {p.accent}; color: {p.on_accent}; border-color: {p.accent}; font-weight: 500;
    }}

    /* ── Buttons ── */
    QPushButton {{
        background: {p.surface}; color: {p.text}; border: 1px solid {p.border};
        border-radius: 12px; padding: 10px 16px; min-height: 20px; font-weight: 600;
    }}
    QPushButton:hover {{ background: {p.surface_3}; border-color: {p.accent}; }}
    QPushButton:pressed {{ background: {p.surface_3}; }}
    QPushButton:focus {{ border: 1px solid {p.accent}; }}
    QPushButton:disabled {{ background: {p.surface_2}; color: {p.subtle}; border-color: {p.border_soft}; }}
    QPushButton#ChoiceButton {{
        background: {p.surface}; color: {p.muted}; border: 1px solid {p.border_soft};
        border-radius: 11px; padding: 9px 15px;
    }}
    QPushButton#ChoiceButton:hover {{ color: {p.text}; border-color: {p.border}; }}
    QPushButton#ChoiceButton:checked {{
        color: {p.text}; background: {p.sidebar_active}; border: 1px solid {p.accent};
    }}
    QPushButton#IconButton {{
        background: transparent; color: {p.muted}; border: none; border-radius: 10px;
        padding: 7px 10px; min-width: 28px;
    }}
    QPushButton#IconButton:hover {{ color: {p.text}; background: {p.surface_3}; border: none; }}
    QPushButton#DangerButton {{
        background: transparent; color: {p.coral}; border: 1px solid {p.border_soft}; border-radius: 10px;
    }}
    QPushButton#DangerButton:hover {{ background: {p.surface_3}; border-color: {p.coral}; }}
    QPushButton#ShortcutRecorder {{
        background: {p.surface}; color: {p.text}; border: 1px solid {p.border};
        border-radius: 12px; padding: 10px 16px; font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 12px; font-weight: 600;
    }}
    QPushButton#ShortcutRecorder:hover {{ border-color: {p.accent}; background: {p.surface_3}; }}
    QPushButton#ShortcutRecorder[recording="true"] {{
        color: {p.accent}; border: 2px solid {p.accent}; background: {p.surface_3};
    }}
    QLabel#ShortcutHint {{ color: {p.muted}; font-size: 12px; font-weight: 500; }}
    QLabel#ShortcutHint[recording="true"] {{ color: {p.accent}; font-weight: 600; }}
    QLabel#ShortcutKeycap {{
        color: {p.text}; background: {p.surface_3}; border: 1px solid {p.border};
        border-bottom: 2px solid {p.border}; border-radius: 5px;
        padding: 2px 7px; font-size: 11px; font-weight: 600;
    }}
    QLabel#ShortcutSeparator {{ color: {p.subtle}; font-size: 11px; font-weight: 600; }}

    /* ── Auto-save indicator ── */
    QFrame#SaveIndicator {{
        background: {p.surface}; border: 1px solid {p.border_soft}; border-radius: 11px;
    }}
    QFrame#SaveIndicator[tone="bad"] {{ border-color: {p.coral}; }}
    QLabel#SaveIndicatorIcon {{ background: transparent; border: none; }}
    QLabel#SaveIndicatorText {{
        color: {p.text}; background: transparent; border: none;
        font-size: 12px; font-weight: 600;
    }}
    QFrame#SaveIndicator[tone="bad"] QLabel#SaveIndicatorText {{ color: {p.coral}; }}
    QPushButton#ToastActionButton {{
        color: {p.accent}; background: transparent; border: none;
        border-radius: 6px; padding: 2px 4px; min-height: 0px;
        font-size: 12px; font-weight: 700;
    }}
    QFrame#SaveIndicator[tone="bad"] QPushButton#ToastActionButton {{ color: {p.coral}; }}
    QPushButton#ToastActionButton:hover {{ background: {p.surface_3}; }}

    QTabWidget#ModernTabs::pane {{
        border: none; background: transparent; top: -1px;
    }}
    QTabWidget#ModernTabs QTabBar::tab {{
        background: transparent; color: {p.muted}; border: none;
        border-radius: 12px; padding: 10px 18px; margin-right: 6px; font-weight: 600;
    }}
    QTabWidget#ModernTabs QTabBar::tab:hover {{ color: {p.text}; background: {p.surface_2}; }}
    QTabWidget#ModernTabs QTabBar::tab:selected {{
        color: {p.text}; background: {p.sidebar_active}; border: 1px solid {p.border_soft};
    }}

    /* ── Model status chip in sidebar ── */
    QLabel#ModelStatus {{ color: {p.muted}; font-size: 10px; }}
    QLabel#ModelStatusDot {{ color: {p.accent}; font-size: 10px; }}

    /* ── Inputs ── */
    QLineEdit, QComboBox, QTextEdit, QListWidget, QTableWidget {{
        background: {p.surface}; color: {p.text}; border: 1px solid {p.border};
        border-radius: 12px; padding: 10px 12px; font-size: 14px; min-height: 22px;
        selection-background-color: {p.accent}; selection-color: {p.on_accent};
    }}
    QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{ border-color: {p.accent}; }}
    QLineEdit:disabled, QComboBox:disabled, QTextEdit:disabled {{ background: {p.surface_2}; color: {p.subtle}; border-color: {p.border_soft}; }}
    QComboBox::drop-down {{ background: {p.surface_2}; border-left: 1px solid {p.border}; border-top-right-radius: 8px; border-bottom-right-radius: 8px; width: 28px; }}
    QComboBox::down-arrow {{ image: url("{arrow_icon}"); width: 14px; height: 14px; }}
    QComboBox QAbstractItemView {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px; outline: none; selection-background-color: {p.accent}; selection-color: {p.on_accent}; }}
    QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 6px 8px; }}
    QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover {{ background: {p.accent}; color: {p.on_accent}; border-radius: 6px; }}
    QComboBox#AppearanceCombo, QComboBox#SettingsCombo {{
        color: {p.text}; background: {p.surface_2}; border: 1px solid {p.border_soft};
        border-radius: 12px; padding: 8px 38px 8px 14px; min-height: 26px;
        font-size: 13px; font-weight: 500;
    }}
    QComboBox#AppearanceCombo:hover, QComboBox#SettingsCombo:hover {{ background: {p.surface_3}; border-color: {p.border}; }}
    QComboBox#AppearanceCombo:focus, QComboBox#SettingsCombo:focus {{ border-color: {p.accent}; }}
    QComboBox#AppearanceCombo::drop-down, QComboBox#SettingsCombo::drop-down {{
        background: transparent; border: none; width: 34px;
    }}
    QComboBox#AppearanceCombo::down-arrow, QComboBox#SettingsCombo::down-arrow {{
        image: url("{arrow_icon}"); width: 13px; height: 13px;
    }}
    QAbstractItemView {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border}; outline: none; selection-background-color: {p.accent}; selection-color: {p.on_accent}; alternate-background-color: {p.surface_2}; }}
    QAbstractItemView::item {{ color: {p.text}; background: transparent; padding: 6px; }}
    QAbstractItemView::item:selected, QTableWidget::item:selected, QListWidget::item:selected {{ background: {p.accent}; color: {p.on_accent}; }}
    QAbstractItemView::item:hover {{ background: {p.surface_2}; color: {p.text}; }}
    QWidget#SettingsComboPopup {{
        background: transparent; border: none;
    }}
    QListView#SettingsComboPopupList {{
        background: {p.surface_2}; color: {p.text}; border: 1px solid {p.border_soft};
        border-radius: 12px; padding: 0px; outline: none;
        selection-background-color: transparent; selection-color: {p.text};
    }}
    QListView#SettingsComboPopupList::item,
    QListView#SettingsComboPopupList::item:selected,
    QListView#SettingsComboPopupList::item:hover {{
        background: transparent; color: {p.text}; border: none; padding: 0px;
    }}
    QTableWidget {{ gridline-color: {p.border_soft}; }}
    QTableCornerButton::section {{ background: {p.surface_2}; border: none; }}
    QHeaderView::section {{ background: {p.surface_2}; color: {p.muted}; border: none; padding: 9px; font-weight: 500; font-size: 11px; }}

    /* ── Scrollbars ── */
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0px; }}
    QScrollBar::handle:vertical {{ background: {p.border_soft}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0px; }}
    QScrollBar::handle:horizontal {{ background: {p.border_soft}; border-radius: 4px; min-width: 24px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollArea > QWidget {{ background: transparent; }}
    QWidget#PageContent {{ background: transparent; }}


    /* ── Menus / Tooltips ── */
    QMenu {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border_soft}; border-radius: 8px; padding: 6px; }}
    QMenu::item {{ background: transparent; padding: 7px 24px 7px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {p.accent}; color: {p.on_accent}; }}
    QMenu::separator {{ height: 1px; background: {p.border_soft}; margin: 6px 4px; }}
    QToolTip {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border_soft}; border-radius: 6px; padding: 6px; }}

    /* ── Checkboxes ── */
    QCheckBox {{ color: {p.text}; spacing: 8px; font-size: 13px; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {p.border}; background: {p.surface}; }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
    QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; image: url("{check_icon}"); }}
    QCheckBox::indicator:disabled {{ background: {p.surface_2}; border-color: {p.border_soft}; }}

    /* ── Slider ── */
    QSlider::groove:horizontal {{ height: 4px; background: {p.surface_3}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {p.accent}; border: none; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
    QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
    """
