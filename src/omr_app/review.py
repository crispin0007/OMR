"""Review page: every item the reader flagged, on the sheet image, fixed with a click or a key (US2, FR-013)."""

import getpass
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QVBoxLayout, QWidget)

from omr_core.marking import mark_sheet
from omr_core.reader import SCALE
from omr_core.template import Grid, Template

from .dashboard import card
from .theme import tokens


def region(t: Template, item: str) -> tuple[Grid | None, tuple[float, float, float, float], tuple[float, ...]] | None:
    """The grid an item is on, the area to show around it and the part to highlight, in mm (x0, y0, x1, y1)."""
    bw, bh = t.bubble

    def box(g: Grid, r0: int, c0: int, r1: int, c1: int, pad: float) -> tuple[float, float, float, float]:
        (x0, y0), (x1, y1) = g.centre(r0, c0), g.centre(r1, c1)
        return x0 - bw / 2 - pad, y0 - bh / 2 - pad, x1 + bw / 2 + pad, y1 + bh / 2 + pad

    if item.startswith("Q") and item[1:].isdigit():
        q = int(item[1:])
        g = t.grid_for(q)
        if g and g.kind == "numeric":
            return g, box(g, 0, 0, g.rows - 1, g.cols - 1, 6), box(g, 0, 0, g.rows - 1, g.cols - 1, 1)
        if g:
            r = q - g.first
            around = box(g, max(r - 2, 0), 0, min(r + 2, g.rows - 1), g.cols - 1, 6)
            return g, around, box(g, r, 0, r, g.cols - 1, 1)
    kind = "set_code" if item == "set code" else "roll_number" if item.startswith("roll number") else None
    g = next((g for g in t.grids if g.kind == kind), None)
    if g is None and item == "roll number" and t.barcode:
        x, y, w, h = t.barcode
        return None, (x - 6, y - 6, x + w + 6, y + h + 6), (x, y, x + w, y + h)
    if g is None:
        return None
    whole = box(g, 0, 0, g.rows - 1, g.cols - 1, 1)
    if item.startswith("roll number digit "):
        c = int(item.rsplit(" ", 1)[1]) - 1
        return g, box(g, 0, 0, g.rows - 1, g.cols - 1, 6), box(g, 0, c, g.rows - 1, c, 1)
    return g, box(g, 0, 0, g.rows - 1, g.cols - 1, 6), whole


