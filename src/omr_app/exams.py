"""Exams page: create exams and open one. Each exam keeps its own template, key, marks, students and sheets."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from omr_core.store import Store
from omr_core.template import load

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"  # the repo's templates, in a source checkout
# Templates made in the sheet designer: %LOCALAPPDATA%\OMR\templates on Windows, next to the database.
USER_TEMPLATES = Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / "OMR" / "templates"


class NewExamDialog(QDialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("New exam")
        self.name = QLineEdit(placeholderText="e.g. Mock test 3, Class 10")
        default = TEMPLATES / "test-100.json"
        self.template_path = str(default) if default.exists() else ""
        self.template_label = QLabel(objectName="muted")
        choose = QPushButton("Choose…")
        choose.clicked.connect(self.choose)
        row = QHBoxLayout()
        row.addWidget(self.template_label, 1)
        row.addWidget(choose)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow("Exam name", self.name)
        form.addRow("Sheet template", row)
        form.addRow(buttons)
        self.setMinimumWidth(460)
        self._show_template()

    def choose(self):
        start = USER_TEMPLATES if USER_TEMPLATES.is_dir() and any(USER_TEMPLATES.glob("*.json")) else TEMPLATES
        path, _ = QFileDialog.getOpenFileName(self, "Choose template", str(start), "Templates (*.json)")
        if path:
            self.template_path = path
            self._show_template()

    def _show_template(self):
        try:
            self.template_label.setText(load(self.template_path).name if self.template_path else "None chosen")
        except (OSError, ValueError) as e:
            self.template_label.setText(f"Can't use it: {e}")


class ExamsPage(QWidget):
    """Every exam; click one to open its page."""

    opened = Signal(object)  # exam id

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.open_id: int | None = None
        new = QPushButton("New exam…", objectName="primary")
        new.clicked.connect(self.new_exam)
        top = QHBoxLayout()
        top.addWidget(QLabel("Exams", objectName="title"))
        top.addStretch()
        top.addWidget(new)
        self.note = QLabel(objectName="muted")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Exam", "Created", "Sheets", "Students", ""])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(lambda row, _: self.opened.emit(self.table.item(row, 0).data(Qt.UserRole)))
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.note)
        layout.addWidget(self.table, 1)
        self.refresh()

    def refresh(self, open_id: int | None = ...):
        if open_id is not ...:
            self.open_id = open_id
        exams = self.store.exams()
        self.note.setText("Click an exam to open it: scan, check, set the key and marks, see results and print its "
                          "sheet. Everything is saved as you work."
                          if exams else "Create an exam to start: give it a name and pick the sheet template.")
        self.table.setRowCount(len(exams))
        for row, (id_, name, created, pages, students) in enumerate(exams):
            for col, text in enumerate((name, created.replace("T", "  "), str(pages), str(students or ""),
                                        "open now" if id_ == self.open_id else "")):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, id_)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()

    def new_exam(self):
        dialog = NewExamDialog(self)
        if not dialog.exec():
            return
        try:
            text = Path(dialog.template_path).read_text(encoding="utf-8")
            exam_id = self.store.create_exam(dialog.name.text(), text)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Can't create the exam", str(e))
            return
        self.opened.emit(exam_id)
