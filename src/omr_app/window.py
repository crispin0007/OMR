"""Main window: a sidebar of pages; an exam opens into its own page with tabs, saved as it is read."""

import getpass
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QInputDialog,
                               QLabel, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog,
                               QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from omr_core.export import Graded, csv_columns, grade, single_questions, write_csv
from omr_core.grading import (BONUS, DROPPED, EITHER, Section, format_topics, full_marks, key_changes, marks_for,
                              parse_key, parse_topics, score)
from omr_core.marking import LEGEND
from omr_core.names import as_text, suggest
from omr_core.parallel import PageReader
from omr_core.reader import read_or_reason
from omr_core.sources import read_pages
from omr_core.store import Exam, Store, StoredPage, sheet_number_problems, to_review
from omr_core.students import Student, same_roll, with_directory

from . import theme
from .answer_key import KeyTab
from .columns import pick_columns
from .dashboard import DashboardPage, ResultsPage
from .directory import DirectoryPage
from .sending import SendingSettings
from .designer import DesignerPage
from .exam_page import ExamPage, ExamSettings, PrintSheet, StudentsTab, WrittenTab
from .exam_templates import TemplatesPage
from .exams import TEMPLATES, ExamsPage  # noqa: F401  (tests find the templates here)
from .help import HelpDialog
from .institutes import InstituteSettings
from .paths import data_dir
from .new_exam import Deduction
from .review import ReviewPage
from .scan import ScanPage, marked_sheet
from .sections import SectionsDialog

APP = "OMR Checker"

COLUMNS = ["File", "Page", "Roll number", "Name", "Set", "Answered", "Score", "Review", "Sheet no."]


@dataclass
class Batch:
    """One "Open sheets" action: sheets[start:start + count]."""
    name: str
    when: datetime
    start: int
    count: int


