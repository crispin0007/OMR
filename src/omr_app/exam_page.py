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
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from omr_core.reader import read_or_reason
from omr_core.sheet import render
from omr_core.sources import read_pages
from omr_core.store import TRASH_DAYS
from omr_core.students import absent, for_sheet, read_students
from omr_core.template import parse

from .institutes import logo_pixmap
from .new_exam import TEMPLATES, USER_TEMPLATES
from .printing import PrintBar
from .theme import tokens


class ExamPage(QWidget):
    back = Signal()
    scan_wanted = Signal()

    def __init__(self, check, tabs: list[tuple[str, QWidget]]):
        super().__init__()
        self.check = check
        self.names = [name for name, _ in tabs]
        back = QPushButton("←  All exams")
        back.clicked.connect(self.back.emit)
        self.title = QLabel(objectName="title")
        self.about = QLabel(objectName="muted")
        self.logo = QLabel()
        top = QHBoxLayout()
        top.addWidget(back)
        top.addSpacing(12)
        top.addWidget(self.logo)
        top.addWidget(self.title)
        top.addSpacing(12)
        top.addWidget(self.about, 1)
        scan = QPushButton("▶  Start scanning", objectName="primary")
        scan.setToolTip("Scan sheets into this exam from the scanner's feeder")
        scan.clicked.connect(self.scan_wanted.emit)
        top.addWidget(scan)
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
        institute = self.check.store.institute_for(exam.id) if exam else None
        self.title.setText(exam.name if exam else "")
        self.about.setText("  ·  ".join([*([institute.name] if institute else []), *when(exam),
                                         f"{len(self.check.questions)} questions",
                                         f"{len(self.check.sheets)} sheets read"]) if exam else "")
        self.logo.setPixmap(logo_pixmap(institute.logo, 32) if institute and institute.logo else QPixmap())
        self.logo.setVisible(bool(institute and institute.logo))


