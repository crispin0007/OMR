"""Scan page: read sheets as the scanner feeds them, as scanner software saves them into a folder, or from scan
files, and show each one live as it is read (US4).

Every page is read and saved the moment it arrives, so a jam, a crash or a power
cut never loses a page already scanned.
"""

import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSizePolicy, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from omr_core.grading import status
from omr_core.reader import SCALE, PageResult, read_or_reason
from omr_core.sources import is_blank, read_pages, ready_files
from omr_core.template import Template

from . import scanner, theme
from .dashboard import Tile, card
from .review import region

FOLDER = "A folder my scanner software saves into"
DPIS = ["200", "300", "150"]
NO_EXAM = "Open an exam on the Exams page first; scanned sheets are saved into it."
SCANS = "Scans (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)"
LIVE_COLUMNS = ["#", "Roll number", "Name", "Set", "Score", "To check"]
# BGR rings on the live sheet: right, wrong, read (no key yet, or roll number and set) and to check.
RIGHT, WRONG, READ, CHECK = (46, 125, 50), (40, 40, 211), (192, 101, 21), (0, 140, 255)


def marked_sheet(aligned: np.ndarray, t: Template, r: PageResult, key: dict[int, str]) -> np.ndarray:
    """The sheet as it was read: every filled bubble ringed (green right, red wrong, blue without a key) and
    every item to check boxed in orange."""
    out = cv2.cvtColor(aligned, cv2.COLOR_GRAY2BGR) if aligned.ndim == 2 else aligned.copy()
    radius = round(max(t.bubble) / 2 * SCALE) + 3

    def ring(g, row: int, col: int, colour):
        x, y = g.centre(row, col)
        cv2.circle(out, (round(x * SCALE), round(y * SCALE)), radius, colour, 3, cv2.LINE_AA)

    for g in t.grids:
        if g.kind == "questions":
            for row in range(g.rows):
                q = g.first + row
                answer = r.answers.get(q, "")
                colour = READ if q not in key else RIGHT if status(answer, key[q]) == "right" else WRONG
                for letter in answer:
                    if letter in g.options:
                        ring(g, row, g.options.index(letter), colour)
        elif g.kind == "roll_number":
            for col, digit in enumerate(r.roll_number[:g.cols]):
                if digit.isdigit():
                    ring(g, int(digit), col, READ)
        elif g.kind == "set_code" and r.set_code and r.set_code in g.options:
            ring(g, 0, g.options.index(r.set_code), READ)
    for where, _ in r.flags:
        found = region(t, where)
        if found:
            x0, y0, x1, y1 = (round(v * SCALE) for v in found[2])
            cv2.rectangle(out, (x0, y0), (x1, y1), CHECK, 4)
    return out


class ScanThread(QThread):
    """Pulls pages from the scanner and reads them off the UI thread; saving happens on the UI thread, at once."""

    page = Signal(object, object)  # the page, and what reading it gave (None for a blank back)
    stopped = Signal(str)  # "" when the feeder ran out, else what went wrong

    def __init__(self, device, dpi: int, duplex: bool, template):
        super().__init__()
        self.device, self.dpi, self.duplex, self.template = device, dpi, duplex, template
        self.stop = self.paused = False

    def run(self):
        try:
            for page in self.device.pages(self.dpi, self.duplex):
                blank = self.duplex and is_blank(page)
                self.page.emit(page, None if blank else read_or_reason(page, self.template))
                while self.paused and not self.stop:  # the next page isn't pulled from the feeder until resumed
                    self.msleep(100)
                if self.stop:
                    break
        except scanner.ScanStopped as e:
            self.stopped.emit(str(e))
            return
        self.stopped.emit("")


