"""Exams page: create exams and open one. Each exam keeps its own template, key, marks, students and sheets."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from omr_core.store import Store

from .new_exam import TEMPLATES, USER_TEMPLATES, NewExamWizard  # noqa: F401  (TEMPLATES is used by window.py)

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
                          if exams else "Create an exam to start: New exam walks you through it and makes its sheet.")
        self.table.setRowCount(len(exams))
        for row, (id_, name, created, pages, students) in enumerate(exams):
            for col, text in enumerate((name, created.replace("T", "  "), str(pages), str(students or ""),
                                        "open now" if id_ == self.open_id else "")):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, id_)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()

    def new_exam(self):
        wizard = NewExamWizard(self, self.store)
        if wizard.exec():
            self.opened.emit(wizard.exam_id)
