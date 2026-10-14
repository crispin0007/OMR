"""A student's profile (every exam they took, their trend and weak sections) and attendance by batch."""

import csv
import io
from pathlib import Path

from PySide6.QtCore import QPointF, QStandardPaths, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget)

from omr_core.progress import Entry, attendance, history, section_averages
from omr_core.store import Store
from omr_core.students import Student

from .theme import tokens


class TrendChart(QWidget):
    """Score percentage in each exam, oldest first, as one line; hover a point for the exam and score."""

    def __init__(self, entries: list[Entry]):
        super().__init__()
        self.entries = entries
        self.setMinimumHeight(170)
        self.setMouseTracking(True)

    def _points(self) -> list[QPointF]:
        left, right, top, bottom = 40, 16, 12, 24
        w, h = self.width() - left - right, self.height() - top - bottom
        n = len(self.entries)
        return [QPointF(left + (w * i / (n - 1) if n > 1 else w / 2), top + h * (1 - e.percent / 100))
                for i, e in enumerate(self.entries)]

    def paintEvent(self, _):
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        left, top, bottom = 40, 12, 24
        h = self.height() - top - bottom
        p.setPen(QPen(QColor(t["border"]), 1))
        for v in (0, 50, 100):  # recessive grid
            y = top + h * (1 - v / 100)
            p.drawLine(left, int(y), self.width() - 16, int(y))
            p.setPen(QColor(t["muted"]))
            p.drawText(0, int(y) - 8, left - 6, 16, Qt.AlignRight | Qt.AlignVCenter, f"{v}%")
            p.setPen(QPen(QColor(t["border"]), 1))
        points = self._points()
        if not points:
            p.setPen(QColor(t["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, "No exams with a sheet read for this student yet")
            return
        p.setPen(QPen(QColor(t["accent"]), 2))
        p.drawPolyline(points)
        p.setBrush(QColor(t["accent"]))
        p.setPen(QPen(QColor(t["card"]), 2))  # a ring of the surface keeps markers apart from the line
        for pt in points:
            p.drawEllipse(pt, 5, 5)
        p.setPen(QColor(t["text"]))
        last = points[-1]
        p.drawText(int(last.x()) - 60, int(last.y()) - 26, 56, 18, Qt.AlignRight | Qt.AlignVCenter,
                   f"{self.entries[-1].percent:g}%")

    def mouseMoveEvent(self, e):
        points = self._points()
        if not points:
            return
        i = min(range(len(points)), key=lambda k: abs(points[k].x() - e.position().x()))
        entry = self.entries[i]
        QToolTip.showText(e.globalPosition().toPoint(), f"{entry.exam}  ·  {entry.date}\n{entry.score:g} of "
                          f"{entry.out_of:g}  ({entry.percent:g}%)  ·  rank {entry.rank} of {entry.of}", self)


def table(columns: list[str], rows: list[tuple]) -> QTableWidget:
    t = QTableWidget(len(rows), len(columns))
    t.setHorizontalHeaderLabels(columns)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.verticalHeader().hide()
    for r, values in enumerate(rows):
        for c, v in enumerate(values):
            item = QTableWidgetItem()
            item.setData(Qt.DisplayRole, v)
            t.setItem(r, c, item)
    t.resizeColumnsToContents()
    return t


class ProfileDialog(QDialog):
    def __init__(self, parent, store: Store, student: Student):
        super().__init__(parent)
        self.setWindowTitle(student.name)
        self.resize(900, 700)
        self.entries = history(store, student.roll_number)
        facts = [f"Roll number {student.roll_number}", student.class_name and f"Class {student.class_name}",
                 student.batch and f"Batch {student.batch}", student.email, student.phone]
        head = QLabel(f"<h2>{student.name}</h2>" + "  ·  ".join(f for f in facts if f), textFormat=Qt.RichText)
        head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        e = self.entries
        if e:
            change = e[-1].percent - e[0].percent if len(e) > 1 else None
            summary = (f"{len(e)} exam{'s' if len(e) > 1 else ''}, average {sum(x.percent for x in e) / len(e):.1f}%, "
                       f"best {max(x.percent for x in e):g}%"
                       + (f", {'up' if change >= 0 else 'down'} {abs(change):.1f} points since the first" if change
                          is not None else "") + ".")
        else:
            summary = "No exam has a sheet read for this roll number yet."
        sections = section_averages(e)
        weak = (f"Weakest: {sections[0][0]} ({sections[0][1]:g}%). Strongest: {sections[-1][0]} "
                f"({sections[-1][1]:g}%)." if len(sections) > 1 else "")
        layout = QVBoxLayout(self)
        layout.addWidget(head)
        layout.addWidget(QLabel(f"{summary} {weak}", objectName="muted", wordWrap=True))
        layout.addWidget(QLabel("Score % in each exam", objectName="muted"))
        self.chart = TrendChart(e)
        layout.addWidget(self.chart)
        self.exams = table(["Exam", "Date", "Score", "Out of", "%", "Rank", "Percentile"],
                           [(x.exam, x.date, x.score, x.out_of, x.percent, f"{x.rank} of {x.of}",
                             round(x.percentile, 1)) for x in e])
        self.sections = table(["Section", "Average %", "Exams"], sections)
        tables = QHBoxLayout()
        tables.addWidget(self.exams, 3)
        tables.addWidget(self.sections, 2)
        layout.addLayout(tables, 1)


class AttendanceDialog(QDialog):
    """Who sat which exam: a batch's students against a program's (or every) exam, a sheet read counting as
    present."""

    def __init__(self, parent, store: Store):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Attendance")
        self.resize(1000, 640)
        self.batch = QComboBox()
        self.batch.addItems(["Every student", *store.batches()])
        self.program = QComboBox()
        self.program.addItem("Every exam", None)
        for f in store.folders():
            if f.parent is None:
                self.program.addItem(f.name, f.id)
        for box in (self.batch, self.program):
            box.activated.connect(lambda _: self.refresh())
        self.save = QPushButton("Save as CSV…")
        self.save.clicked.connect(self.save_csv)
        top = QHBoxLayout()
        top.addWidget(self.batch)
        top.addWidget(self.program)
        top.addStretch()
        top.addWidget(self.save)
        self.note = QLabel(objectName="muted", wordWrap=True)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.note)
        layout.addWidget(self.table, 1)
        self.refresh()

    def refresh(self):
        batch = self.batch.currentText()
        self.students = [s for s in self.store.directory() if self.batch.currentIndex() == 0 or s.batch == batch]
        program = self.program.currentData()
        inside = {f.id for f in self.store.folders() if f.id == program or f.parent == program}
        where = self.store.exam_folders()
        self.exams = [(i, name) for i, name, *_ in reversed(self.store.exams("kept"))
                      if program is None or where.get(i) in inside]
        present = attendance(self.store, [s.roll_number for s in self.students], [i for i, _ in self.exams])
        self.rows = []
        missed = 0
        for s in self.students:
            marks = present[s.roll_number]
            missed += not all(marks)
            self.rows.append([s.roll_number, s.name, s.batch, *("✓" if m else "absent" for m in marks),
                              f"{sum(marks)} of {len(marks)}"])
        self.note.setText(f"{len(self.students)} students, {len(self.exams)} exams; {missed} missed at least one. "
                          "A sheet read for the roll number counts as present." if self.students else
                          "No students here. Add them under Student directory, with a batch.")
        columns = ["Roll number", "Name", "Batch", *(name for _, name in self.exams), "Sat"]
        self.table.clear()
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(len(self.rows))
        warn = QColor(tokens()["warn"])
        for r, values in enumerate(self.rows):
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if v == "absent":
                    item.setForeground(warn)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.save.setEnabled(bool(self.rows))

    def save_csv(self):
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Save attendance", str(docs / "attendance.csv"), "CSV (*.csv)")
        if not path:
            return
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["Roll number", "Name", "Batch", *(name for _, name in self.exams), "Sat"])
        w.writerows(self.rows)
        try:
            Path(path).write_text(out.getvalue(), encoding="utf-8-sig")  # the BOM makes Excel read it as UTF-8
        except OSError as e:  # e.g. the file is open in Excel
            QMessageBox.warning(self, "Couldn't save", f"{path}\n\n{e}")
