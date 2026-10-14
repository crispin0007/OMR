"""Test series: the combined merit list and leaderboard of the exams in a series, how the class did in each
test and section, and the series merit list in Excel."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from omr_core.series import exam_summary, series_results, write_series_excel
from omr_core.store import Store

EVERYONE = "Every batch and class"


def movement(n: int | None) -> str:
    return "" if n is None else "–" if n == 0 else f"▲ {n}" if n > 0 else f"▼ {-n}"


class SeriesDialog(QDialog):
    def __init__(self, parent, store: Store, series: str = "", program: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("Test series")
        self.resize(1100, 680)
        self.store = store
        self.exams, self.rows = [], []
        self.series = QComboBox()
        names = store.series_names()
        if program is not None:  # only the series with an exam in this program or its categories
            inside = {f.id for f in store.folders() if f.id == program or f.parent == program}
            where = store.exam_folders()
            names = [n for n in names if any(where.get(i) in inside for i in store.series_exams(n))]
        self.series.addItems(names)
        if series:
            self.series.setCurrentText(series)
        self.series.currentTextChanged.connect(lambda _: self.refresh())
        self.best_of = QSpinBox(minimum=0, maximum=99, specialValueText="all tests", prefix="best ")
        self.best_of.setToolTip("Count only each student's best tests; the others are left out of the total")
        self.best_of.editingFinished.connect(self.save_settings)
        weights = QPushButton("Weights…", toolTip="Make a test count more, e.g. the final mock counting double")
        weights.clicked.connect(self.edit_weights)
        self.save = QPushButton("Series merit list (Excel)…", objectName="primary")
        self.save.clicked.connect(self.save_excel)
        top = QHBoxLayout()
        top.addWidget(QLabel("Series"))
        top.addWidget(self.series, 1)
        top.addWidget(QLabel("Count"))
        top.addWidget(self.best_of)
        top.addWidget(weights)
        top.addWidget(self.save)
        self.group = QComboBox()
        self.group.activated.connect(lambda _: self.fill())
        self.top_n = QSpinBox(minimum=0, maximum=100000, specialValueText="everyone", prefix="top ")
        self.top_n.valueChanged.connect(lambda _: self.fill())
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Show"))
        filters.addWidget(self.top_n)
        filters.addWidget(self.group)
        filters.addStretch()
        self.note = QLabel(objectName="muted", wordWrap=True)
        self.table = self._table()
        self.tests = self._table()
        self.sections = self._table()
        analysis = QVBoxLayout()
        analysis.addWidget(QLabel("Each test", objectName="muted"))
        analysis.addWidget(self.tests, 1)
        analysis.addWidget(QLabel("Each section, over every test (class average)", objectName="muted"))
        analysis.addWidget(self.sections, 1)
        page = QDialog()
        page.setLayout(analysis)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.table, "Leaderboard")
        self.tabs.addTab(page, "Analysis")
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.note)
        layout.addLayout(filters)
        layout.addWidget(self.tabs, 1)
        self.refresh()

    @staticmethod
    def _table() -> QTableWidget:
        t = QTableWidget()
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.verticalHeader().hide()
        return t

    def refresh(self):
        name = self.series.currentText()
        self.exams, self.rows, problems = series_results(self.store, name) if name else ([], [], [])
        settings = self.store.series_settings(name) if name else {"best_of": 0, "weights": {}}
        self.best_of.blockSignals(True)
        self.best_of.setValue(settings["best_of"])
        self.best_of.blockSignals(False)
        if self.exams:
            weighted = [w for w in settings["weights"].values() if w != 1]
            about = (f"{len(self.exams)} tests, ranked on the total score"
                     + (f" of each student's best {settings['best_of']}" if settings["best_of"] else "")
                     + (", some tests weighted" if weighted else "") + "; a test with no sheet scores nothing. "
                     "Average % is over the tests counted. Movement is the places gained or lost with the latest "
                     "test; Improvement is the latest test's % minus the first one's.")
        else:
            about = ("No exam is in a test series yet. Put exams in one on their Exam settings tab, or when making "
                     "them with New exam.")
        self.note.setText("\n".join([about] + [f"Not counted: {p}" for p in problems]))
        groups = sorted({g for r in self.rows for g in (r.batch, r.class_name) if g}, key=str.lower)
        self.group.clear()
        self.group.addItems([EVERYONE, *groups])
        self.fill()

    def fill(self):
        group = self.group.currentText()
        rows = [r for r in self.rows if group in (EVERYONE, "", r.batch, r.class_name)]
        if self.top_n.value():
            rows = [r for r in rows if r.rank <= self.top_n.value()]
        columns = ["Rank", "Roll number", "Name", "Class", "Batch", *self.exams, "Total", "Tests taken", "Average %",
                   "Movement", "Improvement %"]
        t = self.table
        t.setSortingEnabled(False)
        t.clear()
        t.setColumnCount(len(columns))
        t.setHorizontalHeaderLabels(columns)
        t.setRowCount(len(rows))
        for row, r in enumerate(rows):
            tests = ["absent" if s is None else f"{s:g}  (#{k})" + ("" if c else "  not counted")
                     for s, k, c in zip(r.scores, r.exam_ranks, r.counted)]
            values = [r.rank, r.roll_number, r.name, r.class_name, r.batch, *tests, r.total, r.taken, r.average,
                      movement(r.movement), r.improvement if r.improvement is not None else ""]
            for col, v in enumerate(values):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, v)
                t.setItem(row, col, item)
        t.setSortingEnabled(True)
        t.resizeColumnsToContents()
        summary = exam_summary(self.exams, rows)
        self._fill(self.tests, ["Test", "Students", "Average %", "Top %"], summary)
        names = list(dict.fromkeys(n for r in rows for n in r.sections))
        averages = []
        for n in names:
            p = [r.sections[n] for r in rows if n in r.sections]
            averages.append((n, round(sum(p) / len(p), 1), min(p), max(p)))
        self._fill(self.sections, ["Section", "Class average %", "Lowest %", "Highest %"], averages)
        self.save.setEnabled(bool(self.rows))

    @staticmethod
    def _fill(t: QTableWidget, columns: list[str], rows: list[tuple]):
        t.clear()
        t.setColumnCount(len(columns))
        t.setHorizontalHeaderLabels(columns)
        t.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, v in enumerate(values):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, v)
                t.setItem(row, col, item)
        t.resizeColumnsToContents()

    def save_settings(self, weights: dict[int, float] | None = None):
        name = self.series.currentText()
        if not name:
            return
        try:
            self.store.save_series_settings(name, self.best_of.value(), weights or {})
        except ValueError as e:
            QMessageBox.warning(self, "Not saved", str(e))
        self.refresh()

    def edit_weights(self):
        name = self.series.currentText()
        if not name:
            return
        ids = self.store.series_exams(name)
        current = self.store.series_settings(name)["weights"]
        dialog = QDialog(self)
        dialog.setWindowTitle("Weights")
        form = QFormLayout(dialog)
        form.addRow(QLabel("A test with weight 2 counts double in the total; 0 leaves it out.", objectName="muted"))
        spins = {}
        for i in ids:
            spins[i] = QDoubleSpinBox(minimum=0, maximum=10, decimals=2, singleStep=0.5, value=current[str(i)])
            form.addRow(self.store.exam(i).name, spins[i])
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            self.save_settings({i: s.value() for i, s in spins.items()})

    def save_excel(self):
        name = self.series.currentText()
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name).strip() or "series"
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Save series merit list", str(docs / f"{safe} merit list.xlsx"),
                                              "Excel (*.xlsx)")
        if not path:
            return
        ids = self.store.series_exams(name)
        institute = self.store.institute_for(ids[-1]) if ids else None  # the latest test's letterhead
        try:
            write_series_excel(path, name, self.exams, self.rows, institute)
        except OSError as e:  # e.g. the file is open in Excel
            QMessageBox.warning(self, "Couldn't save", f"{path}\n\n{e}")
            return
        QMessageBox.information(self, "Saved", f"Saved {path}")