class ScanPage(QWidget):
    def __init__(self, check):
        super().__init__()
        self.check = check
        self.devices: list = []
        self.thread: ScanThread | None = None
        self.timer = QTimer(self, interval=1000)
        self.timer.timeout.connect(self.poll_folder)
        self.feeder = QTimer(self, interval=0)  # reads waiting files a page at a time, between window events
        self.feeder.timeout.connect(self.step)
        self.files: deque[str] = deque()  # folder files or imported files waiting to be read
        self.file_pages = None  # the pages of the file being read
        self.file_path = ""
        self.failed: list[str] = []
        self.paused = False
        self.sizes: dict[str, int] = {}
        self.done: set[str] = set()  # folder files handled this run, including all-blank and broken ones
        self.batch, self.count, self.started = "", 0, 0.0

        self.source = QComboBox()
        self.source.currentTextChanged.connect(self._show_options)
        refresh = QPushButton("Find scanners")
        refresh.clicked.connect(self.find_scanners)
        self.dpi = QComboBox()
        self.dpi.addItems(DPIS)
        self.duplex = QCheckBox("Both sides (skip blank backs)")
        self.folder = QLineEdit(placeholderText="Folder the scanner saves PDFs or images into")
        self.choose = QPushButton("Choose…")
        self.choose.clicked.connect(self.choose_folder)
        self.start_button = QPushButton("▶  Start scanning", objectName="primary")
        self.start_button.setStyleSheet("font-size: 13pt; padding: 8px 22px;")
        self.start_button.clicked.connect(self.start_or_explain)
        self.ready = QLabel(objectName="muted")  # whether a scanner was found
        self.pause_button = QPushButton("Pause")
        self.pause_button.setToolTip("Hold the feeder after this page, or the files still to read; Resume carries on")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)

        self.import_button = QPushButton("Import scans…")
        self.import_button.setToolTip("Read PDFs or images of sheets scanned earlier, shown here as they are read")
        self.import_button.clicked.connect(self.import_files)
        top = QHBoxLayout()
        top.addWidget(self.start_button)
        top.addWidget(self.pause_button)
        top.addWidget(self.stop_button)
        top.addSpacing(12)
        top.addWidget(self.ready, 1)
        top.addWidget(self.import_button)
        options = QGridLayout()
        options.addWidget(QLabel("Scanner"), 0, 0)
        options.addWidget(self.source, 0, 1)
        options.addWidget(refresh, 0, 2)
        options.addWidget(QLabel("Resolution (DPI)"), 1, 0)
        options.addWidget(self.dpi, 1, 1)
        options.addWidget(self.duplex, 1, 2)
        options.addWidget(QLabel("Folder"), 2, 0)
        options.addWidget(self.folder, 2, 1)
        options.addWidget(self.choose, 2, 2)
        options.setColumnStretch(1, 1)
        self.status = QLabel(wordWrap=True)

        self.scanned, self.read, self.to_check, self.same_roll, self.skipped, self.speed = (
            Tile(t, lambda: None) for t in ("Pages scanned", "Sheets read", "To check", "Same roll number",
                                            "Blank backs skipped", "Sheets a minute"))
        self.read.on_click = lambda: self.check.show_sheets(self._run_rows(), "from this scan")
        self.to_check.on_click = self.check.review_wanted.emit
        self.same_roll.on_click = self.check.review_wanted.emit
        tiles = QHBoxLayout()
        for t in (self.scanned, self.read, self.to_check, self.same_roll, self.skipped, self.speed):
            tiles.addWidget(t)

        self.latest = QLabel("Each sheet shows here as it is read, with the marks found ringed", objectName="muted")
        self.latest.setAlignment(Qt.AlignCenter)
        self.latest.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)  # the sheet fits the space, not the reverse
        self.latest.setMinimumHeight(240)
        self.latest_text = QLabel(objectName="muted", wordWrap=True)
        latest_card, latest_layout = card("Sheet being read", self.latest)
        latest_layout.addWidget(self.latest_text)
        latest_layout.addWidget(QLabel("Green: right · Red: wrong · Blue: read (no key yet, roll number, set) · "
                                       "Orange box: to check", objectName="muted", wordWrap=True))
        self.live = QTableWidget(0, len(LIVE_COLUMNS))
        self.live.setHorizontalHeaderLabels(LIVE_COLUMNS)
        self.live.verticalHeader().hide()
        self.live.setSelectionBehavior(QTableWidget.SelectRows)
        self.live.setSelectionMode(QTableWidget.SingleSelection)
        self.live.setEditTriggers(QTableWidget.NoEditTriggers)
        self.live.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.live.horizontalHeader().setStretchLastSection(True)
        self.live.cellClicked.connect(lambda row, _: self._show_sheet(self.live.item(row, 0).data(Qt.UserRole)))
        live_card, _ = card("Sheets read in this run (click one to see it)", self.live)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(latest_card)
        split.addWidget(live_card)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(options)
        layout.addWidget(self.status)
        layout.addLayout(tiles)
        layout.addWidget(split, 1)

        s = theme.settings()
        self.dpi.setCurrentText(str(s.value("scan/dpi", "200")))
        self.duplex.setChecked(str(s.value("scan/duplex", "true")) == "true")
        self.folder.setText(str(s.value("scan/folder", "")))
        self.find_scanners()
        self.source.setCurrentText(str(s.value("scan/source", self.source.currentText())))
        self._reset_counts()
        self._enable()

    # -- setup ------------------------------------------------------------------------------------------

    def find_scanners(self):
        self.devices = scanner.scanners()
        current = self.source.currentText()
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItems([d.name for d in self.devices] + [FOLDER])
        self.source.setCurrentText(current or self.source.itemText(0))
        self.source.blockSignals(False)
        self._show_options()
        if not self.devices:
            self.status.setText("No scanner found through Windows. Scan with your scanner's own software into a "
                                "folder and pick that folder here, or connect the scanner and press Find scanners.")

    def _show_options(self, *_):
        folder = self.source.currentText() == FOLDER
        for w in (self.folder, self.choose):
            w.setEnabled(folder)
        self.dpi.setEnabled(not folder)
        self.start_button.setText("▶  Start watching the folder" if folder else "▶  Start scanning")
        self.ready.setText(f"✓ Scanner ready: {self.source.currentText()}" if not folder
                           else "No scanner found through Windows" if not self.devices
                           else "Reading what scanner software saves into a folder")

    def start_or_explain(self):
        """Start, or say what's missing and offer the other ways in when there's no scanner or folder to use."""
        folder = self.folder.text().strip()
        if self.source.currentText() != FOLDER or folder and Path(folder).is_dir():
            self.start()
            return
        box = QMessageBox(QMessageBox.Information, "Start scanning",
                          ("No scanner was found through Windows. " if not self.devices else "")
                          + "Connect the scanner and turn it on, then press Find scanners. Or scan with the "
                          "scanner's own software into a folder and choose that folder here, or import scan files "
                          "(PDFs or images) you already have.", parent=self)
        actions = {box.addButton("Import scans…", QMessageBox.AcceptRole): self.import_files,
                   box.addButton("Choose folder…", QMessageBox.ActionRole): self.choose_folder,
                   box.addButton("Find scanners", QMessageBox.ActionRole): self.find_scanners}
        box.addButton(QMessageBox.Cancel)
        box.exec()
        chosen = actions.get(box.clickedButton())
        if chosen:
            chosen()

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Folder the scanner saves into", self.folder.text())
        if path:
            self.folder.setText(path)

    def _enable(self):
        running = self.running
        self.start_button.setEnabled(self.check.exam is not None and not running)
        self.import_button.setEnabled(self.check.exam is not None and not running)
        self.stop_button.setEnabled(running)
        self.pause_button.setEnabled(running)
        self.pause_button.setText("Resume" if self.paused else "Pause")
        for w in (self.source, self.dpi, self.duplex, self.folder, self.choose):
            w.setEnabled(not running)
        if not running:
            self._show_options()
        if self.check.exam is None and not running:
            self.status.setText(NO_EXAM)
        elif self.status.text() == NO_EXAM:
            self.status.clear()

    @property
    def running(self) -> bool:
        return self.timer.isActive() or self.thread is not None or self.reading_files

    @property
    def reading_files(self) -> bool:
        return bool(self.files) or self.file_pages is not None

    def _reset_counts(self):
        self.first = len(self.check.sheets)
        self.pages_seen = self.blank = self.count = 0
        self.started = time.monotonic()
        self.paused = False
        self.live.setRowCount(0)
        self._count()

    def _run_rows(self) -> list[int]:
        return list(range(self.first, len(self.check.sheets)))

    def _count(self):
        rows = self._run_rows()
        items = self.check.review_items()
        flagged = {i for i, _, _ in items}
        same = {i for i, _, why in items if why.startswith("same roll number")}
        minutes = (time.monotonic() - self.started) / 60
        self.scanned.set(str(self.pages_seen))
        self.read.set(str(len(rows)), "click to see them")
        self.to_check.set(str(sum(r in flagged for r in rows)), "click to review")
        self.same_roll.set(str(sum(r in same for r in rows)), "scanned twice, or a roll number misread")
        self.skipped.set(str(self.blank))
        self.speed.set(f"{len(rows) / minutes:.0f}" if len(rows) >= 2 and minutes > 0 else "–")

    # -- run --------------------------------------------------------------------------------------------

    def start(self):
        s = theme.settings()
        for key, value in (("source", self.source.currentText()), ("dpi", self.dpi.currentText()),
                           ("duplex", "true" if self.duplex.isChecked() else "false"),
                           ("folder", self.folder.text())):
            s.setValue(f"scan/{key}", value)
        self._reset_counts()
        when = f"{datetime.now():%d %b %H:%M:%S}"
        if self.source.currentText() == FOLDER:
            folder = Path(self.folder.text())
            if not self.folder.text().strip() or not folder.is_dir():  # Path("") is the current folder
                self.status.setText("Pick the folder your scanner software saves into.")
                return
            self.batch = f"{folder.name} folder  ·  {when}"
            self.sizes, self.done, self.failed = {}, set(), []
            self.timer.start()
            self.status.setText(f"Watching {folder}. Scan with your scanner's software; each file is read as soon "
                                "as it is saved, and files already there that this exam hasn't read are read too. "
                                "Press Stop when the stack is done.")
        else:
            device = self.devices[self.source.currentIndex()]
            self.batch = f"{device.name}  ·  {when}"
            self.thread = ScanThread(device, int(self.dpi.currentText()), self.duplex.isChecked(),
                                     self.check.exam.template)
            self.thread.page.connect(lambda page, read: self.add_page(page, read=read, blank=read is None))
            self.thread.stopped.connect(self.scan_stopped)
            self.thread.start()
            self.status.setText(f"Scanning from {device.name}…")
        self._enable()

    def import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import scanned sheets", "", SCANS)
        if paths:
            self.read_files(paths)

    def read_files(self, paths: list[str]):
        """Read scan files here, a page at a time, each shown as it is read."""
        self._reset_counts()
        # The time keeps two imports of the same files apart.
        self.batch = (Path(paths[0]).name + (f" and {len(paths) - 1} more" if len(paths) > 1 else "")
                      + f"  ·  {datetime.now():%d %b %H:%M:%S}")
        self.files, self.failed, self.done = deque(paths), [], set()
        self.status.setText(f"Reading {len(paths)} file{'s' if len(paths) > 1 else ''}…")
        self.feeder.start()
        self._enable()

    def step(self):
        """Read the next page of the files waiting: one page per call, so the window stays usable in between."""
        # shortcut: files are read on the window's thread, about 0.2 s a page; a thread like the scanner's would
        # keep a slow PC smoother. Upgrade if people see the window stutter while importing.
        if self.paused:
            self.feeder.stop()
            return
        if self.file_pages is None:
            if not self.files:
                self.feeder.stop()
                return
            self.file_path = self.files.popleft()
            self.file_pages = enumerate(read_pages(self.file_path), 1)
        try:
            n, page = next(self.file_pages)
        except StopIteration:
            n = page = None
        except (OSError, ValueError) as e:
            n = page = None
            name = Path(self.file_path).name
            self.failed.append(str(e) if name in str(e) else f"{name}: {e}")
            self.status.setText(f"Couldn't read {self.failed[-1]}. The other files carry on.")
        if page is None:
            self.file_pages = None
            if not self.files:
                self.feeder.stop()
                self._files_done()
            return
        self.add_page(page, self.file_path, n)

    def _files_done(self):
        self.check.show_sheets(None)  # also the count above the table
        if not self.timer.isActive():  # an import, not a watched folder
            self.status.setText(f"Done. {self._summary()}"
                                + (f" Couldn't read {'; '.join(self.failed)}." if self.failed else ""))
            self.check._enable()
        self._enable()

    def toggle_pause(self):
        self.paused = not self.paused
        if self.thread is not None:
            self.thread.paused = self.paused
        if self.paused:
            self.status.setText("Paused after this page. Press Resume to carry on.")
        else:
            self.status.setText("Carrying on…")
            if self.reading_files:
                self.feeder.start()
        self._enable()

    def stop(self):
        self.paused = False
        if self.thread is not None:
            self.thread.paused = False
            self.thread.stop = True  # stops after the page being fed
            self.status.setText("Stopping after this page…")
        if self.timer.isActive() or self.reading_files:
            left = len(self.files)  # the file being read keeps the pages read so far
            self.timer.stop()
            self.feeder.stop()
            self.files.clear()
            self.file_pages = None
            self.check.show_sheets(None)
            self.status.setText(f"Stopped. {self._summary()}"
                                + (f" {left} file{'s' if left > 1 else ''} not read." if left else ""))
        self._enable()

    def scan_stopped(self, problem: str):
        self.thread.wait()
        self.thread = None
        self.paused = False
        self.check.show_sheets(None)  # also the count above the table
        if problem:
            latest = self.check.sheets[-1] if len(self.check.sheets) > self.first else None
            roll = latest.result.roll_number if latest and latest.result else ""
            self.status.setText(f"{problem}. Every page scanned before that is saved"
                                + (f" (the last sheet read has roll number {roll})" if roll else "")
                                + ". Put the sheets that weren't scanned back on the feeder and press Start scanning.")
            self.status.setObjectName("error")
        else:
            self.status.setText(f"Feeder empty. {self._summary()}")
            self.status.setObjectName("")
        self.status.setStyleSheet("")
        self._enable()

    def _summary(self) -> str:
        rows = self._run_rows()
        return f"{len(rows)} sheets read, {self.to_check.value.text()} to check."

    def add_page(self, page, file: str = "", n: int = 0, read: tuple | None = None, blank: bool | None = None):
        """One page from the scanner or a file: skip a blank back, else read (unless the scanner's thread
        already did) and save it at once, then show it."""
        self.pages_seen += 1
        if blank if blank is not None else self.duplex.isChecked() and is_blank(page):
            self.blank += 1
            self._count()
            return
        self.count += 1
        stored = self.check.read_image(page, self.batch, file or self.batch.split("  ·  ")[0], n or self.count, read)
        self.check.refresh_soon()
        self._count()
        index = len(self.check.sheets) - 1
        self._add_live_row(index)
        self._show_sheet(index)

    def _add_live_row(self, index: int):
        stored = self.check.sheets[index]
        r = stored.result
        score = self.check.score_of(stored) if r else None
        checks = sum(1 for i, _, _ in self.check.review_items() if i == index)
        cells = [str(index - self.first + 1), r.roll_number if r else "", self.check.name_of(stored),
                 r.set_code if r else "", f"{score:g}" if score is not None else "",
                 "can't read" if r is None else str(checks) if checks else ""]
        row = self.live.rowCount()
        self.live.insertRow(row)
        warn = theme.tokens()["warn_bg"]
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setData(Qt.UserRole, index)
            if r is None or checks:
                item.setBackground(QColor(warn))
            self.live.setItem(row, col, item)
        self.live.scrollToBottom()

    def _show_sheet(self, index: int):
        """A sheet of this run on the live view, with what was read drawn on it."""
        stored = self.check.sheets[index]
        r = stored.result
        if r is None:
            self.latest.setText(f"Can't read this page: {stored.problem.removeprefix('unreadable: ')}.\nIt is kept "
                                "under Review. Scan it again flat, with all four corner marks on the paper.")
            self.latest_text.setText(f"{Path(stored.file).name}, page {stored.page}")
            return
        a = self.check.store.image(stored.id)
        if a is not None:
            key = r and self.check.keys.get(r.set_code, self.check.keys.get(""))
            drawn = marked_sheet(a, self.check.exam.template, r, dict(zip(self.check.questions, key or [])))
            image = QImage(drawn.data, drawn.shape[1], drawn.shape[0], drawn.strides[0], QImage.Format_BGR888).copy()
            self.latest.setPixmap(QPixmap.fromImage(image).scaled(
                self.latest.width(), max(self.latest.height() - 10, 240), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        score = self.check.score_of(stored)
        name = self.check.name_of(stored)
        self.latest_text.setText(f"Roll number {r.roll_number}" + (f" ({name})" if name else "")
                                 + f"   Set {r.set_code}   " + (f"Score {score:g}" if score is not None else "No key yet")
                                 + (f"   {len(r.flags)} to check" if r.flags else "")
                                 + (f"   Sheet No. {r.serial}" if r.serial else ""))

    def poll_folder(self):
        folder = self.folder.text()
        known = {s.file for s in self.check.sheets} | self.done
        try:
            files = ready_files(folder, known, self.sizes)
        except OSError as e:
            self.timer.stop()
            self.status.setText(f"Can't read the folder any more: {e}. Press Start watching the folder to try again.")
            self._enable()
            return
        for path in files:
            self.done.add(str(path))
            self.files.append(str(path))
        if files and not self.paused:
            self.feeder.start()