class CheckPage(QWidget):
    """The open exam's scanned sheets, with scores and what needs review.

    It also owns the exam's answer key and marks, shown on their own tabs as
    `key_tab` and `marks_tab`.
    """

    changed = Signal()  # sheets, key or marks changed
    wanted = Signal()  # another page asked to show sheets here
    review_wanted = Signal()  # another page asked for the review queue
    map_wanted = Signal()  # pages don't match the exam's sheet; map the one students used

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.exam: Exam | None = None
        self.logged_keys: dict[str, list[str]] | None = None  # the key as last logged, see _to_log
        self._marks_cache: tuple = (None, [])  # (what they were worked out from, marks), see `marks`
        self._scores: dict[int, tuple[StoredPage, float | None]] = {}  # see `score_of`
        self._scoring: tuple | None = None  # what the scores were worked out from
        self.questions: list[int] = []
        self.sheets: list[StoredPage] = []
        self.students: dict[str, Student] = {}  # the exam's own list
        self.named: dict[str, Student] = {}  # those, and the directory's student for any other roll number read
        self._suggested: dict[int, tuple] = {}  # page id: (what it was worked out from, the student or None)
        self.written: dict[str, float] = {}  # typed written marks by roll number
        self.keys: dict[str, list[str]] = {}
        self.sections: list[Section] = []
        self.topics: dict[int, str] = {}  # question: topic

        self.template_label = QLabel("Open or create an exam on the Exams page", objectName="muted")
        self.open_button = QPushButton("Import scans…", objectName="primary")
        self.open_button.setToolTip("Read PDFs or images of filled sheets")
        self.open_button.clicked.connect(self.open_sheets)
        self.save_button = QPushButton("Save CSV…")
        self.save_button.setToolTip("Pick the columns and their order, then save a CSV for Excel")
        self.save_button.clicked.connect(self.save_csv)
        top = QHBoxLayout()
        top.addWidget(self.template_label)
        top.addStretch()
        top.addWidget(self.open_button)
        top.addWidget(self.save_button)

        self.key_edit = QPlainTextEdit()
        self.key_edit.setPlaceholderText(
            "Answer key, one letter per question in order, e.g. ABDCA…\n"
            "One line per set: A: ABDC…   B: CADB…\n"
            "Separate with commas for more than one correct option: A, AC, B.  * = bonus, - = dropped.  "
            "A key shorter than the sheet counts only those questions.")
        self.key_edit.textChanged.connect(self.update_key)
        self.key_status = QLabel(objectName="muted", wordWrap=True)
        self.key_tab = KeyTab(self, self.key_edit, self.key_status)

        self.correct, self.wrong, self.blank = (self._marks(b) for b in (
            QDoubleSpinBox(minimum=-100, maximum=100, value=1, decimals=2, singleStep=0.25), Deduction(), Deduction()))
        marks = QHBoxLayout()
        for text, box in (("Correct", self.correct), ("Wrong", self.wrong), ("Blank", self.blank)):
            marks.addWidget(QLabel(text))
            marks.addWidget(box)
        marks.addStretch()
        self.sections_button = QPushButton("Sections…")
        self.sections_button.setToolTip("Give ranges of questions their own name and marks, e.g. Physics 1 to 50")
        self.sections_button.clicked.connect(self.edit_sections)
        self.sections_label = QLabel(objectName="muted", wordWrap=True)
        self.marks_tab = QWidget()
        marks_layout = QVBoxLayout(self.marks_tab)
        marks_layout.addWidget(QLabel("Marks for every question not in a section", objectName="muted"))
        marks_layout.addLayout(marks)
        marks_layout.addSpacing(12)
        marks_layout.addWidget(QLabel("Sections give ranges of questions their own name and marks, and results show "
                                      "a score per section.", objectName="muted", wordWrap=True))
        sections_row = QHBoxLayout()
        sections_row.addWidget(self.sections_button)
        sections_row.addWidget(self.sections_label, 1)
        marks_layout.addLayout(sections_row)
        marks_layout.addSpacing(12)
        marks_layout.addWidget(QLabel("Topics show each student's share right per topic on their scorecard and in the "
                                      "merit list's Topics sheet.", objectName="muted", wordWrap=True))
        self.topics_button = QPushButton("Topics…")
        self.topics_button.setToolTip("Give questions a topic each, e.g. 1-10: Kinematics")
        self.topics_button.clicked.connect(self.edit_topics)
        self.topics_label = QLabel(objectName="muted", wordWrap=True)
        topics_row = QHBoxLayout()
        topics_row.addWidget(self.topics_button)
        topics_row.addWidget(self.topics_label, 1)
        marks_layout.addLayout(topics_row)
        marks_layout.addStretch()

        self.filter_label = QLabel(objectName="muted")
        self.show_all = QPushButton("Show all")
        self.show_all.clicked.connect(lambda: self.show_sheets(None))
        self.move_button = QPushButton("Move to exam…")
        self.move_button.setToolTip("Move the selected pages to another exam on the same sheet")
        self.move_button.clicked.connect(self.move_selected)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.setToolTip("Delete the selected pages, e.g. a sheet scanned twice or into the wrong exam")
        self.delete_button.clicked.connect(self.delete_selected)
        self.names_button = QPushButton("Use names read")
        self.names_button.setToolTip("Save the names read from the handwriting on the selected sheets, as shown "
                                     "with a ?, to the student directory. Check them first.")
        self.names_button.clicked.connect(self.use_names_read)
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(self.filter_label)
        filter_bar.addWidget(self.show_all)
        filter_bar.addStretch()
        filter_bar.addWidget(self.names_button)
        filter_bar.addWidget(self.move_button)
        filter_bar.addWidget(self.delete_button)
        self.mismatch = QLabel(objectName="error", wordWrap=True)
        self.map_button = QPushButton("Map my printed sheet…")
        self.map_button.clicked.connect(self.map_wanted.emit)
        mismatch_bar = QHBoxLayout()
        mismatch_bar.addWidget(self.mismatch, 1)
        mismatch_bar.addWidget(self.map_button)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)  # Shift or Ctrl to pick several pages
        # The roll number and name are typed over in place; nothing else in the row can be.
        self.table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        self.table.setToolTip("Double-click a roll number or name, or press F2, to correct it")
        self.table.itemChanged.connect(self.edited)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_sheet)
        self.table.itemSelectionChanged.connect(self._enable)
        table_box = QWidget()
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addLayout(mismatch_bar)
        self.sheet_numbers = QLabel(objectName="error", wordWrap=True)  # repeated, missing or unreadable ones
        table_layout.addWidget(self.sheet_numbers)
        table_layout.addLayout(filter_bar)
        table_layout.addWidget(self.table, 1)

        self.page_view = QLabel("Select a sheet to see it", objectName="muted")
        self.page_view.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.page_view)
        scroll.setWidgetResizable(True)
        self.mark = QCheckBox("Mark the answers", checked=True,
                              toolTip="Green right, red wrong, blue the right answer missed, purple read with "
                                      "nothing to mark, orange to check")
        self.every_bubble = QCheckBox("Show every bubble position",
                                      toolTip="A thin circle where each bubble was read: each should sit on a "
                                              "printed bubble")
        for box in (self.mark, self.every_bubble):
            box.toggled.connect(lambda _: self.show_sheet())
        self.legend = QLabel(objectName="muted", wordWrap=True, textFormat=Qt.RichText)
        self.legend.setText("&nbsp;&nbsp; ".join(f'<span style="color: rgb({c[2]},{c[1]},{c[0]})">●</span>&nbsp;'
                                                 + text.replace(" ", "&nbsp;") for c, text in LEGEND))
        view = QWidget()
        view_layout = QVBoxLayout(view)
        view_layout.setContentsMargins(0, 0, 0, 0)
        marks_row = QHBoxLayout()
        marks_row.addWidget(self.mark)
        marks_row.addWidget(self.every_bubble)
        marks_row.addStretch()
        view_layout.addLayout(marks_row)
        view_layout.addWidget(self.legend)
        view_layout.addWidget(scroll, 1)
        self.review_list = QListWidget()
        self.answers_view = QPlainTextEdit(readOnly=True)
        side = QSplitter(Qt.Vertical)
        for w in (view, self.review_list, self.answers_view):
            side.addWidget(w)
        side.setSizes([500, 120, 120])
        split = QSplitter()
        split.addWidget(table_box)
        split.addWidget(side)
        split.setSizes([620, 480])

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(split, 1)

        self.refresh_timer = QTimer(self, singleShot=True, interval=1000)
        self.refresh_timer.timeout.connect(self.fill_table)
        self.show_sheets(None)
        self._enable()

    def _marks(self, box: QDoubleSpinBox) -> QDoubleSpinBox:
        box.valueChanged.connect(lambda _: self.scheme_changed())
        return box

    def _enable(self):
        for w in (self.open_button, self.key_edit, self.correct, self.wrong, self.blank, self.sections_button,
                  self.topics_button):
            w.setEnabled(self.exam is not None)
        self.save_button.setEnabled(bool(self.sheets))
        chosen = bool(self.selected())
        self.delete_button.setEnabled(chosen)
        self.names_button.setEnabled(chosen)
        self.move_button.setEnabled(chosen)

    def open_exam(self, exam_id: int | None):
        """Show an exam's saved key, marks and sheets; None closes it."""
        self.exam = None  # keeps the loading below from saving the scheme back
        if exam_id is None:
            self.questions, self.sheets, self.students, self.sections = [], [], {}, []
            self.named = {}
            self.written, self.topics = {}, {}
            self.template_label.setText("Open or create an exam on the Exams page")
            self.key_edit.clear()
        else:
            exam = self.store.exam(exam_id)
            t = exam.template
            self.questions = t.questions()
            self.sheets = self.store.pages(exam_id)
            self.students = self.store.students(exam_id)
            self._name()
            self.written = self.store.written(exam_id)
            self.sections = exam.sections
            self.topics = self.store.topics(exam_id)
            self.template_label.setText(f"{exam.name}  ·  {t.name}, {len(self.questions)} questions")
            for box, v in ((self.correct, exam.correct), (self.wrong, exam.wrong), (self.blank, exam.blank)):
                box.setValue(v)
            self.key_edit.setPlainText(exam.answer_key)
            self.exam = exam
        self.logged_keys = None  # the key as last logged; set from the opened exam's key, with nothing to log
        self.update_key()
        self.show_sheets(None)
        self._enable()

    def scheme_changed(self, changes: list[tuple[str, int, str, str]] = ()):
        if self.exam is not None:
            self.store.save_scheme(self.exam.id, self.key_edit.toPlainText(), self.correct.value(),
                                   self.wrong.value(), self.blank.value(), changes, getpass.getuser())
        self.fill_table()

    @property
    def batches(self) -> list[Batch]:
        out = []
        for i, s in enumerate(self.sheets):
            if out and out[-1].name == s.batch and out[-1].start + out[-1].count == i:
                out[-1].count += 1
            else:
                out.append(Batch(s.batch, datetime.fromisoformat(s.read_at), i, 1))
        return out

    @staticmethod
    def file_name(sheet: StoredPage) -> str:
        return Path(sheet.file).name

    @property
    def marks(self) -> list[tuple]:
        """Each question's marks, worked out again only when the exam, marks or sections change."""
        state = (self.exam and self.exam.id, len(self.questions), self.correct.value(), self.wrong.value(),
                 self.blank.value(), tuple(self.sections))
        if self._marks_cache[0] != state:
            self._marks_cache = (state, marks_for(self.questions, *state[2:5], self.sections,
                                            single_questions(self.exam.template) if self.exam else None))
        return self._marks_cache[1]

    def full_marks(self) -> float:
        key = next(iter(self.keys.values()), ["A"] * len(self.questions))  # sets differ only in order
        return full_marks(key, self.marks) + (self.exam.written_out_of if self.exam else 0)

    def edit_sections(self):
        dialog = SectionsDialog(self, self.sections, self.questions,
                                (self.correct.value(), self.wrong.value(), self.blank.value()))
        if not dialog.exec():
            return
        self.store.save_sections(self.exam.id, dialog.sections)
        self.sections = dialog.sections
        self.update_key()

    def edit_topics(self):
        text = format_topics(self.topics)
        while True:
            text, ok = QInputDialog.getMultiLineText(
                self, "Topics", "One line per topic: the questions, a colon and the topic, e.g.\n1-10: Kinematics\n"
                "11-15: Work and energy\n(two columns pasted from Excel work too). Questions left out have no topic.",
                text)
            if not ok:
                return
            try:
                topics = parse_topics(text, self.questions)
                break
            except ValueError as e:
                QMessageBox.warning(self, "Can't use those topics", str(e))
        self.store.set_topics(self.exam.id, topics)
        self.topics = topics
        self.update_key()

    def review_items(self) -> list[tuple[int, str, str]]:
        return to_review(self.sheets, self.students)

    def to_check(self) -> list[int]:
        """Sheets with anything to review: flags, unreadable pages, duplicate or unknown roll numbers."""
        return sorted({i for i, _, _ in self.review_items()})

    def _name(self):
        self.named = with_directory(self.students, self.store.directory(),
                                    {s.result.roll_number for s in self.sheets if s.result})

    def name_of(self, sheet: StoredPage) -> str:
        s = sheet.result and self.named.get(sheet.result.roll_number)
        return s.name if s else ""

    def suggestion(self, sheet: StoredPage) -> Student | None:
        """The directory's student whose name the handwriting fits, for a sheet whose roll number has no student;
        among those whose roll number fits when some digits couldn't be read."""
        r = sheet.result
        if not r or not r.name or self.name_of(sheet):
            return None
        students = self.store.directory()
        key = (r.roll_number, len(students), sum(len(s.name) for s in students))
        if self._suggested.get(sheet.id, (None,))[0] != key:
            self._suggested[sheet.id] = key, suggest(r.name, students, r.roll_number if "?" in r.roll_number else "")
        return self._suggested[sheet.id][1]

    def name_read(self, sheet: StoredPage) -> tuple[str, str]:
        """For a sheet with no student for its roll number: what to show for the name written, and why."""
        if not sheet.result or self.name_of(sheet):
            return "", ""
        s = self.suggestion(sheet)
        if s:
            return f"{s.name} ?", (f"The name written looks like {s.name}, roll number {s.roll_number} in the "
                                   "student directory. Check the roll number on Review.")
        text = as_text(sheet.result.name)
        return (f"{text} ?", "Read from the handwriting and not checked. Double-click to correct it, or select "
                "the rows and press Use names read.") if text else ("", "")

    def use_names_read(self):
        """Save the handwriting read as the name, for selected sheets with a whole roll number and no student."""
        saved = skipped = 0
        for i in self.selected():
            sheet = self.sheets[i]
            text, _ = self.name_read(sheet)
            if not text or self.suggestion(sheet) or "?" in sheet.result.roll_number:
                skipped += bool(sheet.result and not self.name_of(sheet))
                continue
            self.save_name(sheet.result.roll_number, text.removesuffix(" ?"))
            saved += 1
        self.fill_table()
        self.window().statusBar().showMessage(
            f"Saved {saved} name{'s' if saved != 1 else ''} read" + (f"; {skipped} left: fix the roll number or "
                                                                      "pick the student on Review first" if skipped
                                                                      else ""), 8000)

    def open_sheets(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open scanned sheets", "", "Scans (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if paths:
            self.read_files(paths)

    def read_files(self, paths: list[str]):
        failed = []
        # The time keeps two imports of the same files apart.
        batch = (Path(paths[0]).name + (f" and {len(paths) - 1} more" if len(paths) > 1 else "")
                 + f"  ·  {datetime.now():%d %b %H:%M:%S}")
        progress = QProgressDialog("Reading sheets…", "Stop", 0, len(paths), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(300)
        reader = PageReader(self.exam.template, skip_blank=False)
        for path in paths:
            reader.add(path)
        done: set[str] = set()
        while reader.busy and not progress.wasCanceled():
            QApplication.processEvents()
            got = reader.next(timeout=0.02)
            if got is None:
                continue
            path, pages = got
            if isinstance(pages, str):
                failed.append(pages if Path(path).name in pages else f"{Path(path).name}: {pages}")
            else:
                for n, page, _, read in pages:
                    progress.setLabelText(f"Reading {Path(path).name}, page {n}")
                    self.read_image(page, batch, path, n, read)
            done.add(path)
            progress.setValue(len(done))
        reader.stop()
        progress.close()
        self.show_sheets(None)
        self._enable()
        if failed:
            QMessageBox.warning(self, "Some files weren't read", "\n".join(failed))

    def read_image(self, page, batch: str, file: str, n: int, read: tuple | None = None) -> StoredPage:
        """Read one page image (unless `read` already holds what reading it gave) and save it at once; the
        caller refreshes the table."""
        result, problem = read or read_or_reason(page, self.exam.template)
        stored = self.store.add_page(self.exam.id, batch, file, n, result, problem, page)
        if stored.result:
            stored.result.aligned = None  # the image is in the store; don't keep every page in memory
        self.sheets.append(stored)
        return stored

    def read_again(self, template) -> dict[int, tuple] | None:
        """Every page of the exam read with `template`, for changing its sheet: from the original file while it
        is still there, else from the image saved for the page. None when stopped."""
        progress = QProgressDialog("Reading the pages again…", "Stop", 0, len(self.sheets), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(300)
        out = {}
        by_file = defaultdict(dict)
        for sheet in self.sheets:
            by_file[sheet.file][sheet.page] = sheet
        for file, wanted in by_file.items():
            # shortcut: an original file is trusted to be the one read before; a file replaced since would be
            # read in its place. Comparing it would need a fingerprint stored with every page.
            try:
                if Path(file).is_file():
                    for n, page in enumerate(read_pages(file), 1):
                        if n in wanted:
                            out[wanted.pop(n).id] = read_or_reason(page, template)
                            progress.setValue(len(out))
                            if progress.wasCanceled():
                                return None
            except (OSError, ValueError):
                pass  # read from the saved images below
            for sheet in wanted.values():
                image = self.store.image(sheet.id, as_saved=True)
                out[sheet.id] = (read_or_reason(image, template) if image is not None
                                 else (None, "unreadable: no scan of this page is kept; scan it again"))
                progress.setValue(len(out))
                if progress.wasCanceled():
                    return None
        progress.close()
        return out

    def update_key(self):
        names = list(dict.fromkeys(self.topics[q] for q in sorted(self.topics)))
        self.topics_label.setText(f"{len(names)} topics over {len(self.topics)} questions: {', '.join(names)}"
                                  if names else "No topics")
        self.sections_label.setText(", ".join(f"{s.name}: questions {s.first} to {s.last}, {s.correct:g} right, "
                                              f"{s.wrong:g} wrong" for s in self.sections) or "No sections")
        if self.exam is None:
            self.keys = {}
            self.key_status.setText("")
            self.key_tab.refresh()
            self.fill_table()
            return
        try:
            self.keys = parse_key(self.key_edit.toPlainText(), len(self.questions), self.exam.template.answer_options())
            text = (f"Key for {', '.join('set ' + s if s else 'all sets' for s in self.keys)}"
                    if self.keys else "Click the right answers below, or import a CSV, to see scores")
            counted = max((sum(k != "-" for k in key) for key in self.keys.values()), default=len(self.questions))
            if counted < len(self.questions):
                text += f", {counted} of {len(self.questions)} questions counted"
            self.key_status.setText(text)
            self.key_status.setObjectName("muted")
        except ValueError as e:
            self.keys = {}
            self.key_status.setText(str(e))
            self.key_status.setObjectName("error")
        self.key_status.setStyleSheet("")  # re-apply the theme for the new object name
        self.key_tab.refresh()
        self.scheme_changed(self._to_log())

    def _to_log(self) -> list[tuple[str, int, str, str]]:
        """Changes to the key since it was last logged, leaving out answers typed in for the first time."""
        if not self.keys:  # a key being typed that doesn't read yet: log it once it does
            return []
        before, self.logged_keys = self.logged_keys, self.keys
        if before is None:
            return []
        logged = {(c, q) for _, _, c, q, _, _ in self.store.key_log(self.exam.id)}
        return [(c, q, a, b) for c, q, a, b in key_changes(before, self.keys, self.questions)
                if not (a == DROPPED and b != BONUS and EITHER not in b and (c, q) not in logged)]

    def score_of(self, sheet: StoredPage) -> float | None:
        """The sheet's score, kept until the key, marks or written marks change, so the table, dashboard and
        live view work it out once."""
        known = self._scores.get(id(sheet))
        if known and known[0] is sheet:
            return known[1]
        self._scores[id(sheet)] = (sheet, value := self._score(sheet))
        return value

    def _score(self, sheet: StoredPage) -> float | None:
        r = sheet.result
        key = r and self.keys.get(r.set_code, self.keys.get(""))
        if not key:
            return None
        written = self.written.get(r.roll_number, 0) if self.exam.written_out_of else 0
        return score([r.answers[q] for q in self.questions], key, marks=self.marks) + written

    def _score_text(self, sheet: StoredPage) -> str:
        s = self.score_of(sheet)
        if s is not None:
            return f"{s:g}"
        return "no key for set " + sheet.result.set_code if sheet.result and self.keys else ""

    def refresh_soon(self):
        """Refresh the table within a second; while a stack is scanned, at most once a second."""
        if not self.refresh_timer.isActive():
            self.refresh_timer.start()

    def fill_table(self):
        self.refresh_timer.stop()
        _ = self.marks  # brings the marks up to date, and with them what they were worked out from
        scoring = (self.key_edit.toPlainText(), self._marks_cache[0], sorted(self.written.items()))
        if scoring != self._scoring:  # a corrected sheet is a new object, so only it is scored again
            self._scores.clear()
            self._scoring = scoring
        self._name()
        self.table.blockSignals(True)  # filling it isn't a person typing
        self.table.clearSpans()
        self.table.setRowCount(len(self.sheets))
        review_bg = QBrush(QColor(theme.tokens()["warn_bg"]))
        items = Counter(i for i, _, _ in self.review_items())
        for row, sheet in enumerate(self.sheets):
            r = sheet.result
            review = sheet.problem or (f"{items[row]} to check" if items[row] else "")
            cells = [self.file_name(sheet), str(sheet.page), r.roll_number if r else "", self.name_of(sheet),
                     r.set_code if r else "",
                     f"{sum(1 for q in self.questions if r.answers[q])}/{len(self.questions)}" if r else "",
                     self._score_text(sheet), review, r.serial if r else ""]
            read, why = self.name_read(sheet) if not cells[3] else ("", "")
            if read:
                cells[3] = read
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if read and COLUMNS[col] == "Name":
                    item.setToolTip(why)
                    item.setForeground(QColor(theme.tokens()["muted"]))
                    font = item.font()
                    font.setItalic(True)
                    item.setFont(font)
                if not (r and COLUMNS[col] in ("Roll number", "Name")):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if review:
                    item.setBackground(review_bg)
                self.table.setItem(row, col, item)
            if r is None:  # say why across the row instead of leaving it empty
                self.table.item(row, 2).setText(f"Can't read this page: {sheet.problem.removeprefix('unreadable: ')}")
                self.table.setSpan(row, 2, 1, 5)
        self.table.blockSignals(False)
        unreadable = sum(s.result is None for s in self.sheets)
        self.mismatch.setText(
            f"{unreadable} of {len(self.sheets)} pages couldn't be read. If students filled a sheet other than this "
            "exam's (for example one you print yourself), map that sheet, then pick it under Exam settings, "
            "Change sheet; every page is read again." if unreadable else "")
        for w in (self.mismatch, self.map_button):
            w.setVisible(bool(unreadable))
        numbered = bool(self.exam and self.exam.template.serial)
        self.table.setColumnHidden(COLUMNS.index("Sheet no."), not numbered)
        self.sheet_numbers.setText(sheet_number_problems(self.sheets) if numbered else "")
        self.sheet_numbers.setVisible(bool(self.sheet_numbers.text()))
        self.table.resizeColumnsToContents()
        self.changed.emit()

    def edited(self, item: QTableWidgetItem):
        """A roll number or name typed over in the table: saved at once, like a correction on Review."""
        sheet, column = self.sheets[item.row()], COLUMNS[item.column()]
        text = " ".join(item.text().split()).removesuffix(" ?")
        roll = sheet.result.roll_number
        try:
            if column == "Roll number":
                grid = next((g for g in self.exam.template.grids if g.kind == "roll_number"), None)
                if grid and text.isdigit() and len(text) < len(roll):  # "16" for "0016?"
                    text = text.zfill(len(roll))
                if text != roll:
                    self.sheets[item.row()] = self.store.correct(sheet.id, "roll number", text, getpass.getuser())
            elif text != self.name_of(sheet):
                self.save_name(roll, text)
        except ValueError as e:
            QMessageBox.warning(self, "Can't save that", str(e))
        QTimer.singleShot(0, self.fill_table)  # after the editor closes; puts back what was there if not saved

    def save_name(self, roll: str, name: str):
        """The student's name for this roll number, in the directory and, when the exam has a list, in it too."""
        if "?" in roll:
            raise ValueError("correct the roll number first: it has digits that couldn't be read")
        if not name:
            raise ValueError("the student needs a name")
        known = next((s for s in self.store.directory() if same_roll(s.roll_number) == same_roll(roll)), None)
        self.store.save_student(replace(known, name=name) if known else Student(roll, name),
                                known.roll_number if known else "")
        if self.students:
            self.students[roll] = replace(self.students.get(roll) or Student(roll, name), name=name)
            self.store.set_students(self.exam.id, list(self.students.values()))
        self.window().statusBar().showMessage(f"Saved {name} as roll number {roll}", 5000)

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
        a = self.store.image(sheet.id)
        if a is None:
            self.page_view.setText("No image saved for this page")
            return
        key = self.keys.get(r.set_code, self.keys.get(""))
        if self.mark.isChecked() or self.every_bubble.isChecked():
            a = marked_sheet(a, self.exam.template, r, dict(zip(self.questions, key or [])) if self.mark.isChecked()
                             else {}, self.every_bubble.isChecked())
            image = QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format_BGR888).copy()
        else:
            image = QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format_Grayscale8).copy()
        self.page_view.setPixmap(QPixmap.fromImage(image).scaledToWidth(
            max(self.page_view.width() - 20, 300), Qt.SmoothTransformation))
        self.review_list.addItems([f"{where}: {why}" for where, why in r.flags] or ["Nothing to check"])
        self.answers_view.setPlainText("   ".join(f"{q}:{r.answers[q] or '·'}" for q in self.questions))

    def selected(self) -> list[int]:
        """Rows of the selected pages that are shown."""
        rows = self.table.selectionModel().selectedRows()
        return sorted(i.row() for i in rows if not self.table.isRowHidden(i.row()))

    def _after_removing(self, rows: list[int], text: str):
        gone = {self.sheets[r].id for r in rows}
        self.sheets = [s for s in self.sheets if s.id not in gone]
        self.table.clearSelection()
        self.show_sheets(None)
        self._enable()
        self.page_view.setText(text)
        self.answers_view.clear()
        self.review_list.clear()

    def delete_selected(self):
        rows = self.selected()
        pages = f"{len(rows)} page{'s' if len(rows) != 1 else ''}"
        if not rows or QMessageBox.question(
                self, "Delete pages", f"Delete {pages} from “{self.exam.name}”, with any corrections made to them? "
                "This can't be undone; the scan files themselves are kept.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.store.delete_pages([self.sheets[r].id for r in rows])
        self._after_removing(rows, f"Deleted {pages}")

    def move_selected(self):
        rows = self.selected()
        others = [(i, name) for i, name, *_ in self.store.exams()
                  if i != self.exam.id and self.store.same_sheet(self.exam.id, i)]
        if not rows:
            return
        if not others:
            QMessageBox.information(self, "Move pages", "No other exam uses this sheet. Pages can only move to an "
                                    "exam on the same sheet; for another sheet, import the original scans there.")
            return
        name, ok = QInputDialog.getItem(self, "Move pages", f"Move {len(rows)} page{'s' if len(rows) != 1 else ''} "
                                        "to:", [n for _, n in others], 0, False)
        if not ok:
            return
        target = next(i for i, n in others if n == name)
        try:
            self.store.move_pages([self.sheets[r].id for r in rows], target)
        except ValueError as e:
            QMessageBox.warning(self, "Can't move them", str(e))
            return
        self._after_removing(rows, f"Moved {len(rows)} page{'s' if len(rows) != 1 else ''} to “{name}”")

    def graded(self) -> list[Graded]:
        """Every page that can be scored, best first; none while the key doesn't fit the sheet."""
        if not self.exam:
            return []
        try:
            return grade(self.exam.template, self.sheets, self.key_edit.toPlainText(), self.correct.value(),
                         self.wrong.value(), self.blank.value(), self.named, self.sections,
                         written=self.written if self.exam.written_out_of else None, topics=self.topics)
        except ValueError:
            return []  # the Answer key tab says why

    def save_csv(self):
        available = csv_columns(self.exam.template, [s.name for s in self.sections], bool(self.exam.written_out_of))
        columns = pick_columns(self, self.exam.id, available)
        if columns is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save results", "results.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            write_csv(path, self.exam.template, self.sheets, self.graded(), self.named, columns)
        except OSError as e:  # e.g. the file is open in Excel
            QMessageBox.warning(self, "Couldn't save", str(e))
            return
        self.window().statusBar().showMessage(f"Saved {len(self.sheets)} rows to {path}", 5000)


class MainWindow(QMainWindow):
    PAGES = ["Dashboard", "Exams", "Student directory", "Templates", "Map printed sheet", "Question Bank", "Syllabus", "Settings"]
    LATER = {"Question Bank": "Comes in phase 2", "Syllabus": "Comes in phase 3"}

    def __init__(self, db_path: str | Path | None = None):
        super().__init__()
        self.setWindowTitle(APP)
        self.prefs = theme.load_prefs()
        if db_path is None:
            db_path = data_dir() / "omr.db"
        self.store_path = Path(db_path)
        self.store = Store(db_path)
        self.check = CheckPage(self.store)
        self.exams = ExamsPage(self.store)
        self.exams.purged = self.store.purge_trash()
        self.exams.opened.connect(self.open_exam)
        self.dashboard = DashboardPage(self.check)
        self.results = ResultsPage(self.check)
        self.review = ReviewPage(self.check)
        self.scan = ScanPage(self.check)
        self.check.changed.connect(self.scan._enable)
        self.students = StudentsTab(self.check)
        self.students.changed.connect(self.reload_students)
        self.written = WrittenTab(self.check)
        self.written.changed.connect(self.check.fill_table)  # rescores; Results and the Dashboard follow
        self.print_sheet = PrintSheet(self.check)
        self.exam_settings = ExamSettings(self.check)
        self.exam_settings.changed.connect(lambda: self.open_exam(self.check.exam.id))
        self.exam_settings.deleted.connect(lambda: self.open_exam(None))
        self.exam_settings.duplicated.connect(self.open_exam)
        self.exam_settings.archived.connect(lambda: self.exams.refresh())
        self.exam_page = ExamPage(self.check, [
            ("Scan", self.scan), ("Scanned sheets", self.check), ("Review", self.review),
            ("Answer key", self.check.key_tab), ("Marks and sections", self.check.marks_tab),
            ("Students", self.students), ("Written marks", self.written), ("Results", self.results),
            ("Print sheet", self.print_sheet),
            ("Exam settings", self.exam_settings)])
        self.exam_page.back.connect(lambda: self.go("Exams"))
        self.exam_page.scan_wanted.connect(self.start_scanning)
        self.dashboard.scan_wanted.connect(self.start_scanning)
        self.exams_area = QStackedWidget()  # the list of exams, or one exam's page
        self.exams_area.addWidget(self.exams)
        self.exams_area.addWidget(self.exam_page)
        self.templates = TemplatesPage(self.store)
        self.directory = DirectoryPage(self.store)
        self.designer = DesignerPage()
        self.settings = theme.SettingsPage(self.prefs)
        self.settings.form.addRow("Institute", InstituteSettings(self.store, self.institute_changed))
        self.settings.form.addRow("Send results", SendingSettings())
        self.settings.changed.connect(self.apply_prefs)
        self.pages = {"Dashboard": self.dashboard, "Exams": self.exams_area, "Student directory": self.directory,
                      "Templates": self.templates,
                      "Map printed sheet": self.designer, "Settings": self.settings}

        self.stack = QStackedWidget()
        sidebar = QWidget(objectName="sidebar")
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(10, 16, 10, 16)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(QPixmap(str(Path(__file__).with_name("icon.png"))).scaledToHeight(
            30, Qt.SmoothTransformation))
        brand.addWidget(mark)
        name = QLabel(APP)
        name.setStyleSheet("font-size: 15pt; font-weight: 700;")
        brand.addWidget(name, 1)
        nav.addLayout(brand)
        nav.addSpacing(12)
        self.nav = QButtonGroup(self)
        self.nav_buttons = {}
        for name in self.PAGES:
            b = QPushButton(name, objectName="nav", checkable=True)
            if name in self.LATER:
                b.setEnabled(False)
                b.setToolTip(self.LATER[name])
            else:
                self.stack.addWidget(self.pages[name])
                b.clicked.connect(lambda _=False, n=name: self.go(n))
            self.nav.addButton(b)
            self.nav_buttons[name] = b
            if name == "Settings":
                nav.addStretch()
                help_button = QPushButton("Help", objectName="nav")
                help_button.setToolTip("Getting started, shortcuts and where your data is (F1)")
                help_button.clicked.connect(self.show_help)
                nav.addWidget(help_button)
            nav.addWidget(b)
        self.theme_button = QPushButton(objectName="nav")
        self.theme_button.clicked.connect(self.toggle_theme)
        nav.addWidget(self.theme_button)
        sidebar.setFixedWidth(190)

        self.check.wanted.connect(lambda: self.go("Scanned sheets"))
        self.check.review_wanted.connect(lambda: self.go("Review"))
        self.check.map_wanted.connect(lambda: self.go("Map printed sheet"))
        self.designer.new_exam_wanted.connect(self.new_exam)
        self.check.changed.connect(self.exams.refresh)
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)
        layout.addWidget(sidebar)
        # Pages scroll rather than set the window's smallest size, so it fits a laptop screen at 150% scaling.
        pages = QScrollArea(widgetResizable=True, frameShape=QScrollArea.NoFrame)
        pages.setWidget(self.stack)
        layout.addWidget(pages, 1)
        self.setCentralWidget(central)
        for keys, action in (("Ctrl+N", self.new_exam), ("Ctrl+O", self.import_scans), ("F1", self.show_help)):
            QShortcut(QKeySequence(keys), self, action)
        self.resize(1280, 820)
        self.apply_prefs(self.prefs)
        QApplication.styleHints().colorSchemeChanged.connect(lambda _: self.apply_prefs(self.prefs))  # Windows switched

        last = theme.settings().value("last_exam")
        known = {e[0] for e in self.store.exams("kept")}
        last = int(last) if str(last).isdigit() and int(last) in known else None
        self.open_exam(last, go=False)
        self.go("Dashboard" if last else "Exams")

    def open_exam(self, exam_id: int | None, go: bool = True):
        self.check.open_exam(exam_id)
        self.exams.refresh(exam_id)
        self.exam_page.refresh()
        self.students.refresh()
        self.written.refresh()
        self.print_sheet.refresh()
        self.exam_settings.refresh()
        theme.settings().setValue("last_exam", exam_id or "")
        name = self.check.exam.name if self.check.exam else ""
        self.setWindowTitle(f"{APP}  ·  {name}" if name else APP)
        if exam_id is None:
            self.exams_area.setCurrentWidget(self.exams)
        elif go:
            self.go("Scanned sheets" if self.check.sheets else "Print sheet" if self.print_sheet.template else "Scan")

    def reload_students(self):
        self.check.students = self.store.students(self.check.exam.id)
        self.check._name()
        self.check.fill_table()
        self.exams.refresh()

    def institute_changed(self):
        """An institute was added, changed or deleted: redraw what shows it."""
        self.exam_page.refresh()
        self.exam_settings.refresh()

    def go(self, name: str):
        """Show a sidebar page, or a tab of the open exam's page."""
        if name in self.exam_page.names:
            if self.check.exam is None:
                name = "Exams"
            else:
                self.exams_area.setCurrentWidget(self.exam_page)
                self.exam_page.show_tab(name)
                name = "Exams"
        elif name == "Exams":
            self.exams_area.setCurrentWidget(self.exams)
        self.nav_buttons[name].setChecked(True)
        self.stack.setCurrentWidget(self.pages[name])
        if getattr(self.showing(), "stale", False):  # no show event while the window itself isn't shown yet
            self.showing().refresh()

    def showing(self) -> QWidget:
        """The page or exam tab on screen."""
        if self.stack.currentWidget() is self.exams_area:
            area = self.exams_area.currentWidget()
            return self.exam_page.tabs.currentWidget() if area is self.exam_page else area
        return self.stack.currentWidget()

    def new_exam(self):
        self.go("Exams")
        self.exams.new_exam()

    def show_help(self):
        HelpDialog(self, str(self.store_path.parent)).exec()

    def start_scanning(self):
        """The Scan tab, started: from the scanner when there is one, else it says what to do."""
        if self.check.exam is None:
            self.go("Exams")
            return
        self.go("Scan")
        if not self.scan.running:
            self.scan.start_or_explain()

    def import_scans(self):
        if self.check.exam is None:
            self.go("Exams")
            return
        self.go("Scan")  # read there, each sheet shown as it is read
        if not self.scan.running:
            self.scan.import_files()

    def toggle_theme(self):
        """Quick switch between light and dark; Settings has System and the rest."""
        self.settings.theme.setCurrentText("Light" if theme.is_dark(self.prefs) else "Dark")

    def apply_prefs(self, prefs: theme.Prefs):
        self.prefs = prefs
        theme.apply(QApplication.instance(), prefs)
        self.theme_button.setText("☀  Light mode" if theme.is_dark(prefs) else "☾  Dark mode")
        self.check.fill_table()  # repaints review rows and, through `changed`, the dashboard and results

    def closeEvent(self, e):
        thread = self.scan.thread
        if thread is not None:
            thread.stop = True
            thread.wait()  # the page being fed finishes
            QApplication.processEvents()  # read and save the pages it already sent before the database closes
        self.scan.timer.stop()
        if self.scan.reader is not None:  # pages already read and saved stay; the rest are read next time
            self.scan.stop()
        self.store.close()
        super().closeEvent(e)
