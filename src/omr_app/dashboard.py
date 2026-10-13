"""Dashboard and Results pages, and the charts they draw (spec 002 UI-002, UI-003, UI-006)."""

from collections.abc import Callable
from math import atan2, degrees

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout,
                               QWidget)

from omr_core.export import Graded, grade, write_excel, write_scorecards

from .theme import tokens


def card(title: str, body: QWidget | None = None) -> tuple[QWidget, QVBoxLayout]:
    w = QWidget(objectName="card")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.addWidget(QLabel(title, objectName="muted"))
    if body:
        layout.addWidget(body, 1)
    return w, layout


class Tile(QWidget):
    """A card with one big number that opens the sheets behind it when clicked."""

    def __init__(self, title: str, on_click: Callable[[], None]):
        super().__init__(objectName="card")
        self.setAttribute(Qt.WA_StyledBackground)  # a QWidget subclass draws its stylesheet background only with this
        self.on_click = on_click
        self.value, self.note = QLabel("0", objectName="value"), QLabel("", objectName="muted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        for w in (QLabel(title, objectName="muted"), self.value, self.note):
            layout.addWidget(w)
        self.setCursor(Qt.PointingHandCursor)

    def set(self, value: str, note: str = ""):
        self.value.setText(value)
        self.note.setText(note)

    def mousePressEvent(self, _):
        self.on_click()


class Ring(QWidget):
    """Sheets read cleanly against sheets to check; a click on a part opens those sheets."""

    def __init__(self, on_click: Callable[[str], None]):
        super().__init__()
        self.on_click = on_click
        self.parts: list[tuple[str, int, str]] = []  # (label, count, token)
        self.setMinimumSize(180, 180)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set(self, parts: list[tuple[str, int, str]]):
        self.parts = parts
        self.update()

    def _rect(self) -> QRectF:
        side = min(self.width(), self.height()) - 24
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    @staticmethod
    def _pen(colour: str, width: float) -> QPen:
        pen = QPen(QColor(colour), width)
        pen.setCapStyle(Qt.FlatCap)
        return pen

    def paintEvent(self, _):
        t, p = tokens(), QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r, total = self._rect(), sum(n for _, n, _ in self.parts)
        width = max(10, r.width() / 9)
        p.setPen(self._pen(t["border"], width))
        p.drawArc(r, 0, 360 * 16)
        start = 90 * 16
        for _, n, key in self.parts:
            if n:
                span = -round(360 * 16 * n / total)
                p.setPen(self._pen(t[key], width))
                p.drawArc(r, start, span)
                start += span
        p.setPen(QColor(t["text"]))
        f = p.font()
        f.setPointSizeF(f.pointSizeF() * 2)
        f.setBold(True)
        p.setFont(f)
        p.drawText(r, Qt.AlignCenter, str(total))
        p.end()

    def _part_at(self, pos) -> str | None:
        r, total = self._rect(), sum(n for _, n, _ in self.parts)
        if not total or not r.adjusted(-12, -12, 12, 12).contains(pos):
            return None
        clockwise = (90 - degrees(atan2(r.center().y() - pos.y(), pos.x() - r.center().x()))) % 360
        edge = 0.0
        for label, n, _ in self.parts:
            edge += 360 * n / total
            if clockwise < edge:
                return label
        return None

    def mouseMoveEvent(self, e):
        label = self._part_at(e.position())
        count = next((n for l, n, _ in self.parts if l == label), 0)
        self.setToolTip(f"{label}: {count}" if label else "")

    def mousePressEvent(self, e):
        label = self._part_at(e.position())
        if label:
            self.on_click(label)


class Histogram(QWidget):
    """How scores are spread; hover a bar for its range, click it to open those sheets."""

    BINS = 10

    def __init__(self, on_click: Callable[[list[int]], None]):
        super().__init__()
        self.on_click = on_click
        self.bins: list[list[int]] = []  # sheet indices per bar
        self.ranges: list[tuple[float, float]] = []
        self.setMinimumHeight(180)
        self.setMouseTracking(True)

    def set(self, scores: dict[int, float], low: float, high: float):
        """`scores` maps sheet index to score; bars split low..high evenly."""
        step = (high - low) / self.BINS or 1
        self.ranges = [(low + i * step, low + (i + 1) * step) for i in range(self.BINS)]
        self.bins = [[] for _ in range(self.BINS)]
        for i, s in scores.items():
            self.bins[min(max(int((s - low) / step), 0), self.BINS - 1)].append(i)
        self.update()

    def _bar(self, i: int) -> QRectF:
        w = (self.width() - 20) / self.BINS
        tallest = max(len(b) for b in self.bins) or 1
        h = (self.height() - 48) * len(self.bins[i]) / tallest
        return QRectF(10 + i * w + 3, self.height() - 24 - h, w - 6, h)

    def paintEvent(self, _):
        t, p = tokens(), QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not any(self.bins):
            p.setPen(QColor(t["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, "Scores appear here once there is an answer key")
            return
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["accent"]))
        for i in range(self.BINS):
            p.drawRoundedRect(self._bar(i), 4, 4)
        p.setPen(QColor(t["muted"]))
        for i, (lo, _) in enumerate(self.ranges):
            bar = self._bar(i)
            if self.bins[i]:
                p.drawText(QRectF(bar.left(), bar.top() - 20, bar.width(), 18), Qt.AlignCenter, str(len(self.bins[i])))
            p.drawText(QRectF(bar.left() - 4, self.height() - 20, 60, 20), Qt.AlignLeft, f"{lo:g}")
        p.drawText(QRectF(10, self.height() - 20, self.width() - 20, 20), Qt.AlignRight, f"{self.ranges[-1][1]:g}")
        p.end()

    def _index_at(self, pos) -> int | None:
        for i in range(len(self.bins)):
            bar = self._bar(i)
            if bar.left() <= pos.x() <= bar.right() and pos.y() >= 0:
                return i
        return None

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position())
        if i is not None:
            lo, hi = self.ranges[i]
            QToolTip.showText(e.globalPosition().toPoint(), f"{lo:g} to {hi:g}: {len(self.bins[i])} sheets", self)

    def mousePressEvent(self, e):
        i = self._index_at(e.position())
        if i is not None and self.bins[i]:
            self.on_click(self.bins[i])


class DashboardPage(QWidget):
    scan_wanted = Signal()

    def __init__(self, check):
        super().__init__()
        self.check = check
        everything = lambda: check.show_sheets(None)
        self.read = Tile("Sheets read", everything)
        self.average = Tile("Average score", everything)
        self.to_check = Tile("To check", self.open_to_check)
        self.batches = Tile("Batches", everything)
        self.ring = Ring(lambda label: self.open_to_check() if label == "To check" else self.open_clean())
        self.chart = Histogram(lambda rows: check.show_sheets(rows, "in this score range"))
        self.recent = QListWidget()
        self.recent.itemClicked.connect(self.open_batch)

        grid = QGridLayout(self)
        grid.setSpacing(14)
        title = QLabel("Dashboard", objectName="title")
        grid.addWidget(title, 0, 0, 1, 3)
        scan = QPushButton("▶  Start scanning", objectName="primary")
        scan.clicked.connect(self.scan_wanted.emit)
        grid.addWidget(scan, 0, 3, Qt.AlignRight)
        for col, tile in enumerate((self.read, self.average, self.to_check, self.batches)):
            grid.addWidget(tile, 1, col)
        ring_card, ring_layout = card("Read cleanly and to check", self.ring)
        self.legend = QLabel(objectName="muted")
        ring_layout.addWidget(self.legend)
        grid.addWidget(ring_card, 2, 0)
        grid.addWidget(card("Score distribution", self.chart)[0], 2, 1, 1, 3)
        grid.addWidget(card("Recent batches", self.recent)[0], 3, 0, 1, 4)
        grid.setRowStretch(2, 3)
        grid.setRowStretch(3, 2)
        check.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        c = self.check
        scores = {i: s for i, s in enumerate(c.score_of(sh) for sh in c.sheets) if s is not None}
        flagged = c.to_check()
        self.read.set(str(len(c.sheets)), f"{len(c.sheets) - len(flagged)} read cleanly")
        self.average.set(f"{sum(scores.values()) / len(scores):.1f}" if scores else "–",
                         f"out of {c.full_marks():g}" if scores else "type the answer key")
        self.to_check.set(str(len(flagged)), "click to review" if flagged else "nothing to check")
        self.batches.set(str(len(c.batches)))
        t = tokens()
        clean = len(c.sheets) - len(flagged)
        self.ring.set([("Read cleanly", clean, "good"), ("To check", len(flagged), "warn")])
        self.legend.setText(f"<span style='color:{t['good']}'>●</span> Read cleanly {clean}&nbsp;&nbsp; "
                            f"<span style='color:{t['warn']}'>●</span> To check {len(flagged)}")
        self.chart.set(scores, min(0.0, *scores.values()) if scores else 0, c.full_marks())
        self.recent.clear()
        for b in reversed(c.batches[-10:]):
            item = QListWidgetItem(f"{b.name}    {b.count} pages    {b.when:%H:%M}")
            item.setData(Qt.UserRole, list(range(b.start, b.start + b.count)))
            self.recent.addItem(item)
        if not c.batches:
            self.recent.addItem("No sheets yet. Open the exam to scan or import sheets.")
        self.update()

    def open_to_check(self):
        self.check.review_wanted.emit()

    def open_clean(self):
        flagged = set(self.check.to_check())
        self.check.show_sheets([i for i in range(len(self.check.sheets)) if i not in flagged], "read cleanly")

    def open_batch(self, item: QListWidgetItem):
        rows = item.data(Qt.UserRole)
        if rows:
            self.check.show_sheets(rows, f"from {item.text().split('    ')[0]}")


class ResultsPage(QWidget):
    COLUMNS = ["Rank", "Roll number", "Name", "Set", "Score", "Right", "Wrong", "Blank", "Percentile", "To check", "File",
               "Page"]

    def __init__(self, check):
        super().__init__()
        self.check = check
        self.graded: list[Graded] = []
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self.open_sheet)
        self.note = QLabel(objectName="muted")
        self.excel = QPushButton("Merit list (Excel)…", objectName="primary")
        self.excel.clicked.connect(lambda: self.export("Excel", "xlsx", write_excel))
        self.pdf = QPushButton("Scorecards (PDF)…")
        self.pdf.clicked.connect(lambda: self.export("PDF", "pdf", write_scorecards))
        top = QHBoxLayout()
        top.addStretch()
        top.addWidget(self.excel)
        top.addWidget(self.pdf)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.note)
        layout.addWidget(self.table, 1)
        check.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        c = self.check
        try:
            self.graded = grade(c.exam.template, c.sheets, c.key_edit.toPlainText(), c.correct.value(),
                                c.wrong.value(), c.blank.value(), c.students, c.sections,
                                written=c.written if c.exam.written_out_of else None, topics=c.topics) if c.exam else []
        except ValueError:
            self.graded = []  # the key doesn't fit yet; the Answer key tab says why
        self.note.setText("Ranked by score; equal scores share a rank. Double-click a row to open the sheet."
                          if self.graded else "Type the answer key on the Answer key tab to see results.")
        missing = sum(g.written is None for g in self.graded) if c.exam and c.exam.written_out_of else 0
        if missing:
            self.note.setText(self.note.text() + f" {missing} students have no written marks yet; type them on the "
                              "Written marks tab.")
        self.excel.setEnabled(bool(self.graded))
        self.pdf.setEnabled(bool(self.graded))
        self.table.setSortingEnabled(False)
        names = [s.name for s in c.sections]
        split = ["Sheet", "Written"] if c.exam and c.exam.written_out_of else []
        numbered = ["Sheet no."] if c.exam and c.exam.template.serial else []
        columns = self.COLUMNS[:5] + split + names + self.COLUMNS[5:] + numbered
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(len(self.graded))
        warn = QColor(tokens()["warn"])
        index = {p.id: i for i, p in enumerate(c.sheets)}
        for row, g in enumerate(self.graded):
            r = g.page.result
            values = [g.rank, r.roll_number, g.student.name if g.student else "", r.set_code, g.score,
                      *([g.omr, "" if g.written is None else g.written] if split else []), *g.sections.values(), g.right, g.wrong, g.blank, round(g.percentile, 1),
                      "yes" if g.to_check else "", c.file_name(g.page), g.page.page, *(r.serial for _ in numbered)]
            for col, v in enumerate(values):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, v)
                item.setData(Qt.UserRole, index[g.page.id])
                if g.to_check and columns[col] == "To check":
                    item.setForeground(warn)
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.AscendingOrder)
        self.table.resizeColumnsToContents()

    def export(self, kind: str, ext: str, write):
        c = self.check
        waiting = len(c.review_items())
        if waiting and QMessageBox.question(
                self, "Marks still to check",
                f"{waiting} items still need checking on Review, so some scores may change. Export anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        name = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in c.exam.name).strip() or "results"
        default = f"{name} {'merit list' if ext == 'xlsx' else 'scorecards'}.{ext}"
        path, _ = QFileDialog.getSaveFileName(self, f"Save {kind}", default, f"{kind} (*.{ext})")
        if not path:
            return
        try:
            write(path, c.exam.name, c.exam.template, self.graded)
        except OSError as e:  # e.g. the file is open in Excel
            QMessageBox.warning(self, "Couldn't save", f"{path}\n\n{e}")
            return
        self.window().statusBar().showMessage(f"Saved {path}", 5000)

    def open_sheet(self, row: int, _col: int):
        self.check.show_sheets(None)
        self.check.select(self.table.item(row, 0).data(Qt.UserRole))
