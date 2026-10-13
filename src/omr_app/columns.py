"""Choose which columns a results CSV has and in what order, remembered per exam."""

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from omr_core.export import ANSWERS

from . import theme


def arrange(available: list[str], saved: list[list]) -> list[tuple[str, bool]]:
    """The saved order and ticks for columns still available, then any new ones, ticked, in their default order."""
    known = {name: bool(on) for name, on in saved if name in available}  # a name saved twice counts once
    return list(known.items()) + [(name, True) for name in available if name not in known]


def _load(key: str) -> list[list]:
    try:
        saved = json.loads(theme.settings().value(key, "[]"))
        return [s for s in saved if isinstance(s, list) and len(s) == 2 and isinstance(s[0], str)]
    except (TypeError, ValueError):  # a hand-edited or damaged settings file: start from the default
        return []


class ColumnsDialog(QDialog):
    def __init__(self, parent, available: list[str], saved: list[list]):
        super().__init__(parent)
        self.setWindowTitle("Columns to save")
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.save = self.buttons.addButton("Save CSV…", QDialogButtonBox.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.itemChanged.connect(self._enable)
        self.fill(arrange(available, saved))
        moves = QVBoxLayout()
        for text, step in (("Move up", -1), ("Move down", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=step: self.move(s))
            moves.addWidget(b)
        moves.addSpacing(12)
        for text, on in (("Select all", True), ("Select none", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, o=on: self.tick_all(o))
            moves.addWidget(b)
        reset = QPushButton("Reset to default")
        reset.clicked.connect(lambda: self.fill(arrange(available, [])))
        moves.addWidget(reset)
        moves.addStretch()
        row = QHBoxLayout()
        row.addWidget(self.list, 1)
        row.addLayout(moves)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Tick the columns to save and drag them into order. {ANSWERS} adds one column per "
                                "question.", wordWrap=True))
        layout.addLayout(row, 1)
        layout.addWidget(self.buttons)
        self.resize(460, 520)

    def fill(self, columns: list[tuple[str, bool]]):
        self.list.blockSignals(True)
        self.list.clear()
        for name, on in columns:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            item.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._enable()

    def choice(self) -> list[tuple[str, bool]]:
        return [(self.list.item(i).text(), self.list.item(i).checkState() == Qt.Checked)
                for i in range(self.list.count())]

    def chosen(self) -> list[str]:
        return [name for name, on in self.choice() if on]

    def move(self, step: int):
        row = self.list.currentRow()
        if row < 0 or not 0 <= row + step < self.list.count():
            return
        self.list.insertItem(row + step, self.list.takeItem(row))
        self.list.setCurrentRow(row + step)

    def tick_all(self, on: bool):
        self.fill([(name, on) for name, _ in self.choice()])

    def _enable(self):
        self.save.setEnabled(bool(self.chosen()))


def pick_columns(parent, exam_id: int, available: list[str]) -> list[str] | None:
    """Ask for the columns, starting from this exam's last choice, and remember the new one; None if cancelled."""
    key = f"csv_columns/{exam_id}"
    dialog = ColumnsDialog(parent, available, _load(key))
    if not dialog.exec():
        return None
    theme.settings().setValue(key, json.dumps(dialog.choice()))
    return dialog.chosen()
