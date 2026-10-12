"""Scan page: read sheets as the scanner feeds them, or as scanner software saves them into a folder (US4).

Every page is read and saved the moment it arrives, so a jam, a crash or a power
cut never loses a page already scanned.
"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from omr_core.sources import is_blank, read_pages, ready_files

from . import scanner, theme
from .dashboard import Tile, card

FOLDER = "A folder my scanner software saves into"
DPIS = ["200", "300", "150"]


class ScanThread(QThread):
    """Pulls pages from the scanner off the UI thread; reading and saving happen on the UI thread."""

    page = Signal(object)
    stopped = Signal(str)  # "" when the feeder ran out, else what went wrong

    def __init__(self, device, dpi: int, duplex: bool):
        super().__init__()
        self.device, self.dpi, self.duplex = device, dpi, duplex
        self.stop = False

    def run(self):
        try:
            for page in self.device.pages(self.dpi, self.duplex):
                self.page.emit(page)
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
        self.sizes: dict[str, int] = {}
        self.done: set[str] = set()  # folder files handled this run, including all-blank and broken ones
        self.batch, self.count = "", 0

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
        self.start_button = QPushButton("Scan", objectName="primary")
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)

        top = QHBoxLayout()
        top.addWidget(QLabel("Scan", objectName="title"))
        top.addStretch()
        top.addWidget(self.start_button)
        top.addWidget(self.stop_button)
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

        self.scanned, self.read, self.to_check, self.skipped = (
            Tile(t, lambda: None) for t in ("Pages scanned", "Sheets read", "To check", "Blank backs skipped"))
        self.read.on_click = lambda: self.check.show_sheets(self._run_rows(), "from this scan")
        self.to_check.on_click = self.check.review_wanted.emit
        tiles = QHBoxLayout()
        for t in (self.scanned, self.read, self.to_check, self.skipped):
            tiles.addWidget(t)
        self.latest = QLabel("The latest sheet shows here", objectName="muted")
        self.latest.setAlignment(Qt.AlignCenter)
        self.latest_text = QLabel(objectName="muted")
        latest_card, latest_layout = card("Latest sheet", self.latest)
        latest_layout.addWidget(self.latest_text)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(options)
        layout.addWidget(self.status)
        layout.addLayout(tiles)
        layout.addWidget(latest_card, 1)

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

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Folder the scanner saves into", self.folder.text())
        if path:
            self.folder.setText(path)

    def _enable(self):
        running = self.running
        self.start_button.setEnabled(self.check.exam is not None and not running)
        self.stop_button.setEnabled(running)
        for w in (self.source, self.dpi, self.duplex, self.folder, self.choose):
            w.setEnabled(not running)
        if not running:
            self._show_options()
        if self.check.exam is None and not running:
            self.status.setText("Open an exam on the Exams page first; scanned sheets are saved into it.")

    @property
    def running(self) -> bool:
        return self.timer.isActive() or self.thread is not None

    def _reset_counts(self):
        self.first = len(self.check.sheets)
        self.pages_seen = self.blank = 0
        self._count()

    def _run_rows(self) -> list[int]:
        return list(range(self.first, len(self.check.sheets)))

    def _count(self):
        rows = self._run_rows()
        flagged = set(self.check.to_check())
        self.scanned.set(str(self.pages_seen))
        self.read.set(str(len(rows)), "click to see them")
        self.to_check.set(str(sum(r in flagged for r in rows)), "click to review")
        self.skipped.set(str(self.blank))

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
            if not folder.is_dir():
                self.status.setText("Pick the folder your scanner software saves into.")
                return
            self.batch = f"{folder.name} folder  ·  {when}"
            self.sizes, self.done = {}, set()
            self.timer.start()
            self.status.setText(f"Watching {folder}. Scan with your scanner's software; each file is read as soon "
                                "as it is saved, and files already there that this exam hasn't read are read too. "
                                "Press Stop when the stack is done.")
        else:
            device = self.devices[self.source.currentIndex()]
            self.batch, self.count = f"{device.name}  ·  {when}", 0
            self.thread = ScanThread(device, int(self.dpi.currentText()), self.duplex.isChecked())
            self.thread.page.connect(self.add_page)
            self.thread.stopped.connect(self.scan_stopped)
            self.thread.start()
            self.status.setText(f"Scanning from {device.name}…")
        self._enable()

    def stop(self):
        if self.thread is not None:
            self.thread.stop = True  # stops after the page being fed
            self.status.setText("Stopping after this page…")
        if self.timer.isActive():
            self.timer.stop()
            self.status.setText(f"Stopped. {self._summary()}")
        self._enable()

    def scan_stopped(self, problem: str):
        self.thread.wait()
        self.thread = None
        if problem:
            latest = self.check.sheets[-1] if len(self.check.sheets) > self.first else None
            roll = latest.result.roll_number if latest and latest.result else ""
            self.status.setText(f"{problem}. Every page scanned before that is saved"
                                + (f" (the last sheet read has roll number {roll})" if roll else "")
                                + ". Put the sheets that weren't scanned back on the feeder and press Scan.")
            self.status.setObjectName("error")
        else:
            self.status.setText(f"Feeder empty. {self._summary()}")
            self.status.setObjectName("")
        self.status.setStyleSheet("")
        self._enable()

    def _summary(self) -> str:
        rows = self._run_rows()
        return f"{len(rows)} sheets read, {self.to_check.value.text()} to check."

    def add_page(self, page, file: str = "", n: int = 0):
        """One page from the scanner or a folder file: skip a blank back, else read and save it at once."""
        self.pages_seen += 1
        if self.duplex.isChecked() and is_blank(page):
            self.blank += 1
            self._count()
            return
        self.count += 1
        stored = self.check.read_image(page, self.batch, file or self.batch.split("  ·  ")[0], n or self.count)
        self.check.fill_table()
        self._count()
        self._show_latest(stored)

    def _show_latest(self, stored):
        r = stored.result
        if r is None:
            self.latest.setText(stored.problem)
            self.latest_text.setText("")
            return
        a = self.check.store.image(stored.id)
        if a is not None:
            image = QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format_Grayscale8).copy()
            self.latest.setPixmap(QPixmap.fromImage(image).scaledToHeight(
                max(self.latest.height() - 10, 240), Qt.SmoothTransformation))
        score = self.check.score_of(stored)
        name = self.check.name_of(stored)
        self.latest_text.setText(f"Roll number {r.roll_number}" + (f" ({name})" if name else "")
                                 + f"   Set {r.set_code}   " + (f"Score {score:g}" if score is not None else "No key yet")
                                 + (f"   {len(r.flags)} to check" if r.flags else ""))

    def poll_folder(self):
        folder = self.folder.text()
        known = {s.file for s in self.check.sheets} | self.done
        try:
            files = ready_files(folder, known, self.sizes)
        except OSError as e:
            self.timer.stop()
            self.status.setText(f"Can't read the folder any more: {e}. Press Scan to watch it again.")
            self._enable()
            return
        for path in files:
            self.done.add(str(path))
            try:
                for n, page in enumerate(read_pages(path), 1):
                    self.add_page(page, str(path), n)
            except (OSError, ValueError) as e:
                self.status.setText(f"Couldn't read {path.name}: {e}. The other files carry on.")
