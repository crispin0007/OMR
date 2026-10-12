"""Exam page: one exam opened from the Exams list, with a tab for each part of it.

Scanning, the sheets read, review, the answer key, marks and sections,
students, results, the printable sheet and the exam's settings all live here.
"""

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from omr_core.sheet import render, write_pdf
from omr_core.students import read_students


class ExamPage(QWidget):
    back = Signal()

    def __init__(self, check, tabs: list[tuple[str, QWidget]]):
        super().__init__()
        self.check = check
        self.names = [name for name, _ in tabs]
        back = QPushButton("←  All exams")
        back.clicked.connect(self.back.emit)
        self.title = QLabel(objectName="title")
        self.about = QLabel(objectName="muted")
        top = QHBoxLayout()
        top.addWidget(back)
        top.addSpacing(12)
        top.addWidget(self.title)
        top.addSpacing(12)
        top.addWidget(self.about, 1)
        self.tabs = QTabWidget()
        for name, widget in tabs:
            self.tabs.addTab(widget, name)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.tabs, 1)
        check.changed.connect(self.refresh)

    def show_tab(self, name: str):
        self.tabs.setCurrentIndex(self.names.index(name))

    def refresh(self):
        exam = self.check.exam
        self.title.setText(exam.name if exam else "")
        self.about.setText(f"{exam.template.name}, {len(self.check.questions)} questions  ·  "
                           f"{len(self.check.sheets)} sheets read" if exam else "")


class StudentsTab(QWidget):
    changed = Signal()  # a new student list was imported

    def __init__(self, check):
        super().__init__()
        self.check = check
        self.note = QLabel(objectName="muted", wordWrap=True)
        self.import_button = QPushButton("Import students…", objectName="primary")
        self.import_button.setToolTip("An Excel file with roll number, name and (optionally) class columns")
        self.import_button.clicked.connect(self.import_students)
        top = QHBoxLayout()
        top.addWidget(self.note, 1)
        top.addWidget(self.import_button)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Roll number", "Name", "Class"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)

    def refresh(self):
        students = sorted(self.check.students.values(), key=lambda s: s.roll_number)
        self.note.setText(f"{len(students)} students. Their names show on results and scorecards." if students else
                          "No students yet. Import an Excel list to show names on results and scorecards.")
        self.table.setRowCount(len(students))
        for row, s in enumerate(students):
            for col, text in enumerate((s.roll_number, s.name, s.class_name)):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.import_button.setEnabled(self.check.exam is not None)

    def import_students(self):
        exam = self.check.exam
        roll = next((g for g in exam.template.grids if g.kind == "roll_number"), None)
        if roll is None and exam.template.barcode is None:
            QMessageBox.warning(self, "No roll number", "This exam's sheet has no roll number grid or barcode to match "
                                "students by.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import students", "", "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            students, problems = read_students(path, roll.cols if roll else None)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Can't import students", str(e))
            return
        if not students:
            QMessageBox.warning(self, "Can't import students", "No usable rows.\n\n" + "\n".join(problems[:30]))
            return
        replacing = self.check.store.students(exam.id)
        if replacing and QMessageBox.question(
                self, "Replace student list", f"“{exam.name}” already has {len(replacing)} students. Replace them "
                f"with the {len(students)} in this file?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.check.store.set_students(exam.id, students)
        self.changed.emit()
        self.refresh()
        text = f"Imported {len(students)} student{'s' if len(students) != 1 else ''} into “{exam.name}”."
        if problems:
            more = f"\n…and {len(problems) - 30} more" if len(problems) > 30 else ""
            text += f"\n\nSkipped {len(problems)} rows:\n" + "\n".join(problems[:30]) + more
        QMessageBox.information(self, "Students imported", text)


class PrintSheet(QWidget):
    """The exam's own sheet to print, when it was made on the New sheet tab."""

    def __init__(self, check):
        super().__init__()
        self.check = check
        self.template: dict | None = None
        self.note = QLabel(objectName="muted", wordWrap=True)
        self.save = QPushButton("Save PDF to print…", objectName="primary")
        self.save.clicked.connect(self.save_pdf)
        top = QHBoxLayout()
        top.addWidget(self.note, 1)
        top.addWidget(self.save)
        self.preview = QLabel(alignment=Qt.AlignCenter)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(self.preview)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(scroll, 1)

    def refresh(self):
        exam = self.check.exam
        d = json.loads(exam.template_json) if exam else {}
        self.template = d if "print" in d else None  # only sheets made on New sheet carry what to print
        self.save.setEnabled(self.template is not None)
        self.preview.clear()
        if exam is None:
            self.note.setText("")
        elif self.template is None:
            self.note.setText(f"“{exam.template.name}” is a sheet you print yourself, mapped from a scan. Print it "
                              "as you always do; this exam reads it.")
        else:
            self.note.setText("This exam's sheet. Print it at actual size (100%, not “fit to page”).")
            page = render(self.template, dpi=80)
            image = QImage(page.data, page.shape[1], page.shape[0], page.strides[0], QImage.Format_BGR888).copy()
            self.preview.setPixmap(QPixmap.fromImage(image))

    def save_pdf(self):
        exam = self.check.exam
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Save sheet PDF", str(docs / f"{exam.name} sheet.pdf"),
                                              "PDF (*.pdf)")
        if not path:
            return
        try:
            write_pdf(self.template, path)
        except OSError as e:  # e.g. the PDF is open in a viewer
            QMessageBox.warning(self, "Couldn't save", f"{path}\n\n{e}")
            return
        self.window().statusBar().showMessage(f"Saved {path}", 5000)


class ExamSettings(QWidget):
    renamed = Signal()
    deleted = Signal()

    def __init__(self, check):
        super().__init__()
        self.check = check
        self.name = QLineEdit()
        rename = QPushButton("Rename")
        rename.clicked.connect(self.rename)
        row = QHBoxLayout()
        row.addWidget(QLabel("Exam name"))
        row.addWidget(self.name, 1)
        row.addWidget(rename)
        self.about = QLabel(objectName="muted", wordWrap=True)
        delete = QPushButton("Delete exam…")
        delete.clicked.connect(self.delete)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.about)
        layout.addSpacing(24)
        layout.addWidget(QLabel("Deleting removes the exam and every sheet read for it.", objectName="muted"))
        layout.addWidget(delete, 0, Qt.AlignLeft)
        layout.addStretch()

    def refresh(self):
        exam = self.check.exam
        self.name.setText(exam.name if exam else "")
        self.about.setText(f"Sheet: {exam.template.name}, {len(self.check.questions)} questions.  Created "
                           f"{exam.created.replace('T', ' ')}." if exam else "")

    def rename(self):
        try:
            self.check.store.rename_exam(self.check.exam.id, self.name.text())
        except ValueError as e:
            QMessageBox.warning(self, "Can't rename", str(e))
            return
        self.renamed.emit()

    def delete(self):
        exam = self.check.exam
        if QMessageBox.question(self, "Delete exam", f"Delete “{exam.name}” and every sheet read for it? This can't "
                                "be undone.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.check.store.delete_exam(exam.id)
        self.deleted.emit()