def when(exam) -> list[str]:
    """The exam's class, date, time, duration and test series, as far as they were given."""
    d = exam.details
    out = [d["class"]] if d.get("class") else []
    if d.get("date"):
        day = QDate.fromString(d["date"], Qt.ISODate).toString("d MMM yyyy")
        out.append(f"{day} at {d['time']}" if d.get("time") else day)
    if d.get("minutes"):
        out.append(f"{d['minutes']} minutes")
    if d.get("series"):
        out.append(f"test series {d['series']}")
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
        self.copy_button = QPushButton("Use the list of another exam…")
        self.copy_button.clicked.connect(self.copy_students)
        self.batch_button = QPushButton("Use a batch…", toolTip="Take the list from the student directory, by batch")
        self.batch_button.clicked.connect(self.use_batch)
        top = QHBoxLayout()
        top.addWidget(self.note, 1)
        top.addWidget(self.absent_only)
        top.addWidget(self.save_absent)
        top.addWidget(self.copy_button)
        top.addWidget(self.batch_button)
        top.addWidget(self.import_button)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Roll number", "Name", "Class", "Batch", "Email", "Phone", "Sheet"])
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
            for col, text in enumerate((s.roll_number, s.name, s.class_name, s.batch, s.email, s.phone,
                                        "Absent" if s.roll_number in away else "Read")):
                item = QTableWidgetItem(text)
                if col == 6 and s.roll_number in away:
                    item.setForeground(warn)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.import_button.setEnabled(c.exam is not None)
        self.save_absent.setEnabled(bool(away))
        self.absent_only.setEnabled(bool(c.students))
        self.copy_button.setEnabled(c.exam is not None)
        self.batch_button.setEnabled(c.exam is not None)

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
        if not self._replace(students, "in this file"):
            return
        text = f"Imported {len(students)} student{'s' if len(students) != 1 else ''} into “{exam.name}”."
        if problems:
            more = f"\n…and {len(problems) - 30} more" if len(problems) > 30 else ""
            text += f"\n\nSkipped {len(problems)} rows:\n" + "\n".join(problems[:30]) + more
        QMessageBox.information(self, "Students imported", text)

    def copy_students(self):
        store, exam = self.check.store, self.check.exam
        others = [(i, name, n) for i, name, _, _, n in store.exams() if n and i != exam.id]
        if not others:
            QMessageBox.information(self, "No other lists", "No other exam has a student list yet. Import one here.")
            return
        labels = [f"{name} ({n} students)" for _, name, n in others]
        picked, ok = QInputDialog.getItem(self, "Use the list of another exam", "Exam", labels, 0, False)
        if ok:
            other = others[labels.index(picked)]
            self._replace(list(store.students(other[0]).values()), f"of “{other[1]}”")

    def use_batch(self):
        store, exam = self.check.store, self.check.exam
        batches = store.batches()
        everyone = store.directory()
        if not everyone:
            QMessageBox.information(self, "No students in the directory", "Add students under Student directory in "
                                    "the sidebar first, or import an Excel list here.")
            return
        labels = [f"{b} ({sum(s.batch == b for s in everyone)} students)" for b in batches]
        labels.append(f"Everyone in the directory ({len(everyone)} students)")
        picked, ok = QInputDialog.getItem(self, "Use a batch", "Batch", labels, 0, False)
        if not ok:
            return
        n = labels.index(picked)
        chosen = [s for s in everyone if n == len(batches) or s.batch == batches[n]]
        roll = next((g for g in exam.template.grids if g.kind == "roll_number"), None)
        students, problems = for_sheet(chosen, roll.cols if roll else None)
        if not students:
            QMessageBox.warning(self, "Can't use that batch", "None of its roll numbers fit this sheet.\n\n"
                                + "\n".join(problems[:30]))
            return
        if self._replace(students, "of the batch") and problems:
            QMessageBox.information(self, "Some students left out", f"{len(problems)} students can't be on this "
                                    "sheet:\n" + "\n".join(problems[:30]))

    def _replace(self, students: list, source: str) -> bool:
        """Give the exam these students, asking first when it has some; False when the person says no."""
        exam = self.check.exam
        replacing = self.check.store.students(exam.id)
        if replacing and QMessageBox.question(
                self, "Replace student list", f"“{exam.name}” already has {len(replacing)} students. Replace them "
                f"with the {len(students)} {source}?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return False
        self.check.store.set_students(exam.id, students)
        self.changed.emit()
        self.refresh()
        return True


class WrittenTab(QWidget):
    """Marks for a written (subjective) part, typed per student and added to the sheet's score."""

    changed = Signal()

    def __init__(self, check):
        super().__init__()
        self.check = check
        self.out_of = QDoubleSpinBox(minimum=0, maximum=1000, decimals=2, specialValueText="No written part")
        self.out_of.setToolTip("Marks of the written part; 0 for an exam with only the answer sheet")
        self.out_of.editingFinished.connect(self.save_out_of)
        self.note = QLabel(objectName="muted", wordWrap=True)
        top = QHBoxLayout()
        top.addWidget(QLabel("Written part out of"))
        top.addWidget(self.out_of)
        top.addWidget(self.note, 1)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Roll number", "Name", "Written marks"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self.typed)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)

    def showEvent(self, e):
        self.refresh()  # sheets read or students imported since
        super().showEvent(e)

    def rolls(self) -> list[str]:
        """Every student on the list and every roll number read from a sheet."""
        read = {s.result.roll_number for s in self.check.sheets if s.result and "?" not in s.result.roll_number}
        return sorted(read | set(self.check.students))

    def refresh(self):
        c = self.check
        out_of = c.exam.written_out_of if c.exam else 0
        self.out_of.blockSignals(True)
        self.out_of.setValue(out_of)
        self.out_of.blockSignals(False)
        self.out_of.setEnabled(c.exam is not None)
        rolls = self.rolls() if out_of else []
        missing = sum(r not in c.written for r in rolls)
        self.note.setText("" if not c.exam else
                          "Set the marks of the written part to type each student's marks; they add to the sheet's "
                          "score on Results." if not out_of else
                          f"Type marks out of {out_of:g}; Enter moves down. {missing} of {len(rolls)} still to type.")
        self.table.blockSignals(True)
        self.table.setRowCount(len(rolls))
        for row, roll in enumerate(rolls):
            student = c.students.get(roll)
            for col, text in enumerate((roll, student.name if student else "")):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(row, col, item)
            mark = c.written.get(roll)
            self.table.setItem(row, 2, QTableWidgetItem("" if mark is None else f"{mark:g}"))
        self.table.blockSignals(False)
        self.table.setVisible(bool(out_of))
        self.table.resizeColumnsToContents()

    def save_out_of(self):
        c = self.check
        try:
            c.store.set_written_out_of(c.exam.id, self.out_of.value())
        except ValueError as e:
            QMessageBox.warning(self, "Can't change the written part", str(e))
            self.refresh()
            return
        c.exam.written_out_of = self.out_of.value()
        self.changed.emit()

    def typed(self, item: QTableWidgetItem):
        if item.column() != 2:
            return
        c = self.check
        roll = self.table.item(item.row(), 0).text()
        text = item.text().strip()
        try:
            marks = float(text) if text else None
        except ValueError:
            marks = -1.0  # not a number: refused below like any mark out of range
        try:
            c.store.set_written(c.exam.id, roll, marks)
        except ValueError as e:
            QMessageBox.warning(self, "Can't use that mark", f"Roll number {roll}: {text!r} isn't a mark; {e}.")
            self.refresh()
            return
        if marks is None:
            c.written.pop(roll, None)
        else:
            c.written[roll] = marks
        self.changed.emit()


class PrintSheet(QWidget):
    """The exam's own sheet to print, when New exam made it."""

    def __init__(self, check):
        super().__init__()
        self.check = check
        self.template: dict | None = None
        self.note = QLabel(objectName="muted", wordWrap=True)
        self.bar = PrintBar()
        self.bar.changed.connect(self.refresh)
        self.save = self.bar.save
        self.try_print = QPushButton("Check a printed copy…")
        self.try_print.setToolTip("Before printing them all: scan or photograph one printed sheet, blank or with a "
                                  "few bubbles filled, to see that it reads")
        self.try_print.clicked.connect(self.check_print)
        top = QHBoxLayout()
        top.addWidget(self.note, 1)
        top.addWidget(self.try_print)
        self.preview = QLabel(alignment=Qt.AlignCenter)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(self.preview)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.bar)
        layout.addWidget(scroll, 1)

    def refresh(self):
        exam = self.check.exam
        d = json.loads(exam.template_json) if exam else {}
        self.template = d if "print" in d else None  # only sheets New exam made carry what to print
        self.bar.set_template(self.template, exam.name if exam else "")
        self.try_print.setEnabled(exam is not None)
        self.preview.clear()
        if exam is None:
            self.note.setText("")
        elif self.template is None:
            self.note.setText(f"“{exam.template.name}” is a sheet you print yourself, mapped from a scan. Print it "
                              "as you always do; this exam reads it.")
        else:
            self.note.setText("This exam's sheet, ready for any paper size. Keep all four corner circles on the "
                              "paper; scaling or “fit to page” is fine."
                              + (" Each sheet gets its own number, read back when it is scanned."
                                 if "serial_mm" in self.template else ""))
            page = render(self.template, dpi=80, paper=self.bar.paper.currentText(),
                          number=self.bar.first_number())
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
    archived = Signal()

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
        self.series = QComboBox(editable=True)
        self.series.setToolTip("Exams in one test series share the student list and get a combined rank (Exams, "
                               "Test series…)")
        self.series.lineEdit().setPlaceholderText("None")
        put = QPushButton("Save series")
        put.clicked.connect(self.set_series)
        series_row = QHBoxLayout()
        series_row.addWidget(QLabel("Test series"))
        series_row.addWidget(self.series, 1)
        series_row.addWidget(put)
        self.institute = QComboBox()
        self.institute.setToolTip("The institute printed on this exam's scorecards and exports; add them in "
                                  "Settings, Institutes")
        self.institute.activated.connect(self.set_institute)
        institute_row = QHBoxLayout()
        institute_row.addWidget(QLabel("Institute"))
        institute_row.addWidget(self.institute, 1)
        self.about = QLabel(objectName="muted", wordWrap=True)
        change = QPushButton("Change sheet…")
        change.clicked.connect(self.change_sheet)
        delete = QPushButton("Move to Trash…")
        delete.clicked.connect(self.delete)
        self.archive = QPushButton()
        self.archive.clicked.connect(self.toggle_archived)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addLayout(series_row)
        layout.addLayout(institute_row)
        layout.addWidget(self.about)
        layout.addSpacing(24)
        layout.addWidget(QLabel("If students filled a different sheet from this exam's, pick that sheet's template; "
                                "every page is read again with it.", objectName="muted", wordWrap=True))
        layout.addWidget(change, 0, Qt.AlignLeft)
        layout.addSpacing(24)
        layout.addWidget(QLabel("Archive a finished exam to take it off the exam list; it keeps its results and "
                                "opens from Exams, Archived.", objectName="muted", wordWrap=True))
        layout.addWidget(self.archive, 0, Qt.AlignLeft)
        layout.addSpacing(24)
        layout.addWidget(QLabel(f"An exam moved to the Trash can be restored from Exams, Trash for {TRASH_DAYS} days; "
                                "then it is deleted for good.", objectName="muted", wordWrap=True))
        layout.addWidget(delete, 0, Qt.AlignLeft)
        layout.addStretch()

    def refresh(self):
        exam = self.check.exam
        self.name.setText(exam.name if exam else "")
        self.series.clear()
        self.series.addItems(["", *self.check.store.series_names()])
        self.series.setCurrentText(exam.details.get("series", "") if exam else "")
        rows = self.check.store.institutes()
        default = next((inst.name for _, inst, d in rows if d), "")
        self.institute.clear()
        self.institute.addItem(f"The default ({default})" if default else "None (add one in Settings)", None)
        for i, inst, _ in rows:
            self.institute.addItem(inst.name, i)
        chosen = exam.details.get("institute") if exam else None
        self.institute.setCurrentIndex(max(0, self.institute.findData(chosen)) if chosen is not None else 0)
        self.institute.setEnabled(bool(rows))
        self.archive.setText("Put back on the exam list" if exam and exam.archived else "Archive exam")
        self.about.setText("\n".join([*when(exam), f"Sheet: {exam.template.name}, {len(self.check.questions)} "
                                       f"questions.  Created {exam.created.replace('T', ' ')}."]) if exam else "")

    def rename(self):
        try:
            self.check.store.rename_exam(self.check.exam.id, self.name.text())
        except ValueError as e:
            QMessageBox.warning(self, "Can't rename", str(e))
            return
        self.changed.emit()

    def set_institute(self):
        self.check.store.set_exam_institute(self.check.exam.id, self.institute.currentData())
        self.changed.emit()

    def set_series(self):
        self.check.store.set_series(self.check.exam.id, self.series.currentText())
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
        if QMessageBox.question(self, "Move to Trash", f"Move “{exam.name}” and every sheet read for it to the Trash? "
                                f"You can restore it from Exams, Trash for {TRASH_DAYS} days.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.check.store.move_to_trash(exam.id)
        self.deleted.emit()

    def toggle_archived(self):
        exam = self.check.exam
        self.check.store.set_archived(exam.id, not exam.archived)
        exam.archived = not exam.archived
        self.refresh()
        self.archived.emit()
