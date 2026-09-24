from __future__ import annotations

from .config import Snippet
from .parsing import parse_csv


class SettingsSnippetsMixin:
    def _build_snippets_page(self, *, embedded: bool = False):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QFrame,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )

        if embedded:
            page = QWidget()
            page.setObjectName("PersonalizeEmbeddedPage")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(22, 18, 22, 22)
            layout.setSpacing(14)
        else:
            page, layout = self._page(
                "Text shortcuts",
                "Say a short phrase to insert text you use often.",
            )
        settings_card = QFrame()
        settings_card.setObjectName("PersonalizeSectionIntro")
        settings_layout = QHBoxLayout(settings_card)
        settings_layout.setContentsMargins(2, 0, 2, 4)
        settings_layout.setSpacing(12)
        intro_copy = QVBoxLayout()
        intro_copy.setSpacing(4)
        intro_title = QLabel("Reusable text, spoken naturally")
        intro_title.setObjectName("PersonalizeSectionTitle")
        intro_detail = QLabel("Create a phrase once, then say its trigger anywhere in Windows.")
        intro_detail.setObjectName("PersonalizeSectionDetail")
        intro_copy.addWidget(intro_title)
        intro_copy.addWidget(intro_detail)
        settings_layout.addLayout(intro_copy, 1)
        shortcut_toggle = self._check("snippets.enabled", self.config.snippets.enabled)
        settings_layout.addWidget(shortcut_toggle)
        layout.addWidget(settings_card)

        composer = QFrame()
        composer.setObjectName("PersonalizeComposer")
        editor = QVBoxLayout(composer)
        editor.setContentsMargins(18, 16, 18, 16)
        editor.setSpacing(10)
        composer_title = QLabel("New shortcut")
        composer_title.setObjectName("PersonalizeComposerTitle")
        editor.addWidget(composer_title)
        name = QLineEdit()
        name.setPlaceholderText("Name, e.g. Support reply")
        trigger = QLineEdit()
        trigger.setPlaceholderText("Voice trigger, e.g. insert support reply")
        aliases = QLineEdit()
        aliases.setPlaceholderText("Add alternatives, separated by commas")
        profiles = QLineEdit()
        profiles.hide()
        text = QTextEdit()
        text.setObjectName("TextShortcutContentInput")
        text.setPlaceholderText("e.g. Thanks for contacting Winsper Support.")
        text.setMaximumHeight(86)
        form_top = QHBoxLayout()
        form_top.setSpacing(12)
        name_field = QVBoxLayout()
        name_field.setSpacing(5)
        name_label = QLabel("Name")
        name_label.setObjectName("PersonalizeFieldLabel")
        name_field.addWidget(name_label)
        name_field.addWidget(name)
        trigger_field = QVBoxLayout()
        trigger_field.setSpacing(5)
        trigger_label = QLabel("What you will say")
        trigger_label.setObjectName("PersonalizeFieldLabel")
        trigger_field.addWidget(trigger_label)
        trigger_field.addWidget(trigger)
        form_top.addLayout(name_field, 1)
        form_top.addLayout(trigger_field, 1)
        editor.addLayout(form_top)
        text_label = QLabel("Text to insert")
        text_label.setObjectName("PersonalizeFieldLabel")
        editor.addWidget(text_label)
        editor.addWidget(text)
        aliases_label = QLabel("Other phrases (optional)")
        aliases_label.setObjectName("PersonalizeFieldLabel")
        editor.addWidget(aliases_label)
        editor.addWidget(aliases)
        composer_actions = QHBoxLayout()
        save_button = QPushButton("Add shortcut")
        save_button.setObjectName("PrimaryButton")
        cancel_button = QPushButton("Cancel edit")
        cancel_button.hide()
        composer_actions.addWidget(save_button)
        composer_actions.addWidget(cancel_button)
        composer_actions.addStretch(1)
        editor.addLayout(composer_actions)
        layout.addWidget(composer)

        list_header = QHBoxLayout()
        list_header.setContentsMargins(2, 2, 2, 0)
        list_title = QLabel("Saved shortcuts")
        list_title.setObjectName("PersonalizeListHeading")
        search = QLineEdit()
        search.setObjectName("SearchField")
        search.setPlaceholderText("Search shortcuts")
        search.setMaximumWidth(330)
        list_header.addWidget(list_title)
        list_header.addStretch(1)
        list_header.addWidget(search)
        layout.addLayout(list_header)
        list_container = QVBoxLayout()
        list_container.setSpacing(8)
        layout.addLayout(list_container)
        editing = {"index": None}

        def clear_cards() -> None:
            while list_container.count():
                item = list_container.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()

        def refresh() -> None:
            clear_cards()
            query = search.text().strip().casefold()
            matches = [
                (index, snippet)
                for index, snippet in enumerate(self.snippets)
                if not query or query in f"{snippet.name} {snippet.trigger} {snippet.text}".casefold()
            ]
            if not matches:
                message = (
                    "No shortcuts match your search."
                    if query and self.snippets
                    else (
                        'No shortcuts yet. Example: "insert support reply" → '
                        '"Thanks for contacting Winsper Support."'
                    )
                )
                empty = self._empty_state(message)
                empty.setObjectName("PersonalizeEmptyState")
                list_container.addWidget(empty)
                return
            for index, snippet in matches:
                card = QFrame()
                card.setObjectName("PersonalizeListRow")
                row = QHBoxLayout(card)
                row.setContentsMargins(12, 10, 10, 10)
                mark = QLabel("T")
                mark.setObjectName("PersonalizeRowMark")
                mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
                mark.setFixedSize(34, 34)
                copy = QVBoxLayout()
                title = QLabel(snippet.name or snippet.trigger)
                title.setObjectName("ListTitle")
                detail = QLabel(f"Say “{snippet.trigger}”  ·  {snippet.text[:90]}")
                detail.setObjectName("ListMeta")
                detail.setWordWrap(True)
                copy.addWidget(title)
                copy.addWidget(detail)
                row.addWidget(mark)
                row.addLayout(copy, 1)
                edit_button = QPushButton("Edit")
                edit_button.setObjectName("IconButton")
                remove_button = QPushButton("Remove")
                remove_button.setObjectName("IconButton")
                remove_button.setProperty("role", "shortcut-remove")
                edit_button.clicked.connect(lambda _checked=False, i=index: edit_snippet(i))
                remove_button.clicked.connect(lambda _checked=False, i=index: remove_snippet(i))
                row.addWidget(edit_button)
                row.addWidget(remove_button)
                list_container.addWidget(card)

        def edit_snippet(index: int) -> None:
            snippet = self.snippets[index]
            editing["index"] = index
            name.setText(snippet.name)
            trigger.setText(snippet.trigger)
            aliases.setText(", ".join(snippet.aliases))
            profiles.setText(", ".join(snippet.profiles))
            text.setPlainText(snippet.text)
            composer_title.setText("Edit shortcut")
            save_button.setText("Save changes")
            cancel_button.show()
            name.setFocus()

        def current_snippet() -> Snippet | None:
            if not trigger.text().strip() or not text.toPlainText().strip():
                return None
            return Snippet(
                name=name.text().strip() or trigger.text().strip(),
                trigger=trigger.text().strip(),
                text=text.toPlainText().strip(),
                aliases=parse_csv(aliases.text()),
                profiles=parse_csv(profiles.text()),
            )

        def add_update() -> None:
            snippet = current_snippet()
            if snippet is None:
                trigger.setFocus()
                return
            index = editing["index"]
            if index is None:
                self.snippets.append(snippet)
            else:
                self.snippets[index] = snippet
            clear_editor()
            refresh()
            self._schedule_auto_save()
            self._show_inline_status("Shortcut saved")

        def remove_snippet(index: int) -> None:
            removed = self.snippets.pop(index)
            if editing["index"] == index:
                clear_editor()
            refresh()
            self._schedule_auto_save()

            def undo() -> None:
                self.snippets.insert(min(index, len(self.snippets)), removed)
                refresh()
                self._schedule_auto_save()
                self._show_inline_status("Shortcut restored")

            self._show_inline_status("Shortcut removed", action_label="Undo", action_callback=undo)

        def clear_editor() -> None:
            editing["index"] = None
            name.clear()
            trigger.clear()
            aliases.clear()
            profiles.clear()
            text.clear()
            composer_title.setText("New shortcut")
            save_button.setText("Add shortcut")
            cancel_button.hide()

        save_button.clicked.connect(add_update)
        cancel_button.clicked.connect(clear_editor)
        search.textChanged.connect(refresh)
        refresh()
        layout.addStretch(1)
        return page
