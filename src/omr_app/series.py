"""Test series: the combined merit list of the exams in a series, to see and save to Excel."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from omr_core.series import series_results, write_series_excel
from omr_core.store import Store


class SeriesDialog(QDialog):
    def __init__(self, parent, store: Store, series: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Test series")
        self.resize(900, 600)
        self.store = store
        self.exams, self.rows = [], []
        self.series = QComboBox()
        self.series.addItems(store.series_names())
        if series:
            self.series.setCurrentText(series)
        self.series.currentTextChanged.connect(self.refresh)
        self.save = QPushButton("Series merit list (Excel)…", objectName="primary")
        self.save.clicked.connect(self.save_excel)
        top = QHBoxLayout()
        top.addWidget(QLabel("Series"))
        top.addWidget(self.series, 1)
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
        name = self.series.currentText()
        self.exams, self.rows, problems = series_results(self.store, name) if name else ([], [], [])
        if self.exams:
            about = (f"{len(self.exams)} tests, ranked on the total score; a test with no sheet scores nothing. "
                     "Average % is over the tests taken.")
        else:
            about = ("No exam is in a test series yet. Put exams in one on their Exam settings tab, or when making "
                     "them with New exam.")
        self.note.setText("\n".join([about] + [f"Not counted: {p}" for p in problems]))
        columns = ["Rank", "Roll number", "Name", "Class", *self.exams, "Total", "Tests taken", "Average %"]
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(len(self.rows))
        for row, r in enumerate(self.rows):
            values = [r.rank, r.roll_number, r.name, r.class_name, *("absent" if s is None else s for s in r.scores),
                      r.total, r.taken, r.average]
            for col, v in enumerate(values):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, v)
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.save.setEnabled(bool(self.rows))

    def save_excel(self):
        name = self.series.currentText()
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name).strip() or "series"
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Save series merit list", str(docs / f"{safe} merit list.xlsx"),
                                              "Excel (*.xlsx)")
        if not path:
            return
        try:
            write_series_excel(path, name, self.exams, self.rows)
        except OSError as e:  # e.g. the file is open in Excel
            QMessageBox.warning(self, "Couldn't save", f"{path}\n\n{e}")
            return
        QMessageBox.information(self, "Saved", f"Saved {path}")
