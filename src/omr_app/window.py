"""Main window: a sidebar of pages over the open exam, saved as it is read."""

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
                               QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton,
                               QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from omr_core.grading import parse_key, score
from omr_core.reader import UnreadablePage, read_page
from omr_core.sources import read_pages
from omr_core.store import Exam, Store, StoredPage, to_review
from omr_core.students import Student

from . import theme
from .dashboard import DashboardPage, ResultsPage
from .designer import DesignerPage
from .exams import TEMPLATES, ExamsPage
from .review import ReviewPage

COLUMNS = ["File", "Page", "Roll number", "Name", "Set", "Answered", "Score", "Review"]


@dataclass
class Batch:
    """One "Open sheets" action: sheets[start:start + count]."""
    name: str
    when: datetime
    start: int
    count: int


class CheckPage(QWidget):
    """Open scanned sheets for the exam, type the key, see scores and what needs review."""

    changed = Signal()  # sheets, key or marks changed
    wanted = Signal()  # another page asked to show sheets here
    review_wanted = Signal()  # another page asked for the review queue

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.exam: Exam | None = None
        self.questions: list[int] = []
        self.sheets: list[StoredPage] = []
        self.students: dict[str, Student] = {}
        self.keys: dict[str, list[str]] = {}

        self.template_label = QLabel("Open or create an exam on the Exams page", objectName="muted")
        self.open_button = QPushButton("Open sheets…", objectName="primary")
        self.open_button.clicked.connect(self.open_sheets)
        self.save_button = QPushButton("Save CSV…")
        self.save_button.clicked.connect(self.save_csv)
        top = QHBoxLayout()
        top.addWidget(QLabel("Check sheets", objectName="title"))
        top.addSpacing(16)
        top.addWidget(self.template_label)
        top.addStretch()
        top.addWidget(self.open_button)
        top.addWidget(self.save_button)

        self.key_edit = QPlainTextEdit()
        self.key_edit.setPlaceholderText(
            "Answer key, one letter per question in order, e.g. ABDCA…\n"
            "One line per set: A: ABDC…   B: CADB…\n"
            "Separate with commas for more than one correct option: A, AC, B.  * = bonus, - = dropped")
        self.key_edit.setFixedHeight(84)
        self.key_edit.textChanged.connect(self.update_key)
        self.key_status = QLabel(objectName="muted")
        self.correct, self.wrong, self.blank = (self._marks(v) for v in (1, 0, 0))
        marks = QHBoxLayout()
        for text, box in (("Correct", self.correct), ("Wrong", self.wrong), ("Blank", self.blank)):
            marks.addWidget(QLabel(text))
            marks.addWidget(box)
        marks.addSpacing(12)
        marks.addWidget(self.key_status, 1)

        self.filter_label = QLabel(objectName="muted")
        self.show_all = QPushButton("Show all")
        self.show_all.clicked.connect(lambda: self.show_sheets(None))
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(self.filter_label)
        filter_bar.addWidget(self.show_all)
        filter_bar.addStretch()

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_sheet)
        table_box = QWidget()
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addLayout(filter_bar)
        table_layout.addWidget(self.table, 1)

        self.page_view = QLabel("Select a sheet to see it", objectName="muted")
        self.page_view.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.page_view)
        scroll.setWidgetResizable(True)
        self.review_list = QListWidget()
        self.answers_view = QPlainTextEdit(readOnly=True)
        side = QSplitter(Qt.Vertical)
        for w in (scroll, self.review_list, self.answers_view):
            side.addWidget(w)
        side.setSizes([500, 120, 120])
        split = QSplitter()
        split.addWidget(table_box)
        split.addWidget(side)
        split.setSizes([620, 480])

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.key_edit)
        layout.addLayout(marks)
        layout.addWidget(split, 1)

        self.show_sheets(None)
        self._enable()

    def _marks(self, value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox(minimum=-100, maximum=100, value=value, decimals=2, singleStep=0.25)
        box.valueChanged.connect(self.scheme_changed)
        return box

    def _enable(self):
        for w in (self.open_button, self.key_edit, self.correct, self.wrong, self.blank):
            w.setEnabled(self.exam is not None)
        self.save_button.setEnabled(bool(self.sheets))

    def open_exam(self, exam_id: int | None):
        """Show an exam's saved key, marks and sheets; None closes it."""
        self.exam = None  # keeps the loading below from saving the scheme back
        if exam_id is None:
            self.questions, self.sheets, self.students = [], [], {}
            self.template_label.setText("Open or create an exam on the Exams page")
            self.key_edit.clear()
        else:
            exam = self.store.exam(exam_id)
            t = exam.template
            self.questions = sorted(g.first + r for g in t.grids if g.kind == "questions" for r in range(g.rows))
            self.sheets = self.store.pages(exam_id)
            self.students = self.store.students(exam_id)
            self.template_label.setText(f"{exam.name}  ·  {t.name}, {len(self.questions)} questions")
            for box, v in ((self.correct, exam.correct), (self.wrong, exam.wrong), (self.blank, exam.blank)):
                box.setValue(v)
            self.key_edit.setPlainText(exam.answer_key)
            self.exam = exam
        self.update_key()
        self.show_sheets(None)
        self._enable()

    def scheme_changed(self):
        if self.exam is not None:
            self.store.save_scheme(self.exam.id, self.key_edit.toPlainText(), self.correct.value(),
                                   self.wrong.value(), self.blank.value())
        self.fill_table()

    @property
    def batches(self) -> list[Batch]:
        out = []
        for i, s in enumerate(self.sheets):
            if out and out[-1].name == s.batch and out[-1].start + out[-1].count == i:
                out[-1].count += 1
            else:
                out.append(Batch(s.batch, datetime.fromisoformat(s.read_at), i, 1))
        return out

    @staticmethod
    def file_name(sheet: StoredPage) -> str:
        return Path(sheet.file).name

    def full_marks(self) -> float:
        return len(self.questions) * self.correct.value()

    def review_items(self) -> list[tuple[int, str, str]]:
        return to_review(self.sheets, self.students)

    def to_check(self) -> list[int]:
        """Sheets with anything to review: flags, unreadable pages, duplicate or unknown roll numbers."""
        return sorted({i for i, _, _ in self.review_items()})

    def name_of(self, sheet: StoredPage) -> str:
        s = sheet.result and self.students.get(sheet.result.roll_number)
        return s.name if s else ""

    def open_sheets(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open scanned sheets", "", "Scans (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if paths:
            self.read_files(paths)

    def read_files(self, paths: list[str]):
        failed = []
        # The time keeps two imports of the same files apart.
        batch = (Path(paths[0]).name + (f" and {len(paths) - 1} more" if len(paths) > 1 else "")
                 + f"  ·  {datetime.now():%d %b %H:%M:%S}")
        progress = QProgressDialog("Reading sheets…", "Stop", 0, len(paths), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(300)
        for i, path in enumerate(paths):
            progress.setValue(i)
            name = Path(path).name
            try:
                for n, page in enumerate(read_pages(path), 1):
                    progress.setLabelText(f"Reading {name}, page {n}")
                    QApplication.processEvents()
                    if progress.wasCanceled():
                        break
                    try:
                        result, problem = read_page(page, self.exam.template), ""
                    except UnreadablePage as e:
                        result, problem = None, f"unreadable: {e}"
                    stored = self.store.add_page(self.exam.id, batch, path, n, result, problem)
                    if stored.result:
                        stored.result.aligned = None  # the image is in the store; don't keep every page in memory
                    self.sheets.append(stored)
            except (OSError, ValueError) as e:
                failed.append(f"{name}: {e}")
            if progress.wasCanceled():
                break
        progress.close()
        self.show_sheets(None)
        self._enable()
        if failed:
            QMessageBox.warning(self, "Some files weren't read", "\n".join(failed))

    def update_key(self):
        if self.exam is None:
            self.keys = {}
            self.key_status.setText("")
            self.fill_table()
            return
        t = self.exam.template
        options = "".join(sorted({o for g in t.grids if g.kind == "questions" for o in g.options}))
        try:
            self.keys = parse_key(self.key_edit.toPlainText(), len(self.questions), options)
            self.key_status.setText(f"Key for {', '.join('set ' + s if s else 'all sets' for s in self.keys)}"
                                    if self.keys else "Type the answer key to see scores")
            self.key_status.setObjectName("muted")
        except ValueError as e:
            self.keys = {}
            self.key_status.setText(str(e))
            self.key_status.setObjectName("error")
        self.key_status.setStyleSheet("")  # re-apply the theme for the new object name
        self.scheme_changed()

    def score_of(self, sheet: StoredPage) -> float | None:
        r = sheet.result
        key = r and self.keys.get(r.set_code, self.keys.get(""))
        if not key:
            return None
        return score([r.answers[q] for q in self.questions], key,
                     self.correct.value(), self.wrong.value(), self.blank.value())

    def _score_text(self, sheet: StoredPage) -> str:
        s = self.score_of(sheet)
        if s is not None:
            return f"{s:g}"
        return "no key for set " + sheet.result.set_code if sheet.result and self.keys else ""

    def fill_table(self):
        self.table.setRowCount(len(self.sheets))
        review_bg = QBrush(QColor(theme.tokens()["warn_bg"]))
        items = Counter(i for i, _, _ in self.review_items())
        for row, sheet in enumerate(self.sheets):
            r = sheet.result
            review = sheet.problem or (f"{items[row]} to check" if items[row] else "")
            cells = [self.file_name(sheet), str(sheet.page), r.roll_number if r else "", self.name_of(sheet),
                     r.set_code if r else "",
                     f"{sum(1 for q in self.questions if r.answers[q])}/{len(self.questions)}" if r else "",
                     self._score_text(sheet), review]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if review:
                    item.setBackground(review_bg)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.changed.emit()

    def show_sheets(self, rows: list[int] | None, label: str = ""):
        """Show only these sheets (None for all) and bring this page forward."""
        self.fill_table()
        keep = set(range(len(self.sheets)) if rows is None else rows)
        for row in range(len(self.sheets)):
            self.table.setRowHidden(row, row not in keep)
        filtered = rows is not None
        self.filter_label.setText(f"Showing {len(keep)} of {len(self.sheets)} sheets {label}" if filtered
                                  else f"{len(self.sheets)} sheets")
        self.show_all.setVisible(filtered)
        if filtered:
            self.wanted.emit()

    def select(self, index: int):
        self.table.selectRow(index)
        self.wanted.emit()

    def show_sheet(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        sheet = self.sheets[rows[0].row()]
        r = sheet.result
        self.review_list.clear()
        if r is None:
            self.page_view.setText(sheet.problem)
            self.answers_view.clear()
            return
        a = self.store.image(sheet.id)
        if a is None:
            self.page_view.setText("No image saved for this page")
            return
        image = QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format_Grayscale8).copy()
        self.page_view.setPixmap(QPixmap.fromImage(image).scaledToWidth(
            max(self.page_view.width() - 20, 300), Qt.SmoothTransformation))
        self.review_list.addItems([f"{where}: {why}" for where, why in r.flags] or ["Nothing to check"])
        self.answers_view.setPlainText("   ".join(f"{q}:{r.answers[q] or '·'}" for q in self.questions))

    def save_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save results", "results.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:  # the BOM lets Excel open it as UTF-8
                w = csv.writer(f)
                w.writerow(["file", "page", "roll_number", "set_code", "score", *(f"Q{q}" for q in self.questions),
                            "review"])
                for s in self.sheets:
                    r = s.result
                    w.writerow([s.file, s.page, r.roll_number if r else "", r.set_code if r else "",
                                self._score_text(s), *(r.answers[q] if r else "" for q in self.questions),
                                s.problem or "; ".join(f"{a}: {b}" for a, b in (r.flags if r else []))])
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save", str(e))
            return
        self.window().statusBar().showMessage(f"Saved {len(self.sheets)} rows to {path}", 5000)


class MainWindow(QMainWindow):
    PAGES = ["Dashboard", "Exams", "Check sheets", "Review", "Results", "Sheet designer", "Question Bank", "Syllabus",
             "Settings"]
    LATER = {"Question Bank": "Comes in phase 2", "Syllabus": "Comes in phase 3"}

    def __init__(self, db_path: str | Path | None = None):
        super().__init__()
        self.setWindowTitle("OMR")
        self.prefs = theme.load_prefs()
        if db_path is None:
            data = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)  # %LOCALAPPDATA% on Windows
            db_path = Path(data) / "OMR" / "omr.db"
        self.store = Store(db_path)
        self.check = CheckPage(self.store)
        self.exams = ExamsPage(self.store)
        self.exams.opened.connect(self.open_exam)
        self.exams.students_changed.connect(self.reload_students)
        self.dashboard = DashboardPage(self.check)
        self.results = ResultsPage(self.check)
        self.review = ReviewPage(self.check)
        self.designer = DesignerPage()
        self.settings = theme.SettingsPage(self.prefs)
        self.settings.changed.connect(self.apply_prefs)
        self.pages = {"Dashboard": self.dashboard, "Exams": self.exams, "Check sheets": self.check,
                      "Review": self.review, "Results": self.results,
                      "Sheet designer": self.designer, "Settings": self.settings}

        self.stack = QStackedWidget()
        sidebar = QWidget(objectName="sidebar")
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(10, 16, 10, 16)
        nav.addWidget(QLabel("  OMR", objectName="title"))
        nav.addSpacing(12)
        self.nav = QButtonGroup(self)
        self.nav_buttons = {}
        for name in self.PAGES:
            b = QPushButton(name, objectName="nav", checkable=True)
            if name in self.LATER:
                b.setEnabled(False)
                b.setToolTip(self.LATER[name])
            else:
                self.stack.addWidget(self.pages[name])
                b.clicked.connect(lambda _=False, n=name: self.go(n))
            self.nav.addButton(b)
            self.nav_buttons[name] = b
            if name == "Settings":
                nav.addStretch()
            nav.addWidget(b)
        self.theme_button = QPushButton(objectName="nav")
        self.theme_button.clicked.connect(self.toggle_theme)
        nav.addWidget(self.theme_button)
        sidebar.setFixedWidth(190)

        self.check.wanted.connect(lambda: self.go("Check sheets"))
        self.check.review_wanted.connect(lambda: self.go("Review"))
        self.check.changed.connect(self.exams.refresh)
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)
        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.resize(1280, 820)
        self.apply_prefs(self.prefs)
        QApplication.styleHints().colorSchemeChanged.connect(lambda _: self.apply_prefs(self.prefs))  # Windows switched

        last = theme.settings().value("last_exam")
        known = {e[0] for e in self.store.exams()}
        last = int(last) if str(last).isdigit() and int(last) in known else None
        self.open_exam(last, go=False)
        self.go("Dashboard" if last else "Exams")

    def open_exam(self, exam_id: int | None, go: bool = True):
        self.check.open_exam(exam_id)
        self.exams.refresh(exam_id)
        theme.settings().setValue("last_exam", exam_id or "")
        name = self.check.exam.name if self.check.exam else ""
        self.setWindowTitle(f"OMR  ·  {name}" if name else "OMR")
        if go and exam_id is not None:
            self.go("Check sheets")

    def reload_students(self, exam_id: int):
        if self.check.exam and self.check.exam.id == exam_id:
            self.check.students = self.store.students(exam_id)
            self.check.fill_table()

    def go(self, name: str):
        self.nav_buttons[name].setChecked(True)
        self.stack.setCurrentWidget(self.pages[name])

    def toggle_theme(self):
        """Quick switch between light and dark; Settings has System and the rest."""
        self.settings.theme.setCurrentText("Light" if theme.is_dark(self.prefs) else "Dark")

    def apply_prefs(self, prefs: theme.Prefs):
        self.prefs = prefs
        theme.apply(QApplication.instance(), prefs)
        self.theme_button.setText("☀  Light mode" if theme.is_dark(prefs) else "☾  Dark mode")
        self.check.fill_table()  # repaints review rows and, through `changed`, the dashboard and results

    def closeEvent(self, e):
        self.store.close()
        super().closeEvent(e)
