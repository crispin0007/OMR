"""Main window: a sidebar of pages over one set of sheets read in this run."""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
                               QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton,
                               QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from omr_core.grading import parse_key, score
from omr_core.reader import PageResult, UnreadablePage, read_page
from omr_core.sources import read_pages
from omr_core.template import Template, load

from . import theme
from .dashboard import DashboardPage, ResultsPage

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"  # the repo's templates, in a source checkout
COLUMNS = ["File", "Page", "Roll number", "Set", "Answered", "Score", "Review"]


@dataclass
class Sheet:
    file: str
    page: int
    result: PageResult | None  # None when the page couldn't be read at all
    problem: str = ""


@dataclass
class Batch:
    """One "Open sheets" action: sheets[start:start + count]."""
    name: str
    when: datetime
    start: int
    count: int


class CheckPage(QWidget):
    """Pick a template, open scanned sheets, type the key, see scores and what needs review."""

    changed = Signal()  # sheets, key or marks changed
    wanted = Signal()  # another page asked to show sheets here

    def __init__(self):
        super().__init__()
        self.template: Template | None = None
        self.questions: list[int] = []
        self.sheets: list[Sheet] = []
        self.batches: list[Batch] = []
        self.keys: dict[str, list[str]] = {}

        self.template_label = QLabel("No template chosen", objectName="muted")
        choose = QPushButton("Choose template…")
        choose.clicked.connect(self.choose_template)
        self.open_button = QPushButton("Open sheets…", objectName="primary")
        self.open_button.clicked.connect(self.open_sheets)
        self.save_button = QPushButton("Save CSV…")
        self.save_button.clicked.connect(self.save_csv)
        top = QHBoxLayout()
        top.addWidget(QLabel("Check sheets", objectName="title"))
        top.addSpacing(16)
        top.addWidget(self.template_label)
        top.addWidget(choose)
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

        default = TEMPLATES / "test-100.json"
        if default.exists():
            self.set_template(str(default))
        self.show_sheets(None)
        self._enable()

    def _marks(self, value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox(minimum=-100, maximum=100, value=value, decimals=2, singleStep=0.25)
        box.valueChanged.connect(self.fill_table)
        return box

    def _enable(self):
        self.open_button.setEnabled(self.template is not None)
        self.save_button.setEnabled(bool(self.sheets))

    @staticmethod
    def file_name(sheet: Sheet) -> str:
        return Path(sheet.file).name

    def full_marks(self) -> float:
        return len(self.questions) * self.correct.value()

    def to_check(self) -> list[int]:
        """Sheets with anything to review, unreadable ones included."""
        return [i for i, s in enumerate(self.sheets) if s.result is None or s.result.flags]

    def choose_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose template", str(TEMPLATES), "Templates (*.json)")
        if path:
            self.set_template(path)

    def set_template(self, path: str):
        try:
            template = load(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Can't use this template", f"{path}\n\n{e}")
            return
        if self.sheets and template != self.template:
            self.sheets, self.batches = [], []  # sheets read with another template don't match its questions
        self.template = template
        self.questions = sorted(g.first + r for g in template.grids if g.kind == "questions" for r in range(g.rows))
        self.template_label.setText(f"{template.name}  ({len(self.questions)} questions)")
        self.update_key()
        self._enable()

    def open_sheets(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open scanned sheets", "", "Scans (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if paths:
            self.read_files(paths)

    def read_files(self, paths: list[str]):
        failed, start = [], len(self.sheets)
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
                        self.sheets.append(Sheet(path, n, read_page(page, self.template)))
                    except UnreadablePage as e:
                        self.sheets.append(Sheet(path, n, None, f"unreadable: {e}"))
            except (OSError, ValueError) as e:
                failed.append(f"{name}: {e}")
            if progress.wasCanceled():
                break
        progress.close()
        if len(self.sheets) > start:
            name = Path(paths[0]).name + (f" and {len(paths) - 1} more" if len(paths) > 1 else "")
            self.batches.append(Batch(name, datetime.now(), start, len(self.sheets) - start))
        self.show_sheets(None)
        self._enable()
        if failed:
            QMessageBox.warning(self, "Some files weren't read", "\n".join(failed))

    def update_key(self):
        if self.template is None:
            return
        options = "".join(sorted({o for g in self.template.grids if g.kind == "questions" for o in g.options}))
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
        self.fill_table()

    def score_of(self, sheet: Sheet) -> float | None:
        r = sheet.result
        key = r and self.keys.get(r.set_code, self.keys.get(""))
        if not key:
            return None
        return score([r.answers[q] for q in self.questions], key,
                     self.correct.value(), self.wrong.value(), self.blank.value())

    def _score_text(self, sheet: Sheet) -> str:
        s = self.score_of(sheet)
        if s is not None:
            return f"{s:g}"
        return "no key for set " + sheet.result.set_code if sheet.result and self.keys else ""

    def fill_table(self):
        self.table.setRowCount(len(self.sheets))
        review_bg = QBrush(QColor(theme.tokens()["warn_bg"]))
        for row, sheet in enumerate(self.sheets):
            r = sheet.result
            review = sheet.problem or (f"{len(r.flags)} to check" if r.flags else "")
            cells = [self.file_name(sheet), str(sheet.page), r.roll_number if r else "", r.set_code if r else "",
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
        a = r.aligned
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
    PAGES = ["Dashboard", "Check sheets", "Results", "Question Bank", "Syllabus", "Settings"]
    LATER = {"Question Bank": "Comes in phase 2", "Syllabus": "Comes in phase 3"}

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OMR")
        self.prefs = theme.load_prefs()
        self.check = CheckPage()
        self.dashboard = DashboardPage(self.check)
        self.results = ResultsPage(self.check)
        self.settings = theme.SettingsPage(self.prefs)
        self.settings.changed.connect(self.apply_prefs)
        pages = {"Dashboard": self.dashboard, "Check sheets": self.check, "Results": self.results,
                 "Settings": self.settings}

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
                self.stack.addWidget(pages[name])
                b.clicked.connect(lambda _=False, w=pages[name]: self.stack.setCurrentWidget(w))
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
        self.go("Dashboard")

    def go(self, name: str):
        self.nav_buttons[name].setChecked(True)
        self.stack.setCurrentWidget({"Dashboard": self.dashboard, "Check sheets": self.check,
                                     "Results": self.results, "Settings": self.settings}[name])

    def toggle_theme(self):
        """Quick switch between light and dark; Settings has System and the rest."""
        self.settings.theme.setCurrentText("Light" if theme.is_dark(self.prefs) else "Dark")

    def apply_prefs(self, prefs: theme.Prefs):
        self.prefs = prefs
        theme.apply(QApplication.instance(), prefs)
        self.theme_button.setText("☀  Light mode" if theme.is_dark(prefs) else "☾  Dark mode")
        self.check.fill_table()  # repaints review rows and, through `changed`, the dashboard and results
