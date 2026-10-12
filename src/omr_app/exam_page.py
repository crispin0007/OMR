"""Exam page: one exam opened from the Exams list, with a tab for each part of it.

Scanning, the sheets read, review, the answer key, marks and sections,
students, results, the printable sheet and the exam's settings all live here.
"""

import csv
import io
import json
from pathlib import Path

from PySide6.QtCore import QDate, QStandardPaths, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from omr_core.reader import read_or_reason
from omr_core.sheet import PAPERS, render, write_pdf
from omr_core.sources import read_pages
from omr_core.students import absent, read_students
from omr_core.template import parse

from .new_exam import TEMPLATES, USER_TEMPLATES
from .theme import tokens


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
        self.about.setText("  ·  ".join([*when(exam), f"{len(self.check.questions)} questions",
                                         f"{len(self.check.sheets)} sheets read"]) if exam else "")


def when(exam) -> list[str]:
    """The exam's class, date, time and duration, as far as they were given."""
    d = exam.details
    out = [d["class"]] if d.get("class") else []
    if d.get("date"):
        day = QDate.fromString(d["date"], Qt.ISODate).toString("d MMM yyyy")
        out.append(f"{day} at {d['time']}" if d.get("time") else day)
    if d.get("minutes"):
        out.append(f"{d['minutes']} minutes")
    return out


class StudentsTab(QWidget):
    changed = Signal()  # a new student list was imported

    def __init__(self, check):
        super().__init__()
        self.check = check
        self.note = QLabel(objectName="muted", wordWrap=True)
        self.import_button = QPushButton("Import students…", objectName="primary")
        self.import_button.setToolTip("An Excel file with roll number, name and (optionally) class columns")
        self.import_button.clicked.connect(self.import_students)
        self.absent_only = QCheckBox("Show only absent")
        self.absent_only.toggled.connect(lambda _: self.refresh())
        self.save_absent = QPushButton("Save absent list…")
        self.save_absent.setToolTip("Students on the list with no sheet read, as a CSV for Excel")
        self.save_absent.clicked.connect(self.save_absent_list)
        top = QHBoxLayout()
        top.addWidget(self.note, 1)
        top.addWidget(self.absent_only)
        top.addWidget(self.save_absent)
        top.addWidget(self.import_button)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Roll number", "Name", "Class", "Sheet"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)

    def absentees(self) -> list:
        c = self.check
        return absent(c.students, {s.result.roll_number for s in c.sheets if s.result})

    def showEvent(self, e):
        self.refresh()  # sheets read since
        super().showEvent(e)

    def refresh(self):
        c = self.check
        missing = self.absentees()
        away = {s.roll_number for s in missing}
        students = missing if self.absent_only.isChecked() else sorted(c.students.values(), key=lambda s: s.roll_number)
        unreadable = sum(s.result is None for s in c.sheets)
        note = (f"{len(c.students)} students, {len(away)} absent (no sheet read). Their names show on results and "
                "scorecards." if c.students else
                "No students yet. Import an Excel list to show names on results and scorecards, and see who is absent.")
        if away and unreadable:
            note += f" {unreadable} pages couldn't be read; some of these students may be on them."
        self.note.setText(note)
        warn = QColor(tokens()["warn"])
        self.table.setRowCount(len(students))
        for row, s in enumerate(students):
            for col, text in enumerate((s.roll_number, s.name, s.class_name,
                                        "Absent" if s.roll_number in away else "Read")):
                item = QTableWidgetItem(text)
                if col == 3 and s.roll_number in away:
                    item.setForeground(warn)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.import_button.setEnabled(c.exam is not None)
        self.save_absent.setEnabled(bool(away))
        self.absent_only.setEnabled(bool(c.students))

    def save_absent_list(self):
        exam = self.check.exam
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Save absent list", str(docs / f"{exam.name} absent.csv"),
                                              "CSV (*.csv)")
        if not path:
            return
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["Roll number", "Name", "Class"])
        w.writerows((s.roll_number, s.name, s.class_name) for s in self.absentees())
        try:
            Path(path).write_text(out.getvalue(), encoding="utf-8-sig")  # the BOM makes Excel read it as UTF-8
        except OSError as e:  # e.g. the file is open in Excel
            QMessageBox.warning(self, "Couldn't save", f"{path}\n\n{e}")
            return
        self.window().statusBar().showMessage(f"Saved {path}", 5000)

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
    """The exam's own sheet to print, when New exam made it."""

    def __init__(self, check):
        super().__init__()
        self.check = check
        self.template: dict | None = None
        self.note = QLabel(objectName="muted", wordWrap=True)
        self.paper = QComboBox()
        self.paper.addItems(list(PAPERS))
        self.paper.setToolTip("The sheet is scaled to fit the paper; it reads the same on any of them")
        self.paper.currentTextChanged.connect(lambda _: self.refresh())
        self.save = QPushButton("Save PDF to print…", objectName="primary")
        self.save.clicked.connect(self.save_pdf)
        self.try_print = QPushButton("Check a printed copy…")
        self.try_print.setToolTip("Before printing them all: scan or photograph one printed sheet, blank or with a "
                                  "few bubbles filled, to see that it reads")
        self.try_print.clicked.connect(self.check_print)
        top = QHBoxLayout()
        top.addWidget(self.note, 1)
        top.addWidget(QLabel("Paper"))
        top.addWidget(self.paper)
        top.addWidget(self.try_print)
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
        self.template = d if "print" in d else None  # only sheets New exam made carry what to print
        for w in (self.save, self.paper):
            w.setEnabled(self.template is not None)
        self.try_print.setEnabled(exam is not None)
        self.preview.clear()
        if exam is None:
            self.note.setText("")
        elif self.template is None:
            self.note.setText(f"“{exam.template.name}” is a sheet you print yourself, mapped from a scan. Print it "
                              "as you always do; this exam reads it.")
        else:
            self.note.setText("This exam's sheet, ready for any paper size. Keep all four corner circles on the "
                              "paper; scaling or “fit to page” is fine.")
            page = render(self.template, dpi=80, paper=self.paper.currentText())
            image = QImage(page.data, page.shape[1], page.shape[0], page.strides[0], QImage.Format_BGR888).copy()
            self.preview.setPixmap(QPixmap.fromImage(image))

    def check_print(self):
        path, _ = QFileDialog.getOpenFileName(self, "Scan or photo of one printed sheet", "",
                                              "Scans (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if not path:
            return
        try:
            page = next(read_pages(path))
        except (OSError, ValueError, StopIteration) as e:
            QMessageBox.warning(self, "Can't open that file", f"{path}\n\n{e or 'it has no pages'}")
            return
        QMessageBox.information(self, "Printed copy", print_check(page, self.check.exam.template))

    def save_pdf(self):
        exam = self.check.exam
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Save sheet PDF", str(docs / f"{exam.name} sheet.pdf"),
                                              "PDF (*.pdf)")
        if not path:
            return
        try:
            write_pdf(self.template, path, self.paper.currentText())
        except OSError as e:  # e.g. the PDF is open in a viewer
            QMessageBox.warning(self, "Couldn't save", f"{path}\n\n{e}")
            return
        self.window().statusBar().showMessage(f"Saved {path}", 5000)


