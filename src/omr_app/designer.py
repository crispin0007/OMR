"""Sheet designer page: turn a scan of an existing sheet into a template (US5).

Open a scan, click the four corner marks, then drag a box around each block
of bubbles. The designer finds the bubbles, fills in rows and columns, and
saves a template JSON that the exam dialog can use.
"""

import json
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGraphicsScene, QGraphicsView,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox,
                               QSplitter, QVBoxLayout, QWidget)

from omr_core.designer import align, find_bubbles, fit_grid, marker_at
from omr_core.reader import SCALE, UnreadablePage, read_page
from omr_core.sources import read_pages
from omr_core.template import parse

from .dashboard import card
from .new_exam import USER_TEMPLATES
from .theme import tokens

PAGES = {"A4 (210 × 297 mm)": (210.0, 297.0), "Letter (216 × 279 mm)": (215.9, 279.4)}
CORNERS = ["top-left", "top-right", "bottom-right", "bottom-left"]
KINDS = {"Questions": "questions", "Roll number": "roll_number", "Set code": "set_code"}


class Canvas(QGraphicsView):
    """The scan, with clicks for corner marks and drags for bubble boxes."""

    clicked = Signal(float, float)
    boxed = Signal(QRectF)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.drag_boxes = False
        self.start = None
        self.band = None

    def show_image(self, gray: np.ndarray):
        self.scene().clear()
        self.band = None
        image = QImage(gray.data, gray.shape[1], gray.shape[0], gray.strides[0], QImage.Format_Grayscale8).copy()
        self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(0, 0, gray.shape[1], gray.shape[0])
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or not self.scene().items():
            return super().mousePressEvent(e)
        p = self.mapToScene(e.position().toPoint())
        if not self.drag_boxes:
            self.clicked.emit(p.x(), p.y())
            return
        self.start = p
        self.band = self.scene().addRect(QRectF(p, p), QPen(QColor(tokens()["accent"]), 2, Qt.DashLine))

    def mouseMoveEvent(self, e):
        if self.start is not None and self.band is not None:
            self.band.setRect(QRectF(self.start, self.mapToScene(e.position().toPoint())).normalized())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.start is not None and self.band is not None:
            rect = self.band.rect()
            self.scene().removeItem(self.band)
            self.band, self.start = None, None
            if rect.width() > 10 and rect.height() > 10:
                self.boxed.emit(rect)
            return
        super().mouseReleaseEvent(e)


