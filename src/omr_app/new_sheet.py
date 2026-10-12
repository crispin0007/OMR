"""New sheet page: make an answer sheet by choosing questions, options, roll number, sets and sections (US6).

The colour, the heading, a logo and the instructions are yours to choose too.
The sheet is drawn for you and previewed as you change the choices. Save it as a
template for exams, and save the PDF to print.
"""

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QColorDialog, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from omr_core.sheet import (DEFAULT_HEADING, DEFAULT_INSTRUCTIONS, MAX_ROLL_DIGITS, SheetSection, SheetSpec,
                            layout, logo_jpeg, render, write_pdf)

from .dashboard import card
from .exams import USER_TEMPLATES

SETS = ["No sets"] + [f"{n} sets (A to {'ABCDEFGH'[n - 1]})" for n in range(2, 9)]
SECTION_COLUMNS = ["Section", "Questions", "Correct", "Wrong"]
COLOURS = [("Pink", "#e4007c"), ("Red", "#d32f2f"), ("Orange", "#ef6c00"), ("Green", "#2e7d32"),
           ("Teal", "#00838f"), ("Blue", "#1565c0"), ("Purple", "#6a1b9a"), ("Black", "#000000")]
OTHER_COLOUR = "Other colour…"


class NewSheetPage(QWidget):
    saved = Signal(str)  # path of a saved template

    def __init__(self):
        super().__init__()
        self.template: dict | None = None
        self.logo = b""
        self.timer = QTimer(self, singleShot=True, interval=250)  # redraw once typing pauses
        self.timer.timeout.connect(self.update_preview)

        self.name = QLineEdit("Answer sheet")
        self.questions = QSpinBox(minimum=1, maximum=300, value=100)
        self.options = QSpinBox(minimum=2, maximum=8, value=4)
        self.roll = QSpinBox(minimum=0, maximum=MAX_ROLL_DIGITS, value=5, specialValueText="No roll number")
        self.sets = QComboBox()
        self.sets.addItems(SETS)
        self.sets.setCurrentIndex(3)  # A to D
        form = QFormLayout()
        form.addRow("Sheet name", self.name)
        form.addRow("Number of questions", self.questions)
        form.addRow("Options per question", self.options)
        form.addRow("Roll number digits", self.roll)
        form.addRow("Question paper sets", self.sets)

        self.heading = QLineEdit(DEFAULT_HEADING)
        self.colour = QComboBox()
        for name, value in COLOURS:
            self._add_colour(name, value)
        self.colour.addItem(OTHER_COLOUR)
        self.colour.activated.connect(self.colour_chosen)
        self.logo_label = QLabel("No logo", objectName="muted")
        logo = QPushButton("Choose logo…")
        logo.clicked.connect(self.choose_logo)
        no_logo = QPushButton("Remove")
        no_logo.clicked.connect(self.remove_logo)
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_label, 1)
        logo_row.addWidget(logo)
        logo_row.addWidget(no_logo)
        self.instructions = QPlainTextEdit("\n".join(DEFAULT_INSTRUCTIONS))
        self.instructions.setToolTip("One instruction per line; they are numbered for you")
        self.instructions.setMinimumHeight(110)
        look = QFormLayout()
        look.addRow("Heading", self.heading)
        look.addRow("Colour", self.colour)
        look.addRow("Logo", logo_row)
        look.addRow("Instructions", self.instructions)

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
        look_card, look_layout = card("2. Heading, colour, logo and instructions")
        look_layout.addLayout(look)
        sections_card, sections = card("3. Sections (optional): each starts a new column, with its own marks")
        sections.addWidget(self.sections, 1)
        sections.addLayout(buttons)
        self.sections.setMinimumHeight(110)
        save_card, save_layout = card("4. Save")
        save_layout.addWidget(self.summary)
        save_layout.addWidget(self.error)
        save_layout.addLayout(actions)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        for w in (choices_card, look_card, sections_card, save_card):
            side_layout.addWidget(w)
        side_scroll = QScrollArea(widgetResizable=True)
        side_scroll.setWidget(side)
        side_scroll.setFrameShape(QScrollArea.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_scroll.setMaximumWidth(480)

        self.preview = QLabel(alignment=Qt.AlignCenter)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(self.preview)
        preview_card, preview_layout = card("Preview")
        preview_layout.addWidget(scroll, 1)

        body = QHBoxLayout()
        body.addWidget(side_scroll)
        body.addWidget(preview_card, 1)
        layout_ = QVBoxLayout(self)
        layout_.setContentsMargins(0, 0, 0, 0)
        layout_.addLayout(body, 1)

        for w in (self.questions, self.options, self.roll):
            w.valueChanged.connect(self.changed)
        self.sets.currentIndexChanged.connect(self.changed)
        self.name.textChanged.connect(self.changed)
        self.heading.textChanged.connect(self.changed)
        self.instructions.textChanged.connect(self.changed)
        self.update_preview()

    # -- choices ----------------------------------------------------------------------------------------

    def changed(self, *_):
        self.timer.start()

    def _add_colour(self, name: str, value: str):
        swatch = QPixmap(16, 16)
        swatch.fill(QColor(value))
        self.colour.insertItem(max(self.colour.count() - (self.colour.findText(OTHER_COLOUR) >= 0), 0),
                               QIcon(swatch), name, value)

    def colour_chosen(self, index: int):
        if self.colour.itemText(index) == OTHER_COLOUR:
            chosen = QColorDialog.getColor(QColor(self.colour.itemData(0)), self, "Sheet colour")
            if not chosen.isValid():
                self.colour.setCurrentIndex(0)
                return
            value = chosen.name()
            if self.colour.findData(value) < 0:
                self._add_colour(value, value)
            self.colour.setCurrentIndex(self.colour.findData(value))
        self.changed()

    def choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Logo", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            self.logo = logo_jpeg(Path(path).read_bytes())
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Couldn't use that logo", str(e))
            return
        self.logo_label.setText(Path(path).name)
        self.changed()

    def remove_logo(self):
        self.logo = b""
        self.logo_label.setText("No logo")
        self.changed()

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
                         sections, self.colour.currentData() or COLOURS[0][1], self.heading.text(),
                         self.instructions.toPlainText().splitlines(), self.logo)

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
        page = render(t, dpi=80)
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
