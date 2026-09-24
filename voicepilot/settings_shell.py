from __future__ import annotations


def build_settings_navigation(owner, nav_layout, sidebar_layout) -> None:
    """Build the consumer navigation while keeping SettingsWindow focused."""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget, QWidget

    from .settings_icons import settings_nav_icon

    owner.stack = QStackedWidget()
    owner.stack.setObjectName("PageStack")
    owner.nav_buttons: dict[int, QPushButton] = {}
    page_defs = [
        ("General", "home", owner._build_home_page, "main"),
        ("Dictation", "dictation", owner._build_voice_page, "main"),
        ("Polish", "polish", owner._build_polish_consumer_page, "main"),
        ("Personalize", "personalize", owner._build_personalize_page, "main"),
        ("History", "transcripts", owner._build_transcripts_page, "main"),
        ("Privacy", "privacy", owner._build_privacy_page, "main"),
        ("About", "about", owner._build_about_page, "main"),
        ("Language + Speech", "models", owner._build_models_page, "hidden"),
        ("Hidden Fields", "hidden", owner._build_hidden_fields_page, "hidden"),
    ]
    owner.page_names = []
    owner.page_icons = []
    owner.page_builders = []
    owner.pages_loaded = []

    for index, (name, icon, builder, group) in enumerate(page_defs):
        owner.page_names.append(name)
        owner.page_icons.append(icon)
        owner.page_builders.append(builder)
        owner.pages_loaded.append(False)
        if group == "hidden":
            owner.stack.addWidget(QWidget())
            continue
        button = QPushButton(name.replace("&", "&&"))
        button.setObjectName("NavButton")
        button.setIcon(settings_nav_icon(icon, owner.palette.muted))
        button.setIconSize(QSize(18, 18))
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setProperty("group", group)
        button.clicked.connect(lambda _checked=False, i=index: owner._show_page(i))
        owner.nav_buttons[index] = button
        nav_layout.addWidget(button)
        owner.stack.addWidget(QWidget())
    nav_layout.addStretch(1)

    owner.model_status_label = QLabel()
    owner.model_status_label.setObjectName("Tiny")
    owner._refresh_model_status_label()
    owner.model_status_label.hide()
    sidebar_layout.addWidget(owner.model_status_label)
