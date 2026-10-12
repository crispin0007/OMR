"""Exams page: create exams and open one. Each exam keeps its own template, key, marks, students and sheets.

Back up copies every exam into one file; Restore adds the exams in such a file, on this PC or a new one.
"""

import sqlite3
from datetime import date
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from omr_core.store import Store

from .help import steps_html
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
        backup = QPushButton("Back up…", toolTip="Save every exam, with its sheets, corrections and students, "
                             "in one file to keep safe or take to another PC")
        backup.clicked.connect(self.backup)
        restore = QPushButton("Restore…", toolTip="Add the exams in a backup file; exams already here stay as they are")
        restore.clicked.connect(self.restore)
        top = QHBoxLayout()
        top.addWidget(QLabel("Exams", objectName="title"))
        top.addStretch()
        top.addWidget(backup)
        top.addWidget(restore)
        top.addWidget(new)
        self.note = QLabel(objectName="muted")
        self.start = QLabel(f"<h3>Getting started</h3>{steps_html()}", objectName="card", wordWrap=True,
                            textFormat=Qt.RichText)
        self.start.setContentsMargins(20, 12, 20, 12)
        self.start.setMaximumWidth(760)
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
        layout.addWidget(self.start, 0, Qt.AlignTop)
        layout.addStretch()
        self.refresh()

    def refresh(self, open_id: int | None = ...):
        if open_id is not ...:
            self.open_id = open_id
        exams = self.store.exams()
        self.note.setText("Click an exam to open it: scan, check, set the key and marks, see results and print its "
                          "sheet. Everything is saved as you work."
                          if exams else "Create an exam to start: New exam walks you through it and makes its sheet.")
        self.table.setVisible(bool(exams))
        self.start.setVisible(not exams)  # first run: what to do, in order
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

    def backup(self):
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Back up every exam", str(docs / f"OMR backup {date.today()}.db"),
                                              "OMR backup (*.db)")
        if not path:
            return
        try:
            self.store.backup(path)
        except (OSError, sqlite3.Error) as e:
            QMessageBox.warning(self, "Couldn't back up", f"{path}\n\n{e}")
            return
        QMessageBox.information(self, "Backed up", f"Every exam is saved in {path}.\n\nKeep it on a USB drive or "
                                "another PC; Restore… there brings the exams back.")

    def restore(self):
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getOpenFileName(self, "Restore exams from a backup", docs, "OMR backup (*.db)")
        if not path:
            return
        try:
            restored, skipped = self.store.restore(path)
        except sqlite3.Error as e:
            QMessageBox.warning(self, "Can't restore that file", f"{path}\n\nIt isn't an OMR backup ({e}).")
            return
        except OSError as e:
            QMessageBox.warning(self, "Can't restore that file", f"{path}\n\n{e}")
            return
        self.refresh()
        lines = [f"Restored {', '.join(restored)}." if restored else "No new exams in it."]
        if skipped:
            lines.append(f"Already here, left as they are: {', '.join(skipped)}.")
        QMessageBox.information(self, "Restore", "\n\n".join(lines))
