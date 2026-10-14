"""Answer key tab: a row per question to click or type the right options into, with CSV import and export.

The key is kept as text in the format `parse_key` reads, so the grid, the
pasted text and the CSV files are three ways to edit the same key.
"""

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from omr_core.grading import (BONUS, DROPPED, EITHER, changed_questions, describe, format_key, key_from_csv,
                              key_from_sheet, key_to_csv, parse_key, summary)
from omr_core.reader import read_or_reason
from omr_core.sheet import LABELS
from omr_core.sources import read_pages
from omr_core.template import DIGITS

from .theme import tokens

ALL_SETS = "All sets"


class KeyGrid(QTableWidget):
    """The key for one set. Keys: a letter sets that answer and moves down, Shift+letter adds or removes it
    (more than one correct option), / makes the ticked options either-or, * marks a bonus, Space or Delete drops
    the question, Enter moves down.
    On a numeric question a digit or Enter, or a click, asks for the number."""

    def __init__(self, tab: "KeyTab"):
        super().__init__(0, 0)
        self.tab = tab
        self.setSelectionMode(QTableWidget.NoSelection)  # the answers are what's coloured; the current question
        # is marked by its number cell, and the arrow keys still move it
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cellClicked.connect(self.pick)
        self.currentCellChanged.connect(lambda row, *_: self.tab.mark_current(row))

    def keyPressEvent(self, event):
        row = self.currentRow()
        text = event.text().upper()
        if row not in self.tab.numeric:
            text = self.tab.printed.get(event.text(), text)  # 1 or a, on a sheet printed that way
        if row < 0 or event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home,
                                      Qt.Key_End, Qt.Key_Tab):
            super().keyPressEvent(event)
        elif row in self.tab.numeric and (text.isdigit() or event.key() in (Qt.Key_Return, Qt.Key_Enter)):
            self.tab.ask_number(row, text if text.isdigit() else None)
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.down(row)
        elif event.key() in (Qt.Key_Space, Qt.Key_Delete, Qt.Key_Backspace):
            self.tab.set_answer(row, DROPPED)
            self.down(row)
        elif text == BONUS:
            self.tab.set_answer(row, BONUS)
            self.down(row)
        elif text == EITHER and row not in self.tab.numeric:
            self.tab.either(row)
        elif text and text in self.tab.options and row not in self.tab.numeric:
            if event.modifiers() & Qt.ShiftModifier:
                self.tab.toggle(row, text)
            else:
                self.tab.set_answer(row, text)
                self.down(row)
        else:
            super().keyPressEvent(event)

    def down(self, row: int):
        self.setCurrentCell(min(row + 1, self.rowCount() - 1), max(self.currentColumn(), 0))

    def pick(self, row: int, col: int):
        option = col - 2
        if row in self.tab.numeric and 0 <= option < self.tab.bonus_col - 2:
            self.tab.ask_number(row)
        elif 0 <= option < len(self.tab.options):
            letter = self.tab.options[option]
            if QApplication.keyboardModifiers() & Qt.ControlModifier:
                self.tab.toggle(row, letter)
            else:
                self.tab.set_answer(row, "" if self.tab.answer(row) == letter else letter)
        elif col == self.tab.bonus_col:
            self.tab.mistake_menu(row).exec(self.viewport().mapToGlobal(self.visualRect(self.model().index(row, col))
                                                                        .bottomLeft()))


