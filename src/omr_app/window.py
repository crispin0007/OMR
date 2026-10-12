"""Main window: pick a template, open scanned sheets, type the key, see scores and what needs review."""

import csv
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QScrollArea,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from omr_core.grading import parse_key, score
from omr_core.reader import PageResult, UnreadablePage, read_page
from omr_core.sources import read_pages
from omr_core.template import Template, load

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"  # the repo's templates, in a source checkout
COLUMNS = ["File", "Page", "Roll number", "Set", "Answered", "Score", "Review"]
REVIEW = QBrush(QColor(255, 220, 140))


@dataclass
class Sheet:
    file: str
    page: int
    result: PageResult | None  # None when the page couldn't be read at all
    problem: str = ""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OMR")
        self.template: Template | None = None
        self.questions: list[int] = []
        self.sheets: list[Sheet] = []
        self.keys: dict[str, list[str]] = {}

        self.template_label = QLabel("No template chosen")
        choose = QPushButton("Choose template…")
        choose.clicked.connect(self.choose_template)
        self.open_button = QPushButton("Open sheets…")
        self.open_button.clicked.connect(self.open_sheets)
        self.save_button = QPushButton("Save CSV…")
        self.save_button.clicked.connect(self.save_csv)
        top = QHBoxLayout()
        for w in (QLabel("Template:"), self.template_label, choose):
            top.addWidget(w)
        top.addStretch()
        top.addWidget(self.open_button)
        top.addWidget(self.save_button)

        self.key_edit = QPlainTextEdit()
        self.key_edit.setPlaceholderText(
            "Answer key, one letter per question in order, e.g. ABDCA…\n"
            "One line per set: A: ABDC…   B: CADB…\n"
            "Separate with commas for more than one correct option: A, AC, B.  * = bonus, - = dropped")
        self.key_edit.setFixedHeight(80)
        self.key_edit.textChanged.connect(self.update_key)
        self.key_status = QLabel()
        self.correct, self.wrong, self.blank = (self._marks(v) for v in (1, 0, 0))
        marks = QHBoxLayout()
        for text, box in (("Correct", self.correct), ("Wrong", self.wrong), ("Blank", self.blank)):
            marks.addWidget(QLabel(text))
            marks.addWidget(box)
        marks.addWidget(self.key_status, 1)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_sheet)

        self.page_view = QLabel("Select a sheet to see it")
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
        split.addWidget(self.table)
        split.addWidget(side)
        split.setSizes([620, 480])

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.key_edit)
        layout.addLayout(marks)
        layout.addWidget(split, 1)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        self.resize(1200, 800)

        default = TEMPLATES / "test-100.json"
        if default.exists():
            self.set_template(str(default))
        self._enable()

    def _marks(self, value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox(minimum=-100, maximum=100, value=value, decimals=2, singleStep=0.25)
        box.valueChanged.connect(self.fill_table)
        return box

    def _enable(self):
        self.open_button.setEnabled(self.template is not None)
        self.save_button.setEnabled(bool(self.sheets))

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
            self.sheets = []  # sheets read with another template don't match its questions
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
        failed = []
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
        self.fill_table()
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
            self.key_status.setStyleSheet("")
        except ValueError as e:
            self.keys = {}
            self.key_status.setText(str(e))
            self.key_status.setStyleSheet("color: #c0392b")
        self.fill_table()

    def sheet_score(self, sheet: Sheet) -> str:
        r = sheet.result
        if r is None:
            return ""
        key = self.keys.get(r.set_code, self.keys.get(""))
        if key is None:
            return "no key for set " + r.set_code if self.keys else ""
        total = score([r.answers[q] for q in self.questions], key,
                      self.correct.value(), self.wrong.value(), self.blank.value())
        return f"{total:g}"

    def fill_table(self):
        self.table.setRowCount(len(self.sheets))
        for row, sheet in enumerate(self.sheets):
            r = sheet.result
            review = sheet.problem or (f"{len(r.flags)} to check" if r.flags else "")
            cells = [Path(sheet.file).name, str(sheet.page), r.roll_number if r else "", r.set_code if r else "",
                     f"{sum(1 for q in self.questions if r.answers[q])}/{len(self.questions)}" if r else "",
                     self.sheet_score(sheet), review]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if review:
                    item.setBackground(REVIEW)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()

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
        self.answers_view.setPlainText("   ".join(f"{q}:{r.answers[q] or '-'}" for q in self.questions))

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
                                self.sheet_score(s), *(r.answers[q] if r else "" for q in self.questions),
                                s.problem or "; ".join(f"{a}: {b}" for a, b in (r.flags if r else []))])
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save", str(e))
            return
        self.statusBar().showMessage(f"Saved {len(self.sheets)} rows to {path}", 5000)
