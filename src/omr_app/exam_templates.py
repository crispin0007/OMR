"""Templates page: every ready-made exam layout, to change and save under a name of your own.

The built-in layouts never change; edits to one are saved as a new template, and Reset to default puts the
built-in's own values back. The user's templates are kept in the database and listed under Start from in New exam.
"""

import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from omr_core.sheet import MAX_ROLL_DIGITS, layout, render
from omr_core.store import Store

from .new_exam import (ANSWERED_WITH, BLANK, BUBBLE_SHAPES, PATTERN_NOTE, READY, SETS, Deduction, Ready, _marks,
                       saved_templates, spec_of)

LABEL_NAMES = (("A, B, C, D…", "letters"), ("a, b, c, d…", "lower"), ("1, 2, 3, 4…", "numbers"))
MINE = "My templates"


class TemplatesPage(QWidget):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.current = ""  # the template open in the editor
        self.loaded: Ready | None = None  # its values as saved, to tell edits apart
        self.mine: dict[str, Ready] = {}
        self.timer = QTimer(self, singleShot=True, interval=300)  # redraw the preview once typing pauses
        self.timer.timeout.connect(self.update_preview)

        self.list = QListWidget()
        self.list.setFixedWidth(330)
        self.list.currentItemChanged.connect(self._picked)
        self.damaged = QLabel(objectName="error", wordWrap=True)

        self.title = QLabel(objectName="title", wordWrap=True)
        self.kind = QLabel(objectName="muted", wordWrap=True)
        self.total = QSpinBox(minimum=1, maximum=300, value=100)
        self.sections = QTableWidget(0, 3)
        self.sections.setHorizontalHeaderLabels(["Subject or section", "Questions", "Answered with"])
        self.sections.verticalHeader().hide()
        self.sections.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sections.setMinimumHeight(170)
        add = QPushButton("Add section")
        add.clicked.connect(lambda: self.add_section("", 25, 0))
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_section)
        section_buttons = QHBoxLayout()
        section_buttons.addWidget(add)
        section_buttons.addWidget(remove)
        section_buttons.addStretch()
        self.options = QSpinBox(minimum=2, maximum=8)
        self.labels = QComboBox()
        for name, value in LABEL_NAMES:
            self.labels.addItem(name, value)
        self.roll = QSpinBox(minimum=0, maximum=MAX_ROLL_DIGITS, specialValueText="No roll number")
        self.sets = QComboBox()
        self.sets.addItems(SETS)
        self.shape = QComboBox()
        for name, value in BUBBLE_SHAPES:
            self.shape.addItem(name, value)
        self.right, self.wrong = _marks(1), Deduction()
        marks = QHBoxLayout()
        marks.addWidget(self.right)
        marks.addWidget(QLabel("Wrong"))
        marks.addWidget(self.wrong)
        marks.addStretch()
        form = QFormLayout()
        form.addRow("Questions (no sections)", self.total)
        form.addRow(self.sections)
        form.addRow(section_buttons)
        form.addRow("Options per question", self.options)
        form.addRow("Options shown as", self.labels)
        form.addRow("Roll number digits", self.roll)
        form.addRow("Question paper sets", self.sets)
        form.addRow("Bubbles", self.shape)
        form.addRow("Marks: correct", marks)
        for box in (self.total, self.options, self.roll, self.right, self.wrong):
            box.valueChanged.connect(self.timer.start)
        for box in (self.labels, self.sets, self.shape):
            box.currentIndexChanged.connect(self.timer.start)
        self.sections.itemChanged.connect(self._sections_changed)

        self.save_button = QPushButton("Save", objectName="primary")
        self.save_button.clicked.connect(self.save)
        save_as = QPushButton("Save as new template…")
        save_as.clicked.connect(self.save_as)
        self.reset_button = QPushButton("Reset to default")
        self.reset_button.clicked.connect(self.reset)
        self.rename_button = QPushButton("Rename…")
        self.rename_button.clicked.connect(self.rename)
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.clicked.connect(self.duplicate)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete)
        buttons = QHBoxLayout()
        for b in (self.save_button, save_as, self.reset_button, self.rename_button, self.duplicate_button,
                  self.delete_button):
            buttons.addWidget(b)
        buttons.addStretch()
        self.error = QLabel(objectName="error", wordWrap=True)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.addWidget(self.title)
        editor_layout.addWidget(self.kind)
        editor_layout.addLayout(form)
        editor_layout.addStretch()
        self.preview = QLabel(alignment=Qt.AlignHCenter | Qt.AlignTop)
        preview_scroll = QScrollArea(widgetResizable=True)
        preview_scroll.setWidget(self.preview)
        left = QVBoxLayout()
        left.addWidget(self.list, 1)
        left.addWidget(self.damaged)
        body = QHBoxLayout()
        body.addLayout(left)
        body.addWidget(editor, 3)
        body.addWidget(preview_scroll, 2)
        page = QVBoxLayout(self)
        page.addWidget(QLabel("Exam templates", objectName="title"))
        page.addWidget(QLabel("Built-in templates stay as they are: change one and save it under a new name, or put "
                              "its values back with Reset to default. Your templates are listed in New exam under "
                              "Start from. " + PATTERN_NOTE, objectName="muted", wordWrap=True))
        page.addLayout(body, 1)
        page.addLayout(buttons)
        page.addWidget(self.error)
        self.refresh(next(iter(READY)))

    # -- the list ------------------------------------------------------------------------------------------

    def refresh(self, select: str):
        self.mine, bad = saved_templates(self.store)
        self.damaged.setText(f"Can't use {', '.join(bad)}: the saved template is damaged. Delete it and make it "
                             "again." if bad else "")
        self.list.blockSignals(True)
        self.list.clear()
        for name in READY:
            self.list.addItem(name)
            self.list.item(self.list.count() - 1).setToolTip(name)  # long names are cut off in the list
        header = QListWidgetItem(MINE if self.mine else f"{MINE}: none yet")
        header.setFlags(Qt.NoItemFlags)
        font = header.font()
        font.setBold(True)
        header.setFont(font)
        self.list.addItem(header)
        for name in self.mine:
            self.list.addItem(name)
        self.list.blockSignals(False)
        found = self.list.findItems(select, Qt.MatchExactly)
        self.list.setCurrentItem(found[0] if found else self.list.item(0))

    def _picked(self, item: QListWidgetItem | None, before: QListWidgetItem | None):
        if item is None or item.text() == self.current:
            return
        if self.edited() and QMessageBox.question(
                self, "Discard changes", f"Discard your changes to “{self.current}”?") != QMessageBox.Yes:
            self.list.blockSignals(True)
            self.list.setCurrentItem(before)
            self.list.blockSignals(False)
            return
        self.open(item.text())

    def open(self, name: str):
        self.current = name
        self.loaded = READY.get(name) or self.mine[name]
        built_in = name in READY
        self.title.setText(name)
        self.kind.setText("Built-in template: save your changes as a new template." if built_in
                          else "Your template.")
        self.save_button.setVisible(not built_in)
        self.reset_button.setText("Reset to default" if built_in else "Undo changes")
        for b in (self.rename_button, self.delete_button):
            b.setVisible(not built_in)
        self.fill(self.loaded)

    # -- the editor ----------------------------------------------------------------------------------------

    def fill(self, r: Ready):
        for box in (self.total, self.options, self.roll, self.right, self.wrong, self.labels, self.sets, self.shape):
            box.blockSignals(True)
        self.total.setValue(r.total or 100)
        self.options.setValue(r.options)
        self.labels.setCurrentIndex(self.labels.findData(r.labels))
        self.roll.setValue(r.roll)
        self.sets.setCurrentIndex(r.sets - 1 if r.sets else 0)
        self.shape.setCurrentIndex(self.shape.findData(r.shape))
        self.right.setValue(r.right)
        self.wrong.setValue(r.wrong)
        for box in (self.total, self.options, self.roll, self.right, self.wrong, self.labels, self.sets, self.shape):
            box.blockSignals(False)
        self.sections.setRowCount(0)
        for name, count, *digits in r.sections:
            self.add_section(name, count, digits[0] if digits else 0)
        self._sections_changed()

    def add_section(self, name: str, count: int, digits: int):
        n = self.sections.rowCount()
        self.sections.blockSignals(True)
        self.sections.insertRow(n)
        self.sections.setItem(n, 0, QTableWidgetItem(name or f"Subject {n + 1}"))
        self.sections.setItem(n, 1, QTableWidgetItem(str(count)))
        answered = QComboBox()
        answered.addItems(ANSWERED_WITH)
        answered.setCurrentIndex(digits)
        answered.currentIndexChanged.connect(self.timer.start)
        self.sections.setCellWidget(n, 2, answered)
        self.sections.blockSignals(False)
        self._sections_changed()

    def remove_section(self):
        row = self.sections.currentRow()
        self.sections.removeRow(row if row >= 0 else self.sections.rowCount() - 1)
        self._sections_changed()

    def _sections_changed(self, *_):
        self.total.setEnabled(self.sections.rowCount() == 0)
        self.timer.start()

    def ready(self) -> Ready:
        """The editor's values; ValueError names a section row that needs fixing."""
        sections = []
        for r in range(self.sections.rowCount()):
            name = (self.sections.item(r, 0).text() if self.sections.item(r, 0) else "").strip()
            try:
                count = int(self.sections.item(r, 1).text())
                if count < 1:
                    raise ValueError
            except (AttributeError, ValueError):
                raise ValueError(f"Section {r + 1}: the number of questions must be a whole number above 0") from None
            if not name or name in (s[0] for s in sections):
                raise ValueError(f"Section {r + 1} needs its own name")
            digits = self.sections.cellWidget(r, 2).currentIndex()
            sections.append((name, count, digits) if digits else (name, count))
        sets = self.sets.currentIndex()
        return Ready(sections, 0 if sections else self.total.value(), self.options.value(), self.right.value(),
                     self.wrong.value(), self.roll.value(), sets + 1 if sets else 0, self.labels.currentData(),
                     self.shape.currentData())

    def edited(self) -> bool:
        try:
            return bool(self.current) and self.ready() != self.loaded
        except ValueError:
            return True

    def checked(self) -> tuple[Ready, dict] | None:
        """The editor's values if the sheet they make fits on the page; otherwise says why and gives None."""
        try:
            r = self.ready()
            made = layout(spec_of(self.current, r))
        except ValueError as e:
            self.error.setText(str(e))
            return None
        self.error.clear()
        return r, made

    def update_preview(self):
        checked = self.checked()
        if checked is None:
            self.preview.clear()
            return
        page = render(checked[1], dpi=40)
        image = QImage(page.data, page.shape[1], page.shape[0], page.strides[0], QImage.Format_BGR888).copy()
        self.preview.setPixmap(QPixmap.fromImage(image))

    # -- saving --------------------------------------------------------------------------------------------

    def ask_name(self, title: str, suggested: str, keeping: str = "") -> str:
        """A new template name from the user, or "" if they cancel."""
        while True:
            name, ok = QInputDialog.getText(self, title, "Template name:", text=suggested)
            name = name.strip()
            if not ok or not name:
                return ""
            if name == keeping:
                return name
            if name in READY or name in self.mine or name == BLANK:
                QMessageBox.warning(self, title, f"There is already a template called “{name}”. Pick another name.")
                suggested = name
                continue
            return name

    def _store(self, name: str, r: Ready, replacing: str = ""):
        try:
            self.store.save_template(name, json.dumps(r._asdict()), replacing)
        except ValueError as e:
            self.error.setText(f"Can't save: {e}")
            return
        self.current = ""  # saved, so nothing to discard
        self.refresh(name)

    def save(self):
        checked = self.checked()
        if checked is not None and self.current in self.mine:
            self._store(self.current, checked[0])

    def save_as(self):
        checked = self.checked()
        if checked is None:
            return
        name = self.ask_name("Save as new template", f"{self.current.split(':')[0]} (my copy)")
        if name:
            self._store(name, checked[0])

    def duplicate(self):
        name = self.ask_name("Duplicate template", f"{self.current.split(':')[0]} (copy)")
        if name:
            self._store(name, self.loaded)

    def rename(self):
        old = self.current
        name = self.ask_name("Rename template", old, keeping=old)
        if name and name != old:
            self._store(name, self.mine[old], replacing=old)

    def reset(self):
        self.fill(self.loaded)

    def delete(self):
        name = self.current
        if QMessageBox.question(self, "Delete template", f"Delete the template “{name}”? Exams made from it keep "
                                "their sheet.") != QMessageBox.Yes:
            return
        self.store.delete_template(name)
        self.current = ""
        self.refresh(next(iter(READY)))
