"""New sheet page: make an answer sheet by choosing questions, options, roll number, sets and sections (US6).

The sheet is drawn for you and previewed as you change the choices. Save it as a
template for exams, and save the PDF to print.
"""

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from omr_core.sheet import SheetSection, SheetSpec, layout, render, write_pdf

from .dashboard import card
from .exams import USER_TEMPLATES

SETS = ["No sets"] + [f"{n} sets (A to {'ABCDEFGH'[n - 1]})" for n in range(2, 9)]
SECTION_COLUMNS = ["Section", "Questions", "Correct", "Wrong"]


class NewSheetPage(QWidget):
    saved = Signal(str)  # path of a saved template

    def __init__(self):
        super().__init__()
        self.template: dict | None = None
        self.timer = QTimer(self, singleShot=True, interval=250)  # redraw once typing pauses
        self.timer.timeout.connect(self.update_preview)

        self.name = QLineEdit("Answer sheet")
        self.questions = QSpinBox(minimum=1, maximum=300, value=100)
        self.options = QSpinBox(minimum=2, maximum=8, value=4)
        self.roll = QSpinBox(minimum=0, maximum=12, value=5, specialValueText="No roll number")
        self.sets = QComboBox()
        self.sets.addItems(SETS)
        self.sets.setCurrentIndex(3)  # A to D
        form = QFormLayout()
        form.addRow("Sheet name", self.name)
        form.addRow("Number of questions", self.questions)
        form.addRow("Options per question", self.options)
        form.addRow("Roll number digits", self.roll)
        form.addRow("Question paper sets", self.sets)

        self.sections = QTableWidget(0, len(SECTION_COLUMNS))
        self.sections.setHorizontalHeaderLabels(SECTION_COLUMNS)
        self.sections.verticalHeader().hide()
        self.sections.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sections.itemChanged.connect(self.changed)
        add = QPushButton("Add section")
        add.clicked.connect(self.add_section)
        remove = QPushButton("Remove section")
        remove.clicked.connect(self.remove_section)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()

        self.error = QLabel(objectName="error", wordWrap=True)
        self.summary = QLabel(objectName="muted", wordWrap=True)
        save = QPushButton("Save template", objectName="primary")
        save.setToolTip("Saves the sheet so New exam… on the Exams page can use it")
        save.clicked.connect(self.save_template)
        pdf = QPushButton("Save PDF to print…")
        pdf.clicked.connect(self.save_pdf)
        actions = QHBoxLayout()
        actions.addWidget(save)
        actions.addWidget(pdf)

        choices_card, choices = card("1. Choose what the sheet has")
        choices.addLayout(form)
        sections_card, sections = card("2. Sections (optional): each starts a new column, with its own marks")
        sections.addWidget(self.sections, 1)
        sections.addLayout(buttons)
        save_card, save_layout = card("3. Save")
        save_layout.addWidget(self.summary)
        save_layout.addWidget(self.error)
        save_layout.addLayout(actions)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        for w in (choices_card, sections_card, save_card):
            side_layout.addWidget(w)
        side_layout.setStretch(1, 1)
        side.setMaximumWidth(460)

        self.preview = QLabel(alignment=Qt.AlignCenter)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(self.preview)
        preview_card, preview_layout = card("Preview")
        preview_layout.addWidget(scroll, 1)

        body = QHBoxLayout()
        body.addWidget(side)
        body.addWidget(preview_card, 1)
        layout_ = QVBoxLayout(self)
        layout_.setContentsMargins(0, 0, 0, 0)
        layout_.addLayout(body, 1)

        for w in (self.questions, self.options, self.roll):
            w.valueChanged.connect(self.changed)
        self.sets.currentIndexChanged.connect(self.changed)
        self.name.textChanged.connect(self.changed)
        self.update_preview()

    # -- choices ----------------------------------------------------------------------------------------

    def changed(self, *_):
        self.timer.start()

    def add_section(self):
        n = self.sections.rowCount()
        self.sections.blockSignals(True)
        self.sections.insertRow(n)
        # The first section takes every question; later ones start at 10 and add to the total.
        for col, value in enumerate([f"Section {n + 1}", "10" if n else str(self.questions.value()), "1", "0"]):
            self.sections.setItem(n, col, QTableWidgetItem(value))
        self.sections.blockSignals(False)
        self.changed()

    def remove_section(self):
        row = self.sections.currentRow()
        self.sections.removeRow(row if row >= 0 else self.sections.rowCount() - 1)
        self.changed()

    def read_sections(self) -> list[SheetSection]:
        out = []
        for r in range(self.sections.rowCount()):
            text = [(self.sections.item(r, c).text() if self.sections.item(r, c) else "").strip()
                    for c in range(len(SECTION_COLUMNS))]
            try:
                out.append(SheetSection(text[0], int(text[1]), float(text[2] or 0), float(text[3] or 0)))
            except ValueError:
                raise ValueError(f"section row {r + 1}: questions must be a whole number and marks numbers") from None
        return out

    def spec(self) -> SheetSpec:
        sections = self.read_sections()
        if sections:  # the sections decide how many questions there are
            self.questions.blockSignals(True)
            self.questions.setValue(min(max(sum(s.questions for s in sections), 1), self.questions.maximum()))
            self.questions.blockSignals(False)
        self.questions.setEnabled(not sections)
        return SheetSpec(self.name.text(), sum(s.questions for s in sections) if sections else self.questions.value(),
                         self.options.value(), self.roll.value(), self.sets.currentIndex() and self.sets.currentIndex() + 1,
                         sections)

    def update_preview(self):
        try:
            self.template = layout(self.spec())
        except ValueError as e:
            self.template = None
            self.error.setText(str(e))
            return
        self.error.clear()
        t = self.template
        size = "x".join(f"{v:g}" for v in t["bubble_mm"])
        self.summary.setText(f"{self.questions.value()} questions in {sum(g['kind'] == 'questions' for g in t['grids'])} "
                             f"columns, bubbles {size} mm, A4.")
        page = render(t, dpi=60)
        image = QImage(page.data, page.shape[1], page.shape[0], page.strides[0], QImage.Format_BGR888).copy()
        self.preview.setPixmap(QPixmap.fromImage(image))

    # -- saving -----------------------------------------------------------------------------------------

    def _ready(self) -> dict | None:
        self.timer.stop()
        self.update_preview()
        if self.template is None:
            QMessageBox.warning(self, "Can't save yet", self.error.text())
        return self.template

    def save_template(self):
        t = self._ready()
        if t is None:
            return
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in t["name"]).strip() or "sheet"
        path = USER_TEMPLATES / f"{safe}.json"
        if path.exists() and QMessageBox.question(
                self, "Replace template", f"A template called “{t['name']}” already exists. Replace it? Exams already "
                "made with it keep their own copy.", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            USER_TEMPLATES.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(t, indent=2), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save", str(e))
            return
        self.saved.emit(str(path))
        QMessageBox.information(self, "Template saved", f"Saved “{t['name']}”. On the Exams page, New exam… and "
                                "Choose… lists it. Print the sheet with Save PDF to print….")

    def save_pdf(self):
        t = self._ready()
        if t is None:
            return
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Save sheet PDF", str(docs / f"{t['name']}.pdf"), "PDF (*.pdf)")
        if not path:
            return
        try:
            write_pdf(t, path)
        except OSError as e:  # e.g. the PDF is open in a viewer
            QMessageBox.warning(self, "Couldn't save", f"{path}\n\n{e}")
            return
        QMessageBox.information(self, "PDF saved", f"Saved {path}.\n\nPrint it at actual size (100%, not “fit to "
                                "page”) so the bubbles land where the template expects them.")