def print_check(page, template) -> str:
    """What reading one printed copy says about the print: whether it reads, and what it read."""
    result, problem = read_or_reason(page, template)
    if result is None:
        return (f"This copy can't be read: {problem.removeprefix('unreadable: ')}.\n\nCheck that all four corner "
                "circles are on the paper and printed solid black, and that the page is this exam's sheet. Then "
                "print and try again before printing the rest.")
    filled = {q: a for q, a in result.answers.items() if a}
    lines = ["This copy reads: the corner circles and every bubble were found."]
    if filled or result.roll_number.strip("?"):
        lines.append(f"Roll number {result.roll_number or 'none'}, set {result.set_code or 'none'}, "
                     f"{len(filled)} questions answered: "
                     + (", ".join(f"{q} {a}" for q, a in list(filled.items())[:10]) or "none")
                     + (" …" if len(filled) > 10 else "") + ".")
    else:
        lines.append("Every bubble reads empty. Fill a few and try again to see them read.")
    if result.flags:
        lines.append(f"{len(result.flags)} to check, for example {result.flags[0][0]}: {result.flags[0][1]}. "
                     "Faint print or a smudge can cause this; compare the copy with the PDF.")
    return "\n\n".join(lines)


class ExamSettings(QWidget):
    changed = Signal()  # renamed, or a new sheet
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
        change = QPushButton("Change sheet…")
        change.clicked.connect(self.change_sheet)
        delete = QPushButton("Delete exam…")
        delete.clicked.connect(self.delete)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.about)
        layout.addSpacing(24)
        layout.addWidget(QLabel("If students filled a different sheet from this exam's, pick that sheet's template; "
                                "every page is read again with it.", objectName="muted", wordWrap=True))
        layout.addWidget(change, 0, Qt.AlignLeft)
        layout.addSpacing(24)
        layout.addWidget(QLabel("Deleting removes the exam and every sheet read for it.", objectName="muted"))
        layout.addWidget(delete, 0, Qt.AlignLeft)
        layout.addStretch()

    def refresh(self):
        exam = self.check.exam
        self.name.setText(exam.name if exam else "")
        self.about.setText("\n".join([*when(exam), f"Sheet: {exam.template.name}, {len(self.check.questions)} "
                                       f"questions.  Created {exam.created.replace('T', ' ')}."]) if exam else "")

    def rename(self):
        try:
            self.check.store.rename_exam(self.check.exam.id, self.name.text())
        except ValueError as e:
            QMessageBox.warning(self, "Can't rename", str(e))
            return
        self.changed.emit()

    def change_sheet(self):
        start = USER_TEMPLATES if USER_TEMPLATES.is_dir() and any(USER_TEMPLATES.glob("*.json")) else TEMPLATES
        path, _ = QFileDialog.getOpenFileName(self, "Change sheet", str(start), "Templates (*.json)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            t = parse(json.loads(text))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Can't use that template", f"{path}\n\n{e}")
            return
        check = self.check
        if check.sheets and QMessageBox.question(
                self, "Change sheet", f"Read all {len(check.sheets)} pages again with “{t.name}”? Corrections made "
                "on the Review tab are replaced by the new readings (the change log keeps them).",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        pages = check.read_again(t)
        if pages is None:
            return  # stopped: nothing changed
        try:
            check.store.change_sheet(check.exam.id, text, pages)
        except ValueError as e:
            QMessageBox.warning(self, "Can't change the sheet", str(e))
            return
        self.changed.emit()  # reopens the exam with the new sheet
        unreadable = sum(r is None for r, _ in pages.values())
        QMessageBox.information(self, "Sheet changed", f"The exam now uses “{t.name}”. " + (
            f"{len(pages) - unreadable} of {len(pages)} pages read" + (
                f"; {unreadable} can't be read with this sheet and are listed under Scanned sheets."
                if unreadable else ".") if pages else ""))

    def delete(self):
        exam = self.check.exam
        if QMessageBox.question(self, "Delete exam", f"Delete “{exam.name}” and every sheet read for it? This can't "
                                "be undone.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.check.store.delete_exam(exam.id)
        self.deleted.emit()
