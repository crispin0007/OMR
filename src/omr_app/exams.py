"""Exams page: create, open and delete exams. Each exam keeps its own template, key, marks and sheets."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from omr_core.store import Store
from omr_core.students import read_students
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
    opened = Signal(object)  # exam id, or None when the open exam was deleted
    students_changed = Signal(int)  # exam id

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.open_id: int | None = None
        new = QPushButton("New exam…", objectName="primary")
        new.clicked.connect(self.new_exam)
        self.open_button = QPushButton("Open")
        self.open_button.clicked.connect(lambda: self.opened.emit(self.selected()))
        self.students_button = QPushButton("Import students…")
        self.students_button.setToolTip("An Excel file with roll number, name and (optionally) class columns")
        self.students_button.clicked.connect(self.import_students)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.clicked.connect(self.delete_exam)
        top = QHBoxLayout()
        top.addWidget(QLabel("Exams", objectName="title"))
        top.addStretch()
        for b in (new, self.open_button, self.students_button, self.delete_button):
            top.addWidget(b)
        self.note = QLabel(objectName="muted")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Exam", "Created", "Sheets", "Students", ""])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(lambda *_: self.opened.emit(self.selected()))
        self.table.itemSelectionChanged.connect(self._enable)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.note)
        layout.addWidget(self.table, 1)
        self.refresh()

    def selected(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def _enable(self):
        for b in (self.open_button, self.students_button, self.delete_button):
            b.setEnabled(self.selected() is not None)

    def refresh(self, open_id: int | None = ...):
        if open_id is not ...:
            self.open_id = open_id
        exams = self.store.exams()
        self.note.setText("Double-click an exam to open it. Everything is saved as you work."
                          if exams else "Create an exam to start: give it a name and pick the sheet template.")
        self.table.setRowCount(len(exams))
        for row, (id_, name, created, pages, students) in enumerate(exams):
            for col, text in enumerate((name, created.replace("T", "  "), str(pages), str(students or ""),
                                        "open now" if id_ == self.open_id else "")):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, id_)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self._enable()

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

    def import_students(self):
        exam_id = self.selected()
        if exam_id is None:
            return
        exam = self.store.exam(exam_id)
        roll = next((g for g in exam.template.grids if g.kind == "roll_number"), None)
        if roll is None:
            QMessageBox.warning(self, "No roll number", "This exam's sheet has no roll number grid to match students by.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import students", "", "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            students, problems = read_students(path, roll.cols)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Can't import students", str(e))
            return
        if not students:
            QMessageBox.warning(self, "Can't import students", "No usable rows.\n\n" + "\n".join(problems[:30]))
            return
        replacing = self.store.students(exam_id)
        if replacing and QMessageBox.question(
                self, "Replace student list", f"“{exam.name}” already has {len(replacing)} students. Replace them "
                f"with the {len(students)} in this file?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.store.set_students(exam_id, students)
        self.refresh()
        self.students_changed.emit(exam_id)
        text = f"Imported {len(students)} student{'s' if len(students) != 1 else ''} into “{exam.name}”."
        if problems:
            more = f"\n…and {len(problems) - 30} more" if len(problems) > 30 else ""
            text += f"\n\nSkipped {len(problems)} rows:\n" + "\n".join(problems[:30]) + more
        QMessageBox.information(self, "Students imported", text)

    def delete_exam(self):
        exam_id = self.selected()
        if exam_id is None:
            return
        name = self.store.exam(exam_id).name
        sure = QMessageBox.question(
            self, "Delete exam", f"Delete “{name}” and every sheet read for it? This can't be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if sure != QMessageBox.Yes:
            return
        self.store.delete_exam(exam_id)
        if exam_id == self.open_id:
            self.opened.emit(None)
        self.refresh()
