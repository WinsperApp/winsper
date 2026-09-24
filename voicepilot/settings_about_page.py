from __future__ import annotations

class SettingsAboutPageMixin:
    def _build_about_page(self):
        from PySide6.QtCore import QSize, Qt, QUrl
        from PySide6.QtGui import (
            QBrush,
            QColor,
            QDesktopServices,
            QLinearGradient,
            QPainter,
            QPainterPath,
            QPen,
            QPixmap,
        )
        from PySide6.QtWidgets import (
            QFrame,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QSizePolicy,
            QVBoxLayout,
            QWidget,
        )

        from . import __version__
        from .settings_icons import settings_nav_icon

        page, layout = self._page("", "")
        layout.setSpacing(18)

        header = QFrame()
        header.setObjectName("AboutHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 2)
        header_row.setSpacing(24)
        header_copy = QVBoxLayout()
        header_copy.setSpacing(5)
        heading = QLabel("About")
        heading.setObjectName("AboutHeading")
        tagline = QLabel("Winsper for Windows.")
        tagline.setObjectName("AboutTagline")
        header_copy.addWidget(heading)
        header_copy.addWidget(tagline)
        header_row.addLayout(header_copy, 1)
        layout.addWidget(header)

        class AboutWaveform(QWidget):
            def __init__(wave_self):
                super().__init__()
                wave_self.setObjectName("AboutWaveform")
                wave_self.setMinimumWidth(260)
                wave_self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                wave_self.setAttribute(Qt.WA_TransparentForMouseEvents)

            def paintEvent(wave_self, _event):
                width = float(wave_self.width())
                height = float(wave_self.height())
                if width < 2 or height < 2:
                    return
                painter = QPainter(wave_self)
                painter.setRenderHint(QPainter.Antialiasing)
                gradient = QLinearGradient(0, 0, width, 0)
                cyan = QColor(self.palette.accent)
                violet = QColor(self.palette.accent_2)
                cyan.setAlpha(25)
                violet.setAlpha(42)
                gradient.setColorAt(0.0, cyan)
                gradient.setColorAt(0.55, violet)
                gradient.setColorAt(1.0, cyan)
                for index in range(4):
                    path = QPainterPath()
                    baseline = height * (0.48 + (index - 1.5) * 0.065)
                    amplitude = height * (0.18 - index * 0.018)
                    path.moveTo(0, baseline)
                    path.cubicTo(
                        width * 0.18,
                        baseline - amplitude,
                        width * 0.30,
                        baseline + amplitude,
                        width * 0.48,
                        baseline,
                    )
                    path.cubicTo(
                        width * 0.66,
                        baseline - amplitude,
                        width * 0.80,
                        baseline + amplitude,
                        width,
                        baseline - amplitude * 0.18,
                    )
                    painter.setPen(QPen(QBrush(gradient), 1.0))
                    painter.drawPath(path)

        identity = QFrame()
        identity.setObjectName("AboutIdentity")
        identity.setMinimumHeight(112)
        identity.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        identity_row = QHBoxLayout(identity)
        identity_row.setContentsMargins(8, 10, 8, 10)
        identity_row.setSpacing(18)
        logo_tile = QFrame()
        logo_tile.setObjectName("AboutLogoTile")
        logo_tile.setFixedSize(62, 62)
        logo_tile_layout = QVBoxLayout(logo_tile)
        logo_tile_layout.setContentsMargins(0, 0, 0, 0)
        logo = QLabel()
        logo.setObjectName("AboutLogo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setPixmap(self._logo_pixmap(QPixmap, 48))
        logo_tile_layout.addWidget(logo)
        identity_row.addWidget(logo_tile, 0, Qt.AlignVCenter)
        identity_copy = QVBoxLayout()
        identity_copy.setSpacing(5)
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        product_name = QLabel("Winsper")
        product_name.setObjectName("AboutProductName")
        name_row.addWidget(product_name)
        name_row.addStretch(1)
        product_meta = QLabel(f"Version {__version__}  ·  Windows")
        product_meta.setObjectName("AboutMeta")
        identity_copy.addLayout(name_row)
        identity_copy.addWidget(product_meta)
        identity_row.addLayout(identity_copy)
        identity_row.addWidget(AboutWaveform(), 1)
        update_actions = QVBoxLayout()
        update_actions.setSpacing(6)
        update_actions.setContentsMargins(0, 8, 0, 0)
        update_actions.setAlignment(Qt.AlignHCenter)
        check_button = QPushButton("Check for updates")
        check_button.setObjectName("PrimaryButton")
        check_button.setFixedWidth(210)
        check_button.setCursor(Qt.PointingHandCursor)
        check_button.setAccessibleDescription("Check for a newer Winsper version")
        update_status = QLabel("")
        update_status.setObjectName("AboutUpdateStatus")
        update_status.setAlignment(Qt.AlignCenter)
        update_actions.addWidget(check_button, 0, Qt.AlignHCenter)
        update_actions.addWidget(update_status, 0, Qt.AlignHCenter)
        identity_row.addLayout(update_actions)
        layout.addWidget(identity)
        layout.addStretch(1)

        support_panel = QFrame()
        support_panel.setObjectName("AboutSupportHub")
        support_panel.setMinimumHeight(178)
        support_panel.setMaximumWidth(680)
        support_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        support_row = QVBoxLayout(support_panel)
        support_row.setContentsMargins(20, 8, 20, 10)
        support_row.setSpacing(7)
        support_row.setAlignment(Qt.AlignCenter)
        support_icon = QLabel()
        support_icon.setObjectName("AboutSupportIcon")
        support_icon.setAlignment(Qt.AlignCenter)
        support_icon.setFixedSize(72, 72)
        support_icon.setPixmap(
            settings_nav_icon("support", self.palette.accent, 28).pixmap(QSize(28, 28))
        )
        support_row.addWidget(support_icon, 0, Qt.AlignHCenter)

        support_title = QLabel("Need help with Winsper?")
        support_title.setObjectName("AboutSupportTitle")
        support_title.setAlignment(Qt.AlignCenter)
        support_detail = QLabel("Questions, feedback, or setup trouble—we’re here to help.")
        support_detail.setObjectName("AboutSupportDetail")
        support_detail.setAlignment(Qt.AlignCenter)
        support_detail.setWordWrap(True)
        support_row.addWidget(support_title)
        support_row.addWidget(support_detail)
        help_button = QPushButton("Get help")
        help_button.setObjectName("PrimaryButton")
        help_button.setFixedWidth(440)
        help_button.setCursor(Qt.PointingHandCursor)
        help_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("mailto:help@winsper.app?subject=Winsper%20help"))
        )
        support_row.addSpacing(5)
        support_row.addWidget(help_button, 0, Qt.AlignHCenter)
        layout.addWidget(support_panel, 0, Qt.AlignHCenter)

        links = QFrame()
        links.setObjectName("AboutLinks")
        links_row = QHBoxLayout(links)
        links_row.setContentsMargins(0, 6, 0, 0)
        links_row.setSpacing(2)
        destinations = (
            ("Privacy", "https://winsper.app/privacy/"),
            ("Terms", "https://winsper.app/terms/"),
        )
        links_row.addStretch(1)
        for label, destination in destinations:
            button = QPushButton(label)
            button.setObjectName("AboutLinkButton")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, target=destination: QDesktopServices.openUrl(QUrl(target))
            )
            links_row.addWidget(button)
        links_row.addStretch(1)
        layout.addWidget(links)

        self._bind_about_update_widgets(check_button, update_status)
        return page
