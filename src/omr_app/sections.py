"""Sections dialog: give a range of questions its own name and marks, e.g. Physics 1 to 50, 4 right, -1 wrong."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from omr_core.grading import Section, check_sections

COLUMNS = ["Section", "From question", "To question", "Correct", "Minus for wrong", "Minus for blank", "Partial marks"]


class SectionsDialog(QDialog):
    def __init__(self, parent: QWidget, sections: list[Section], questions: list[int], marks: tuple[float, float, float]):
        super().__init__(parent)
        self.setWindowTitle("Sections")
        self.questions = questions
        self.marks = marks
        self.sections: list[Section] = list(sections)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for s in sections:
            self._add_row([s.name, s.first, s.last, s.correct, -s.wrong or 0.0, -s.blank or 0.0], s.partial)
        add = QPushButton("Add section")
        add.clicked.connect(self.add)
        remove = QPushButton("Remove section")
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        self.error = QLabel(objectName="error", wordWrap=True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Each section's questions get its own marks; questions in no section use the exam's "
                                "marks. Results show a score per section.", objectName="muted", wordWrap=True))
        layout.addWidget(self.table, 1)
        layout.addLayout(row)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.resize(720, 360)

    def _add_row(self, values: list, partial: bool = False):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for col, v in enumerate(values):
            self.table.setItem(r, col, QTableWidgetItem(f"{v:g}" if isinstance(v, float) else str(v)))
        item = QTableWidgetItem("")
        item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        item.setCheckState(Qt.Checked if partial else Qt.Unchecked)
        item.setToolTip("Part of the marks for some, but not all, of a multi-correct answer")
        self.table.setItem(r, len(values), item)

    def add(self):
        """A new row starting after the last section, to the end of the sheet."""
        rows = self.read_rows(check=False)
        start = max((s.last for s in rows), default=self.questions[0] - 1) + 1
        start = next((q for q in self.questions if q >= start), self.questions[-1])
        correct, wrong, blank = self.marks
        self._add_row([f"Section {len(rows) + 1}", start, self.questions[-1], correct, -wrong or 0.0, -blank or 0.0])

    def read_rows(self, check: bool = True) -> list[Section]:
        out = []
        for r in range(self.table.rowCount()):
            text = [(self.table.item(r, c).text() if self.table.item(r, c) else "").strip() for c in range(6)]
            partial = self.table.item(r, 6) is not None and self.table.item(r, 6).checkState() == Qt.Checked
            try:
                correct, wrong, blank = (float(t or 0) for t in text[3:])
                # marks taken off, so 1 and -1 both take off a mark
                out.append(Section(text[0], int(text[1]), int(text[2]), correct, -abs(wrong), -abs(blank), partial))
            except ValueError:
                if check:
                    raise ValueError(f"row {r + 1}: questions must be whole numbers and marks numbers") from None
        if check:
            check_sections(out, self.questions)
        return out

    def accept(self):
        try:
            self.sections = self.read_rows()
        except ValueError as e:
            self.error.setText(str(e))
            return
        super().accept()