class ReviewPage(QWidget):
    def __init__(self, check):
        super().__init__()
        self.check = check
        self.user = getpass.getuser()
        self.items: list[tuple[int, str, str]] = []
        self.queue = QListWidget()
        self.queue.currentRowChanged.connect(self.show_item)
        self.count = QLabel(objectName="muted")

        self.where = QLabel(objectName="title")
        self.why = QLabel(objectName="muted")
        self.picture = QLabel(alignment=Qt.AlignCenter)
        self.picture.setMinimumHeight(220)
        self.read_as = QLabel()
        self.buttons = QHBoxLayout()
        self.error = QLabel(objectName="error")
        self.help = QLabel("Press a letter or digit to pick it, Delete for blank, Space to keep the reading.",
                           objectName="muted")
        item_card, item_layout = card("Item to check")
        for w in (self.where, self.why, self.picture, self.read_as):
            item_layout.addWidget(w)
        item_layout.addLayout(self.buttons)
        item_layout.addWidget(self.error)
        item_layout.addWidget(self.help)
        item_layout.addStretch()
        self.log = QListWidget()
        right = QSplitter(Qt.Vertical)
        right.addWidget(item_card)
        right.addWidget(card("Changes made", self.log)[0])
        right.setSizes([560, 160])

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.count)
        left_layout.addWidget(self.queue, 1)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([380, 760])
        layout = QVBoxLayout(self)
        layout.addWidget(split, 1)
        check.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        c = self.check
        keep = self.queue.currentRow()
        self.items = c.review_items() if c.exam else []
        self.queue.blockSignals(True)
        self.queue.clear()
        for i, item, why in self.items:
            sheet = c.sheets[i]
            self.queue.addItem(QListWidgetItem(f"{c.file_name(sheet)}  p{sheet.page}   {item}   ·  {why}"))
        self.queue.blockSignals(False)
        self.count.setText(f"{len(self.items)} to check" if self.items else
                           "Nothing to check. Results are ready." if c.sheets else "No sheets read yet.")
        self.log.clear()
        for at, user, file, page, item, before, after in reversed(c.store.audit(c.exam.id) if c.exam else []):
            self.log.addItem(f"{at.replace('T', ' ')}  {user}:  {Path(file).name}  p{page}  {item}  {before or 'blank'} → {after or 'blank'}")
        if self.items:
            self.queue.setCurrentRow(min(max(keep, 0), len(self.items) - 1))
            self.show_item(self.queue.currentRow())
        else:
            self.show_item(-1)

    def show_item(self, row: int):
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w:
                w.hide()  # deleted once the click that got us here has finished
                w.deleteLater()
        self.error.clear()
        if row < 0 or row >= len(self.items):
            self.where.setText("")
            self.why.setText("")
            self.picture.clear()
            self.read_as.clear()
            self.help.hide()
            return
        c = self.check
        i, item, why = self.items[row]
        sheet = c.sheets[i]
        self.where.setText(f"{c.file_name(sheet)}  page {sheet.page}  ·  {item}")
        self.why.setText(why)
        if sheet.result is None:
            self.picture.setText("This page couldn't be read. Scan it again, or import the scan again.")
            self.read_as.clear()
            self.help.hide()
            return
        self.help.show()
        t = c.exam.template
        found = region(t, item)
        self._show_picture(sheet.id, found)
        r = sheet.result
        if item.startswith("Q"):
            current = r.answers[int(item[1:])]
            self.read_as.setText(f"Read as: {current or 'blank'}")
            grid = found[0] if found else None
            if grid and grid.kind == "numeric":
                self._number_entry(item, current, grid.cols)
                return
            options = grid.options if grid else ""
            self._choice_buttons(item, list(options) + [""], keep=current if grid and (grid.multi or
                                                                                        len(current) <= 1) else None)
        elif item.startswith("roll number digit "):
            current = r.roll_number[int(item.rsplit(" ", 1)[1]) - 1]
            looks = c.suggestion(sheet)
            self.read_as.setText(f"Read as: {current}" + (f"   ·   The name written looks like {looks.name}, roll "
                                                          f"number {looks.roll_number}" if looks and c.misread(looks)
                                                          else ""))
            self._choice_buttons(item, list("0123456789"), keep=None if current == "?" else current)
        elif item == "set code":
            self.read_as.setText(f"Read as: {r.set_code}")
            options = found[0].options if found else ""
            self._choice_buttons(item, list(options), keep=None if r.set_code == "?" else r.set_code)
        else:  # the whole roll number, e.g. a duplicate
            student, looks = c.named.get(r.roll_number), c.suggestion(sheet)
            new = looks and not c.misread(looks)  # a directory student sitting under a roll number new to them
            self.read_as.setText(f"Read as: {r.roll_number}" + (f"  ({student.name})" if student else "") + (
                f"   ·   The name written looks like {looks.name}, " + (
                    f"Student ID {looks.roll_number}" if new else f"roll number {looks.roll_number}") if looks else ""))
            if new and "?" not in r.roll_number:
                put = QPushButton(f"{looks.name} is roll number {r.roll_number} in this exam", objectName="primary")
                put.clicked.connect(lambda: self.put_on_list(r.roll_number, looks))
                self.buttons.addWidget(put)
            digits = next((g.cols for g in t.grids if g.kind == "roll_number"), None)
            typed = looks.roll_number.zfill(digits or 0) if looks and not new and "?" in r.roll_number else r.roll_number
            edit = QLineEdit(typed.replace("?", ""), maxLength=digits or 40)
            save = QPushButton("Save roll number", objectName="primary")
            save.clicked.connect(lambda: self.fix(item, edit.text()))
            edit.returnPressed.connect(save.click)
            self.buttons.addWidget(edit)
            self.buttons.addWidget(save)
            self.buttons.addStretch()
            self.help.hide()

    def _number_entry(self, item: str, current: str, digits: int):
        """A box to type a numeric answer into, as no button per digit can give a number."""
        edit = QLineEdit(current.replace("?", ""), maxLength=digits, placeholderText="the number filled")
        save = QPushButton("Save number", objectName="primary")
        save.clicked.connect(lambda: self.fix(item, edit.text()))
        edit.returnPressed.connect(save.click)
        blank = QPushButton("Blank")
        blank.clicked.connect(lambda: self.fix(item, ""))
        for w in (edit, save, blank):
            self.buttons.addWidget(w)
        self.buttons.addStretch()
        self.help.hide()
        edit.setFocus()

    def _choice_buttons(self, item: str, choices: list[str], keep: str | None):
        for value in choices:
            b = QPushButton(value or "Blank")
            b.setMinimumWidth(56)
            b.setShortcut(QKeySequence(value or "Delete"))
            b.clicked.connect(lambda _=False, v=value: self.fix(item, v))
            self.buttons.addWidget(b)
        self.buttons.addSpacing(16)
        k = QPushButton("Keep as read", objectName="primary")
        k.setShortcut(QKeySequence("Space"))
        k.setEnabled(keep is not None)
        k.clicked.connect(lambda: self.fix(item, keep))
        self.buttons.addWidget(k)
        self.buttons.addStretch()

    def _show_picture(self, page_id: int, found):
        image = self.check.store.image(page_id)
        if image is None or found is None:
            self.picture.setText("No image saved for this page")
            return
        _, around, mark = found
        h, w = image.shape[:2]
        x0, y0, x1, y1 = (round(v * SCALE) for v in around)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        sheet = next((s for s in self.check.sheets if s.id == page_id), None)
        if sheet is not None and sheet.result is not None:  # the marking around it: is the bubble where it should be?
            key = self.check.keys.get(sheet.result.set_code, self.check.keys.get(""))
            image = mark_sheet(image, self.check.exam.template, sheet.result,
                               dict(zip(self.check.questions, key or [])), every_bubble=True)
        crop = image[y0:y1, x0:x1] if image.ndim == 3 else cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
        crop = np.ascontiguousarray(crop)
        accent = tokens()["accent"].lstrip("#")
        colour = tuple(int(accent[k:k + 2], 16) for k in (4, 2, 0))  # BGR
        mx0, my0, mx1, my1 = (round(v * SCALE) for v in mark)
        cv2.rectangle(crop, (mx0 - x0, my0 - y0), (mx1 - x0, my1 - y0), colour, 2)
        crop = np.ascontiguousarray(crop[:, :, ::-1])  # RGB for Qt
        q = QImage(crop.data, crop.shape[1], crop.shape[0], crop.strides[0], QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(q)
        self.picture.setPixmap(pix.scaled(min(pix.width() * 2, 720), min(pix.height() * 2, 360),
                                          Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def put_on_list(self, roll: str, student):
        self.check.put_on_list(roll, student)
        self.check.fill_table()  # the sheet now has its student, so it leaves the queue

    def fix(self, item: str, value: str | None):
        if value is None:
            return
        c = self.check
        i = self.items[self.queue.currentRow()][0]
        try:
            c.sheets[i] = c.store.correct(c.sheets[i].id, item, value, self.user)
        except ValueError as e:
            self.error.setText(str(e))
            return
        c.fill_table()  # re-scores, and through `changed` refreshes this queue on the next item
