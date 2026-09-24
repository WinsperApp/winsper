from __future__ import annotations

from .corrections import CorrectionRule, make_rule
from .parsing import parse_csv
from .settings_widgets import add_personalize_tab_separator


class SettingsMemoryMixin:
    def _build_memory_page(self, *, embedded: bool = False):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QFrame,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QPushButton,
            QTabWidget,
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
                "Words & corrections",
                "Teach Winsper names, specialist terms, and replacements.",
            )
        automatic_corrections = self._check(
            "correction_memory.enabled",
            self.config.correction_memory.enabled,
        )
        max_rules = self._line("correction_memory.max_rules", str(self.config.correction_memory.max_rules))
        max_rules.hide()

        tabs = QTabWidget()
        tabs.setObjectName("PersonalizeInnerTabs")
        terms_tab = QWidget()
        corrections_tab = QWidget()
        tabs.addTab(terms_tab, "Terms")
        tabs.addTab(corrections_tab, "Corrections")
        add_personalize_tab_separator(tabs)
        layout.addWidget(tabs, 1)

        terms_layout = QVBoxLayout(terms_tab)
        terms_layout.setContentsMargins(0, 16, 0, 0)
        terms_layout.setSpacing(14)
        terms_intro = QFrame()
        terms_intro.setObjectName("PersonalizeSectionIntro")
        terms_intro_layout = QVBoxLayout(terms_intro)
        terms_intro_layout.setContentsMargins(2, 0, 2, 4)
        terms_intro_layout.setSpacing(4)
        terms_title = QLabel("Words Winsper should know")
        terms_title.setObjectName("PersonalizeSectionTitle")
        terms_detail = QLabel("Add names, products, and specialist terms so they are written correctly.")
        terms_detail.setObjectName("PersonalizeSectionDetail")
        terms_intro_layout.addWidget(terms_title)
        terms_intro_layout.addWidget(terms_detail)
        terms_layout.addWidget(terms_intro)
        vocab = QListWidget()
        vocab.addItems(self.config.vocabulary)
        vocab.hide()
        self.widgets["vocabulary"] = vocab
        terms_layout.addWidget(vocab)
        vocab_composer = QFrame()
        vocab_composer.setObjectName("PersonalizeComposer")
        vocab_editor = QVBoxLayout(vocab_composer)
        vocab_editor.setContentsMargins(18, 16, 18, 16)
        vocab_editor.setSpacing(10)
        vocab_composer_title = QLabel("Add vocabulary")
        vocab_composer_title.setObjectName("PersonalizeComposerTitle")
        vocab_editor.addWidget(vocab_composer_title)
        vocab_row = QHBoxLayout()
        vocab_row.setSpacing(10)
        vocab_entry = QLineEdit()
        vocab_entry.setObjectName("DictionaryTermInput")
        vocab_entry.setPlaceholderText("Add a name or term, e.g. Winsper")
        add_vocab = QPushButton("Add term")
        add_vocab.setProperty("role", "dictionary-term-save")
        add_vocab.setObjectName("PrimaryButton")
        vocab_row.addWidget(vocab_entry, 1)
        vocab_row.addWidget(add_vocab)
        vocab_editor.addLayout(vocab_row)
        terms_layout.addWidget(vocab_composer)
        vocab_list_header = QHBoxLayout()
        vocab_list_header.setContentsMargins(2, 2, 2, 0)
        vocab_list_title = QLabel("Saved terms")
        vocab_list_title.setObjectName("PersonalizeListHeading")
        vocab_search = QLineEdit()
        vocab_search.setObjectName("SearchField")
        vocab_search.setPlaceholderText("Search terms")
        vocab_search.setMaximumWidth(330)
        vocab_list_header.addWidget(vocab_list_title)
        vocab_list_header.addStretch(1)
        vocab_list_header.addWidget(vocab_search)
        terms_layout.addLayout(vocab_list_header)
        vocab_cards = QVBoxLayout()
        vocab_cards.setSpacing(8)
        terms_layout.addLayout(vocab_cards)
        terms_layout.addStretch(1)
        vocab_editing = {"index": None}

        def clear_layout(target) -> None:
            while target.count():
                item = target.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()

        def refresh_vocab() -> None:
            clear_layout(vocab_cards)
            query = vocab_search.text().strip().casefold()
            items = [vocab.item(index).text() for index in range(vocab.count())]
            matches = [(index, term) for index, term in enumerate(items) if not query or query in term.casefold()]
            if not matches:
                message = (
                    "No terms match your search."
                    if query and items
                    else "No terms yet. Example: Winsper"
                )
                empty = self._empty_state(message)
                empty.setObjectName("PersonalizeEmptyState")
                vocab_cards.addWidget(empty)
                return
            for index, term in matches:
                item_card = QFrame()
                item_card.setObjectName("PersonalizeListRow")
                row = QHBoxLayout(item_card)
                row.setContentsMargins(12, 10, 10, 10)
                mark = QLabel("Aa")
                mark.setObjectName("PersonalizeRowMark")
                mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
                mark.setFixedSize(34, 34)
                title = QLabel(term)
                title.setObjectName("ListTitle")
                row.addWidget(mark)
                row.addWidget(title, 1)
                edit = QPushButton("Edit")
                edit.setObjectName("IconButton")
                remove = QPushButton("Remove")
                remove.setObjectName("IconButton")
                remove.setProperty("role", "dictionary-term-remove")
                edit.clicked.connect(lambda _checked=False, i=index: edit_vocab(i))
                remove.clicked.connect(lambda _checked=False, i=index: remove_vocab(i))
                row.addWidget(edit)
                row.addWidget(remove)
                vocab_cards.addWidget(item_card)

        def edit_vocab(index: int) -> None:
            vocab_editing["index"] = index
            vocab_entry.setText(vocab.item(index).text())
            add_vocab.setText("Save")
            vocab_entry.setFocus()
            vocab_entry.selectAll()

        def save_vocab() -> None:
            term = vocab_entry.text().strip()
            if not term:
                return
            index = vocab_editing["index"]
            existing = {vocab.item(item_index).text().casefold() for item_index in range(vocab.count()) if item_index != index}
            if term.casefold() in existing:
                self._show_inline_status("That term already exists", "bad")
                return
            if index is None:
                vocab.addItem(term)
            else:
                vocab.item(index).setText(term)
            vocab_editing["index"] = None
            vocab_entry.clear()
            add_vocab.setText("Add term")
            refresh_vocab()
            self._schedule_auto_save()
            self._show_inline_status("Dictionary updated")

        def remove_vocab(index: int) -> None:
            removed = vocab.takeItem(index).text()
            vocab_editing["index"] = None
            vocab_entry.clear()
            add_vocab.setText("Add term")
            refresh_vocab()
            self._schedule_auto_save()

            def undo() -> None:
                vocab.insertItem(min(index, vocab.count()), removed)
                refresh_vocab()
                self._schedule_auto_save()
                self._show_inline_status("Term restored")

            self._show_inline_status("Term removed", action_label="Undo", action_callback=undo)

        add_vocab.clicked.connect(save_vocab)
        vocab_entry.returnPressed.connect(save_vocab)
        vocab_search.textChanged.connect(refresh_vocab)
        refresh_vocab()

        corrections_layout = QVBoxLayout(corrections_tab)
        corrections_layout.setContentsMargins(0, 16, 0, 0)
        corrections_layout.setSpacing(14)

        correction_intro = QFrame()
        correction_intro.setObjectName("PersonalizeSectionIntro")
        correction_intro_layout = QVBoxLayout(correction_intro)
        correction_intro_layout.setContentsMargins(0, 0, 0, 2)
        correction_intro_layout.setSpacing(0)
        self._row(
            correction_intro_layout,
            "Automatic corrections",
            "Replace recurring misheard words before text is inserted.",
            automatic_corrections,
        )
        corrections_layout.addWidget(correction_intro)

        correction_composer = QFrame()
        correction_composer.setObjectName("PersonalizeComposer")
        editor = QVBoxLayout(correction_composer)
        editor.setContentsMargins(18, 16, 18, 16)
        editor.setSpacing(12)
        correction_composer_title = QLabel("New correction")
        correction_composer_title.setObjectName("PersonalizeComposerTitle")
        editor.addWidget(correction_composer_title)
        heard = QLineEdit()
        heard.setObjectName("CorrectionHeardInput")
        heard.setPlaceholderText("e.g. Win spur")
        replacement = QLineEdit()
        replacement.setObjectName("CorrectionReplacementInput")
        replacement.setPlaceholderText("e.g. Winsper")
        profiles = QLineEdit()
        profiles.hide()
        correction_fields = QHBoxLayout()
        correction_fields.setSpacing(12)
        heard_field = QVBoxLayout()
        heard_field.setSpacing(5)
        heard_label = QLabel("When Winsper hears")
        heard_label.setObjectName("PersonalizeFieldLabel")
        heard_field.addWidget(heard_label)
        heard_field.addWidget(heard)
        replacement_field = QVBoxLayout()
        replacement_field.setSpacing(5)
        replacement_label = QLabel("Write this instead")
        replacement_label.setObjectName("PersonalizeFieldLabel")
        replacement_field.addWidget(replacement_label)
        replacement_field.addWidget(replacement)
        arrow = QLabel("→")
        arrow.setObjectName("PersonalizeDirection")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setFixedWidth(28)
        correction_fields.addLayout(heard_field, 1)
        correction_fields.addWidget(arrow, 0, Qt.AlignmentFlag.AlignBottom)
        correction_fields.addLayout(replacement_field, 1)
        editor.addLayout(correction_fields)
        correction_actions = QHBoxLayout()
        save_rule = QPushButton("Add correction")
        save_rule.setProperty("role", "correction-save")
        save_rule.setObjectName("PrimaryButton")
        cancel_rule = QPushButton("Cancel edit")
        cancel_rule.hide()
        correction_actions.addWidget(save_rule)
        correction_actions.addWidget(cancel_rule)
        correction_actions.addStretch(1)
        editor.addLayout(correction_actions)
        corrections_layout.addWidget(correction_composer)

        correction_list_header = QHBoxLayout()
        correction_list_header.setContentsMargins(2, 2, 2, 0)
        correction_list_title = QLabel("Saved corrections")
        correction_list_title.setObjectName("PersonalizeListHeading")
        correction_search = QLineEdit()
        correction_search.setObjectName("SearchField")
        correction_search.setPlaceholderText("Search corrections")
        correction_search.setMaximumWidth(330)
        correction_list_header.addWidget(correction_list_title)
        correction_list_header.addStretch(1)
        correction_list_header.addWidget(correction_search)
        corrections_layout.addLayout(correction_list_header)
        correction_cards = QVBoxLayout()
        correction_cards.setSpacing(8)
        corrections_layout.addLayout(correction_cards)
        corrections_layout.addStretch(1)
        rule_editing = {"index": None}

        def refresh() -> None:
            clear_layout(correction_cards)
            query = correction_search.text().strip().casefold()
            matches = [
                (index, rule)
                for index, rule in enumerate(self.corrections)
                if not query or query in f"{rule.heard} {rule.replacement}".casefold()
            ]
            if not matches:
                message = (
                    "No corrections match your search."
                    if query and self.corrections
                    else "No corrections yet. Example: Win spur → Winsper"
                )
                empty = self._empty_state(message)
                empty.setObjectName("PersonalizeEmptyState")
                correction_cards.addWidget(empty)
                return
            for index, rule in matches:
                item_card = QFrame()
                item_card.setObjectName("PersonalizeListRow")
                row = QHBoxLayout(item_card)
                row.setContentsMargins(12, 10, 10, 10)
                mark = QLabel("→")
                mark.setObjectName("PersonalizeRowMark")
                mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
                mark.setFixedSize(34, 34)
                copy = QVBoxLayout()
                title = QLabel(f"{rule.heard}  →  {rule.replacement}")
                title.setObjectName("ListTitle")
                copy.addWidget(title)
                row.addWidget(mark)
                row.addLayout(copy, 1)
                edit = QPushButton("Edit")
                edit.setObjectName("IconButton")
                remove = QPushButton("Remove")
                remove.setObjectName("IconButton")
                remove.setProperty("role", "correction-remove")
                edit.clicked.connect(lambda _checked=False, i=index: edit_rule(i))
                remove.clicked.connect(lambda _checked=False, i=index: remove_rule(i))
                row.addWidget(edit)
                row.addWidget(remove)
                correction_cards.addWidget(item_card)

        def edit_rule(index: int) -> None:
            rule_editing["index"] = index
            rule = self.corrections[index]
            heard.setText(rule.heard)
            replacement.setText(rule.replacement)
            profiles.setText(", ".join(rule.profiles))
            save_rule.setText("Save changes")
            cancel_rule.show()
            heard.setFocus()

        def current_rule(existing: CorrectionRule | None = None) -> CorrectionRule | None:
            if not heard.text().strip() or not replacement.text().strip():
                return None
            return make_rule(
                heard.text(),
                replacement.text(),
                profiles=parse_csv(profiles.text()),
                enabled=existing.enabled if existing is not None else True,
                rule_id=existing.id if existing is not None else "",
                created_at=existing.created_at if existing is not None else "",
            )

        def add_update() -> None:
            index = rule_editing["index"]
            existing = self.corrections[index] if index is not None else None
            rule = current_rule(existing)
            if rule is None:
                heard.setFocus()
                return
            if existing is None:
                self.corrections.append(rule)
            else:
                self.corrections[index] = rule
            clear_editor()
            refresh()
            self._schedule_auto_save()
            self._show_inline_status("Correction saved")

        def remove_rule(index: int) -> None:
            removed = self.corrections.pop(index)
            clear_editor()
            refresh()
            self._schedule_auto_save()

            def undo() -> None:
                self.corrections.insert(min(index, len(self.corrections)), removed)
                refresh()
                self._schedule_auto_save()
                self._show_inline_status("Correction restored")

            self._show_inline_status("Correction removed", action_label="Undo", action_callback=undo)

        def clear_editor() -> None:
            rule_editing["index"] = None
            heard.clear()
            replacement.clear()
            profiles.clear()
            save_rule.setText("Add correction")
            cancel_rule.hide()

        save_rule.clicked.connect(add_update)
        cancel_rule.clicked.connect(clear_editor)
        replacement.returnPressed.connect(add_update)
        correction_search.textChanged.connect(refresh)
        refresh()
        return page