class DesignerPage(QWidget):
    saved = Signal(str)  # path of a saved template

    def __init__(self):
        super().__init__()
        self.scan: np.ndarray | None = None  # BGR, as read
        self.gray: np.ndarray | None = None
        self.aligned: np.ndarray | None = None
        self.marks: list[tuple[float, float, float, str]] = []
        self.blocks: list[dict] = []
        self.sizes: list[tuple[float, float]] = []
        self.barcode: tuple[float, float, float, float] | None = None  # x, y, w, h in mm

        open_button = QPushButton("Open scan…", objectName="primary")
        open_button.clicked.connect(self.open_scan)
        self.page = QComboBox()
        self.page.addItems(list(PAGES))
        self.page.currentTextChanged.connect(lambda _: self.restart())
        self.dropout = QCheckBox("Sheet printed in red or pink (ignore that colour)")
        top = QHBoxLayout()
        top.addWidget(QLabel("Sheet designer", objectName="title"))
        top.addSpacing(16)
        top.addWidget(open_button)
        top.addWidget(QLabel("Paper"))
        top.addWidget(self.page)
        top.addWidget(self.dropout)
        top.addStretch()

        self.canvas = Canvas()
        self.canvas.clicked.connect(self.mark_clicked)
        self.canvas.boxed.connect(self.add_block)

        self.step = QLabel(wordWrap=True)
        self.error = QLabel(objectName="error", wordWrap=True)
        restart = QPushButton("Start corners again")
        restart.clicked.connect(self.restart)
        self.block_list = QListWidget()
        self.block_list.currentRowChanged.connect(self.show_block)
        self.kind = QComboBox()
        self.kind.addItems(list(KINDS))
        self.first = QSpinBox(minimum=1, maximum=999)
        self.options = QLineEdit()
        self.rows = QSpinBox(minimum=1, maximum=200)
        self.cols = QSpinBox(minimum=1, maximum=26)
        self.barcode_button = QPushButton("Box the barcode next", checkable=True)
        self.barcode_button.setToolTip("If the sheet has a barcode or QR code with the roll number, drag a box around it")
        remove = QPushButton("Remove block")
        remove.clicked.connect(self.remove_block)
        for w in (self.kind,):
            w.currentTextChanged.connect(self.edit_block)
        for w in (self.first, self.rows, self.cols):
            w.valueChanged.connect(self.edit_block)
        self.options.textEdited.connect(self.edit_block)
        form = QFormLayout()
        form.addRow("Kind", self.kind)
        form.addRow("First question", self.first)
        form.addRow("Options", self.options)
        form.addRow("Rows", self.rows)
        form.addRow("Columns", self.cols)
        form.addRow(remove)
        self.editor = QWidget()
        self.editor.setLayout(form)

        self.name = QLineEdit(placeholderText="Template name, e.g. School 100 questions")
        test = QPushButton("Test on this scan")
        test.clicked.connect(self.test_read)
        save = QPushButton("Save template…", objectName="primary")
        save.clicked.connect(self.save)
        self.test_result = QLabel(objectName="muted", wordWrap=True)

        steps_card, steps = card("Steps")
        steps.addWidget(self.step)
        steps.addWidget(self.error)
        steps.addWidget(restart)
        blocks_card, blocks = card("Bubble blocks")
        blocks.addWidget(self.block_list, 1)
        blocks.addWidget(self.editor)
        blocks.addWidget(self.barcode_button)
        save_card, save_layout = card("Save")
        save_layout.addWidget(self.name)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addWidget(save)
        save_layout.addLayout(row)
        save_layout.addWidget(self.test_result)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        for w in (steps_card, blocks_card, save_card):
            side_layout.addWidget(w)
        side_layout.setStretch(1, 1)
        split = QSplitter()
        split.addWidget(self.canvas)
        split.addWidget(side)
        split.setSizes([760, 380])
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        self.restart()

    # -- steps -------------------------------------------------------------------------------------------

    def open_scan(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open a scan of the sheet", "",
                                              "Scans (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if path:
            self.load_scan(path)

    def load_scan(self, path: str):
        try:
            self.scan = next(read_pages(path))
        except (OSError, ValueError, StopIteration) as e:
            QMessageBox.warning(self, "Can't open the scan", f"{path}\n\n{e or 'no pages'}")
            return
        self.gray = cv2.cvtColor(self.scan, cv2.COLOR_BGR2GRAY) if self.scan.ndim == 3 else self.scan
        if not self.name.text():
            self.name.setText(Path(path).stem)
        self.restart()

    def restart(self):
        """Back to clicking corner marks; keeps the scan."""
        self.marks, self.blocks, self.sizes, self.aligned, self.barcode = [], [], [], None, None
        self.barcode_button.setChecked(False)
        self.block_list.clear()
        self.editor.setEnabled(False)
        self.error.clear()
        self.test_result.clear()
        self.canvas.drag_boxes = False
        if self.gray is not None:
            self.canvas.show_image(self.gray)
        self._say()

    def _say(self):
        if self.gray is None:
            self.step.setText("1. Open a flat scan of a sheet you already print (blank or filled), the whole page, "
                              "at 150 to 300 DPI. To make a new sheet instead, start a New exam.")
        elif len(self.marks) < 4:
            self.step.setText(f"2. Click the {CORNERS[len(self.marks)]} corner mark ({len(self.marks)} of 4 done).")
        else:
            self.step.setText("3. Drag a box around each block of bubbles: every question column, the roll number "
                              "and the set code. Check rows and columns on the right. Scroll to zoom. If the roll number is "
                              "also a barcode or QR code, click Box the barcode next and box it.")

    @property
    def px_per_mm(self) -> float:
        return self.gray.shape[1] / PAGES[self.page.currentText()][0]  # the scan covers the whole page

    def mark_clicked(self, x: float, y: float):
        if self.gray is None or len(self.marks) >= 4:
            return
        found = marker_at(self.gray, x, y, self.px_per_mm)
        if found is None:
            self.error.setText("No corner mark found there. Click on the black square or ring in the corner itself. "
                               "Sheets without such corner marks can't be mapped; let New exam make a sheet "
                               "instead.")
            return
        self.error.clear()
        self.marks.append(found)
        mx, my, d, _ = found
        pen = QPen(QColor(tokens()["accent"]), 3)
        self.canvas.scene().addEllipse(mx - d / 2, my - d / 2, d, d, pen)
        if len(self.marks) == 4:
            self.aligned = align(self.gray, [m[:2] for m in self.marks], self.marks_mm(), PAGES[self.page.currentText()])
            self.canvas.show_image(self.aligned)
            self.canvas.drag_boxes = True
        self._say()

    def marks_mm(self) -> list[tuple[float, float]]:
        return [(round(m[0] / self.px_per_mm, 2), round(m[1] / self.px_per_mm, 2)) for m in self.marks]

    # -- blocks ------------------------------------------------------------------------------------------

    def add_block(self, rect: QRectF):
        box = (rect.left() / SCALE, rect.top() / SCALE, rect.right() / SCALE, rect.bottom() / SCALE)
        if self.barcode_button.isChecked():
            self.barcode_button.setChecked(False)
            self.barcode = tuple(round(v, 1) for v in (box[0], box[1], box[2] - box[0], box[3] - box[1]))
            self._redraw()
            return
        centres, size = find_bubbles(self.aligned, box)
        try:
            origin, pitch, rows, cols = fit_grid(centres, size)
        except ValueError as e:
            self.error.setText(f"{e}. Drag the box around the bubbles only, a little outside them.")
            return
        self.error.clear()
        kinds = [b["kind"] for b in self.blocks]
        if rows == 10 and "roll_number" not in kinds and cols <= 12:
            kind = "roll_number"
        elif rows == 1 and "set_code" not in kinds:
            kind = "set_code"
        else:
            kind = "questions"
        block = {"kind": kind, "origin_mm": list(origin), "pitch_mm": list(pitch), "rows": rows, "cols": cols}
        if kind != "roll_number":
            block["options"] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:cols]
        if kind == "questions":
            block["first"] = 1 + max((b["first"] + b["rows"] - 1 for b in self.blocks if b["kind"] == "questions"),
                                     default=0)
        self.blocks.append(block)
        self.sizes.append(size)
        self.block_list.addItem("")
        self.block_list.setCurrentRow(len(self.blocks) - 1)
        self._redraw()

    def show_block(self, row: int):
        self.editor.setEnabled(row >= 0)
        if row < 0:
            return
        b = self.blocks[row]
        for w in (self.kind, self.first, self.options, self.rows, self.cols):
            w.blockSignals(True)
        self.kind.setCurrentText(next(k for k, v in KINDS.items() if v == b["kind"]))
        self.first.setValue(b.get("first", 1))
        self.options.setText(b.get("options", ""))
        self.rows.setValue(b["rows"])
        self.cols.setValue(b["cols"])
        self.first.setEnabled(b["kind"] == "questions")
        self.options.setEnabled(b["kind"] != "roll_number")
        for w in (self.kind, self.first, self.options, self.rows, self.cols):
            w.blockSignals(False)

    def edit_block(self, *_):
        row = self.block_list.currentRow()
        if row < 0:
            return
        b = self.blocks[row]
        b["kind"] = KINDS[self.kind.currentText()]
        b["rows"], b["cols"] = self.rows.value(), self.cols.value()
        b.pop("first", None)
        b.pop("options", None)
        if b["kind"] != "roll_number":
            b["options"] = self.options.text().strip().upper() or "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:b["cols"]]
        if b["kind"] == "questions":
            b["first"] = self.first.value()
        self.show_block(row)
        self._redraw()

    def remove_block(self):
        row = self.block_list.currentRow()
        if row >= 0:
            del self.blocks[row]
            del self.sizes[row]
            self.block_list.takeItem(row)
            self._redraw()

    def _redraw(self):
        """Labels in the list and a dot on every bubble the template will read."""
        for i, b in enumerate(self.blocks):
            label = {"questions": lambda: f"Questions {b['first']} to {b['first'] + b['rows'] - 1}",
                     "roll_number": lambda: f"Roll number, {b['cols']} digits",
                     "set_code": lambda: f"Set code {b.get('options', '')}"}[b["kind"]]()
            self.block_list.item(i).setText(f"{label}   ({b['rows']} × {b['cols']})")
        self.canvas.show_image(self.aligned) if self.aligned is not None else None
        if self.barcode:
            x, y, w, h = (v * SCALE for v in self.barcode)
            self.canvas.scene().addRect(x, y, w, h, QPen(QColor(tokens()["accent"]), 3))
        brush = QBrush(QColor(tokens()["accent"]))
        r = 0.8 * SCALE
        for b in self.blocks:
            (ox, oy), (px, py) = b["origin_mm"], b["pitch_mm"]
            for row in range(b["rows"]):
                for col in range(b["cols"]):
                    x, y = (ox + col * px) * SCALE, (oy + row * py) * SCALE
                    self.canvas.scene().addEllipse(x - r, y - r, 2 * r, 2 * r, QPen(Qt.NoPen), brush)

    # -- result ------------------------------------------------------------------------------------------

    def template_dict(self) -> dict:
        if len(self.marks) < 4:
            raise ValueError("click the four corner marks first")
        if not any(b["kind"] == "questions" for b in self.blocks):
            raise ValueError("box at least one block of questions")
        shapes = [m[3] for m in self.marks]
        d = {
            "name": self.name.text().strip() or "Untitled sheet",
            "version": 1,
            "page_mm": list(PAGES[self.page.currentText()]),
            "markers": {"shape": max(set(shapes), key=shapes.count),
                        "size_mm": round(float(np.median([m[2] for m in self.marks])) / self.px_per_mm, 2),
                        "centres_mm": [list(m) for m in self.marks_mm()]},
            "bubble_mm": [round(float(np.median([s[i] for s in self.sizes])), 2) for i in (0, 1)],
            "grids": [dict(b) for b in self.blocks],
        }
        if self.dropout.isChecked():
            d["dropout"] = "red"
        if self.barcode:
            d["barcode_mm"] = list(self.barcode)
        parse(d)  # the reader's own checks: overlapping questions, points off the page, wrong roll rows
        return d

    def test_read(self):
        try:
            t = parse(self.template_dict())
            r = read_page(self.scan, t)
        except (ValueError, UnreadablePage) as e:
            self.test_result.setText(f"Can't read with this template yet: {e}")
            return
        answered = sum(1 for a in r.answers.values() if a)
        flags = "; ".join(f"{w}: {y}" for w, y in r.flags[:5]) + ("…" if len(r.flags) > 5 else "")
        self.test_result.setText(f"Read roll number {r.roll_number or '–'}, set {r.set_code or '–'}, "
                                 f"{answered} of {len(r.answers)} questions answered."
                                 + (f" To check: {flags}" if flags else " Nothing to check."))

    def save(self):
        try:
            d = self.template_dict()
        except ValueError as e:
            QMessageBox.warning(self, "Can't save yet", str(e))
            return
        USER_TEMPLATES.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in d["name"]).strip()
        path, _ = QFileDialog.getSaveFileName(self, "Save template", str(USER_TEMPLATES / f"{safe}.json"),
                                              "Templates (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(d, indent=2), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save", str(e))
            return
        self.saved.emit(path)
        QMessageBox.information(self, "Template saved", f"Saved {path}.\n\nPick it in New exam… on the Exams "
                                "page, or under an exam's Exam settings, Change sheet.")