class KeyTab(QWidget):
    def __init__(self, check, key_edit: QPlainTextEdit, key_status: QLabel):
        super().__init__()
        self.check = check
        self.key_edit = key_edit
        self.options = ""  # the option letters of every question with options
        self.printed: dict[str, str] = {}  # label printed in a bubble to its option letter, e.g. "1": "A"
        self.per_question: list[str] = []  # each question's options, DIGITS for a numeric one
        self.numeric: set[int] = set()  # rows of numeric questions
        self.bonus_col = 2
        self.shown_exam = None  # the exam the set list was made for
        self.sets = QComboBox()
        self.sets.currentIndexChanged.connect(self.refresh)
        self.count = QLabel(objectName="muted")
        self.sheet_button = QPushButton("Read from a filled sheet…")
        self.sheet_button.setToolTip("Fill one answer sheet with the right answers, scan or photograph it, and open it "
                                     "here; its set code says which set's key it is")
        self.sheet_button.clicked.connect(self.read_master)
        self.import_button = QPushButton("Import CSV…")
        self.import_button.clicked.connect(self.import_csv)
        self.export_button = QPushButton("Export CSV…")
        self.export_button.clicked.connect(self.export_csv)
        self.paste_button = QPushButton("Paste as text", checkable=True)
        self.paste_button.setToolTip("Type or paste the key as letters, e.g. ABDCA…, or A: ABDC… per set")
        self.paste_button.toggled.connect(self.show_text)
        self.log_button = QPushButton("Key changes…")
        self.log_button.setToolTip("Who changed which answer in the key and when, with undo")
        self.log_button.clicked.connect(self.show_log)
        self.changes = QLabel(objectName="muted", wordWrap=True)
        top = QHBoxLayout()
        top.addWidget(QLabel("Key for"))
        top.addWidget(self.sets)
        top.addWidget(self.count, 1)
        top.addWidget(self.sheet_button)
        top.addWidget(self.import_button)
        top.addWidget(self.export_button)
        top.addWidget(self.paste_button)
        top.addWidget(self.log_button)
        self.grid = KeyGrid(self)
        help_text = QLabel("Click the right option or press its letter; the next question is selected. Shift+letter "
                           "or Ctrl+click adds a second correct option. A question with a mistake: click its "
                           "Mistake cell to give everyone the marks (bonus, or press *), drop it (Space), or accept "
                           "either of the ticked options (/). Sheets already read are marked again at once. "
                           "For a numeric question, type the number.",
                           objectName="muted", wordWrap=True)
        key_edit.hide()
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(key_status)
        layout.addWidget(help_text)
        layout.addWidget(self.changes)
        layout.addWidget(self.grid, 1)
        layout.addWidget(key_edit, 1)

    # -- the key ------------------------------------------------------------------------------------------

    def set_code(self) -> str:
        return "" if self.sets.currentText() in ("", ALL_SETS) else self.sets.currentText()

    def keys(self) -> dict[str, list[str]]:
        """The keys in the text, or {} when it doesn't read."""
        try:
            return parse_key(self.key_edit.toPlainText(), len(self.check.questions), self.per_question)
        except ValueError:
            return {}

    def answer(self, row: int) -> str:
        key = self.keys().get(self.set_code())
        return key[row] if key else DROPPED

    def set_answer(self, row: int, answer: str, set_code: str | None = None):
        keys = self.keys()
        if not keys and self.key_edit.toPlainText().strip():
            QMessageBox.warning(self, "Fix the key first", "The typed key has a mistake; fix it under Paste as text.")
            return
        key = keys.setdefault(self.set_code() if set_code is None else set_code, [DROPPED] * len(self.check.questions))
        key[row] = answer or DROPPED
        self.key_edit.setPlainText(format_key(keys))  # the check page rescores, logs the change and redraws

    def toggle(self, row: int, letter: str):
        now = self.answer(row)
        now = "" if now in (BONUS, DROPPED) else now
        picked = set(now) ^ {letter}
        self.set_answer(row, (EITHER if EITHER in now else "").join(o for o in self.options if o in picked))

    def either(self, row: int):
        """Make the ticked options either-or (A/C), or all needed together (AC) when they already are."""
        now = self.answer(row)
        if now in (BONUS, DROPPED) or len(now.replace(EITHER, "")) < 2:
            self.window().statusBar().showMessage(f"Q{self.check.questions[row]}: tick two or more options first "
                                                  "(Ctrl+click or Shift+letter)", 5000)
            return
        self.set_answer(row, now.replace(EITHER, "") if EITHER in now else EITHER.join(now))

    def mistake_menu(self, row: int) -> QMenu:
        """What to do about a question with a mistake: bonus, drop, either answer, or undo the last change."""
        q, now = self.check.questions[row], self.answer(row)
        menu = QMenu(self)
        menu.addAction("Bonus: full marks to everyone", lambda: self.set_answer(row, BONUS))
        menu.addAction("Drop: count it for no one (the total goes down)", lambda: self.set_answer(row, DROPPED))
        if row in self.numeric:
            menu.addAction("Accept more than one number…", lambda: self.ask_number(row))
        elif EITHER in now:
            menu.addAction(f"Need all of {now.replace(EITHER, ', ')} together", lambda: self.either(row))
        else:
            menu.addAction("Either ticked option is right", lambda: self.either(row)).setEnabled(
                now not in (BONUS, DROPPED) and len(now) > 1)
        last = next((b for _, _, c, n, b, _ in self.check.store.key_log(self.check.exam.id)
                     if c == self.set_code() and n == q), None)
        if last is not None:
            menu.addSeparator()
            menu.addAction(f"Undo the last change (back to {describe(last)})", lambda: self.set_answer(row, last))
        return menu

    def show_log(self):
        LogDialog(self).exec()

    def ask_number(self, row: int, typed: str | None = None):
        now = self.answer(row)
        start = typed if typed is not None else now if now[:1].isdigit() else ""
        text, ok = QInputDialog.getText(self, "Answer key", f"Q{self.check.questions[row]}: the right number, or "
                                        "numbers separated by / when more than one is right (leave it empty to drop "
                                        "the question)", text=start)
        text = text.strip().replace(" ", "")
        if not ok:
            return
        if text and not all(n.isdigit() for n in text.split(EITHER)):
            QMessageBox.warning(self, "Not a number", f"{text} isn't a whole number.")
            return
        self.set_answer(row, EITHER.join(dict.fromkeys(str(int(n)) for n in text.split(EITHER))) if text else DROPPED)
        self.grid.down(row)

    # -- showing it -----------------------------------------------------------------------------------------

    def refresh(self):
        """Redraw for the open exam and the key in the text."""
        exam = self.check.exam
        t = exam.template if exam else None
        options = "".join(sorted({o for g in t.grids if g.kind == "questions" for o in g.options})) if t else ""
        sets = next((g.options for g in t.grids if g.kind == "set_code"), "") if t else ""
        self.options = options
        labels = LABELS[json.loads(exam.template_json).get("print", {}).get("labels", "letters")] if exam else ""
        self.printed = {p: o for o, p in zip("ABCDEFGH", labels) if o in options and p != o}
        self.per_question = t.answer_options() if t else []
        self.numeric = {r for r, o in enumerate(self.per_question) if o == DIGITS}
        keys = self.keys()
        self.sets.blockSignals(True)
        if exam is not self.shown_exam:
            self.shown_exam = exam
            self.sets.clear()
            self.sets.addItems([ALL_SETS, *sets])
        if keys and not self.set_code() and "" not in keys:  # only keys for sets, e.g. set A pasted: show set A
            self.sets.setCurrentText(next(iter(keys)))
        self.sets.blockSignals(False)
        self.sets.setVisible(bool(sets))
        questions = self.check.questions
        heads = [o + (f" ({p})" if (p := next((k for k, v in self.printed.items() if v == o), "")) else "")
                 for o in options] or ["Number"]  # e.g. "A (1)"; a sheet of only numeric questions: one column
        self.bonus_col = 2 + len(heads)
        if [self.grid.horizontalHeaderItem(c).text() if self.grid.horizontalHeaderItem(c) else ""
                for c in range(self.grid.columnCount())] != ["Question", "Section", *heads, "Mistake"]:
            self.grid.setColumnCount(len(heads) + 3)
            self.grid.setHorizontalHeaderLabels(["Question", "Section", *heads, "Mistake"])
        self.grid.setRowCount(len(questions))
        key = keys.get(self.set_code()) or [DROPPED] * len(questions)
        changes = dict(changed_questions(key, questions))
        sections = self.check.sections
        accent, on, warn = QColor(tokens()["accent"]), QColor("#ffffff"), QColor(tokens()["warn_bg"])
        for r, q in enumerate(questions):
            section = next((s.name for s in sections if s.first <= q <= s.last), "")
            for c, text in ((0, str(q)), (1, section)):
                self._cell(r, c, text, None, None)
            for i, o in enumerate(list(options) or ["Number"]):
                if r in self.numeric:  # the number goes in the first answer column
                    given = key[r][:1].isdigit() and i == 0
                    self._cell(r, 2 + i, key[r] if given else "", accent if given else None, on if given else None)
                    continue
                chosen = key[r] not in (BONUS, DROPPED) and o in key[r]
                self._cell(r, 2 + i, o, accent if chosen else None, on if chosen else None)
            changed = changes.get(q)
            self._cell(r, self.bonus_col, changed and ("Bonus" if key[r] == BONUS else "Dropped" if key[r] == DROPPED
                                                       else describe(key[r])),
                       warn if changed else None, None)
        answered = sum(a != DROPPED for a in key)
        text = f"{answered} of {len(questions)} questions in the key"
        if self.set_code() and self.set_code() not in keys and "" in keys:
            text = f"Set {self.set_code()} uses the key for all sets until you give it its own"
        self.count.setText(text if exam else "")
        self.changes.setText(f"Changed ({summary(list(changes.items()))}): "
                             + "  ·  ".join(f"Q{q} {c}" for q, c in changes.items()) if changes else "")
        self.changes.setVisible(bool(changes))
        for w in (self.grid, self.sheet_button, self.import_button, self.paste_button, self.sets, self.log_button):
            w.setEnabled(exam is not None)
        self.export_button.setEnabled(bool(keys))
        if self.grid.currentRow() < 0 and questions:
            self.grid.setCurrentCell(0, 2)
        self.mark_current(self.grid.currentRow())

    def _cell(self, row: int, col: int, text: str, back: QColor | None, fore: QColor | None):
        item = self.grid.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignCenter)
            self.grid.setItem(row, col, item)
        item.setText(text)
        item.setBackground(QBrush(back) if back else QBrush())
        item.setForeground(QBrush(fore) if fore else QBrush())

    def mark_current(self, row: int):
        accent = QColor(tokens()["accent"])
        accent.setAlpha(60)
        for r in range(self.grid.rowCount()):
            item = self.grid.item(r, 0)
            if item:
                item.setBackground(QBrush(accent) if r == row else QBrush())

    def show_text(self, on: bool):
        self.key_edit.setVisible(on)
        self.grid.setVisible(not on)

    # -- CSV ----------------------------------------------------------------------------------------------

    def import_csv(self):
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getOpenFileName(self, "Import answer key", docs, "CSV (*.csv)")
        if not path:
            return
        try:
            keys = key_from_csv(Path(path).read_text(encoding="utf-8-sig"), self.check.questions, self.per_question)
        except (OSError, UnicodeDecodeError, ValueError) as e:
            QMessageBox.warning(self, "Can't import that key", f"{path}\n\n{e}")
            return
        self.key_edit.setPlainText(format_key(keys))

    def read_master(self):
        path, _ = QFileDialog.getOpenFileName(self, "Answer key: the filled master sheet", "",
                                              "Scans (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if not path:
            return
        try:
            page = next(read_pages(path))
        except (OSError, ValueError, StopIteration) as e:
            QMessageBox.warning(self, "Can't open that file", f"{path}\n\n{e or 'it has no pages'}")
            return
        result, problem = read_or_reason(page, self.check.exam.template)
        if result is None:
            QMessageBox.warning(self, "Can't read the master sheet", f"{problem.removeprefix('unreadable: ')}.\n\n"
                                "Check that it is this exam's sheet with all four corner circles in the picture.")
            return
        has_sets = self.sets.count() > 1
        set_code = result.set_code if has_sets and result.set_code not in ("", "?") else self.set_code()
        keys = self.keys()
        name = f"set {set_code}" if set_code else "all sets"
        if keys.get(set_code) and QMessageBox.question(
                self, "Replace the key", f"Replace the key for {name} with the one on this sheet?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        key, doubtful = key_from_sheet(result.answers, result.flags, self.check.questions)
        keys[set_code] = key
        self.key_edit.setPlainText(format_key(keys))
        self.sets.setCurrentText(set_code or ALL_SETS)
        given = sum(a != DROPPED for a in key)
        lines = [f"Key for {name}: {given} of {len(key)} questions read from the sheet."]
        if doubtful:
            lines.append("Not taken, because the mark was unclear or doubled: "
                         + ", ".join(f"Q{q}" for q in doubtful) + ". Click their answers in the grid.")
        if has_sets and result.set_code in ("", "?"):
            lines.append(f"The sheet's set code couldn't be read, so this is the key for {name}.")
        if given + len(doubtful) < len(key):
            lines.append("Questions left blank on the sheet are left out of the key.")
        QMessageBox.information(self, "Key read", "\n\n".join(lines))

    def export_csv(self):
        exam = self.check.exam
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Export answer key", str(docs / f"{exam.name} key.csv"),
                                              "CSV (*.csv)")
        if not path:
            return
        try:
            Path(path).write_text(key_to_csv(self.keys(), self.check.questions), encoding="utf-8")
        except OSError as e:  # e.g. the file is open in Excel
            QMessageBox.warning(self, "Couldn't save", f"{path}\n\n{e}")
            return
        self.window().statusBar().showMessage(f"Saved {path}", 5000)


class LogDialog(QDialog):
    """Every logged change to the key, newest first, with undo."""

    def __init__(self, tab: KeyTab):
        super().__init__(tab)
        self.tab = tab
        self.setWindowTitle("Answer key changes")
        self.resize(640, 400)
        self.rows = tab.check.store.key_log(tab.check.exam.id)
        self.table = QTableWidget(len(self.rows), 6)
        self.table.setHorizontalHeaderLabels(["When", "Who", "Set", "Question", "Was", "Now"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        for r, (at, user, set_code, q, before, after) in enumerate(self.rows):
            for c, text in enumerate((at.replace("T", " "), user, set_code or ALL_SETS, f"Q{q}", describe(before),
                                      describe(after))):
                self.table.setItem(r, c, QTableWidgetItem(text))
        empty = QLabel("No changes yet. Answers typed in for the first time aren't listed; changes after that are.",
                       objectName="muted", wordWrap=True)
        empty.setVisible(not self.rows)
        self.undo = QPushButton("Undo this change")
        self.undo.setToolTip("Put the selected question's answer back to what it was")
        self.undo.clicked.connect(self.undo_selected)
        self.undo.setEnabled(False)
        self.table.itemSelectionChanged.connect(lambda: self.undo.setEnabled(bool(self.table.selectedItems())))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.addButton(self.undo, QDialogButtonBox.ActionRole)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(empty)
        layout.addWidget(self.table, 1)
        layout.addWidget(buttons)

    def undo_selected(self):
        _, _, set_code, q, before, after = self.rows[self.table.currentRow()]
        row = self.tab.check.questions.index(q)
        key = self.tab.keys().get(set_code)
        now = key[row] if key else DROPPED
        if now != after and QMessageBox.question(
                self, "Changed since", f"Q{q} is now {describe(now)}, changed again since. Set it back to "
                f"{describe(before)} anyway?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.tab.set_answer(row, before, set_code)
        self.accept()
