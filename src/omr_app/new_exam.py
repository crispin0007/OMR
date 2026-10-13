"""New exam: a step-by-step setup that makes the exam and its answer sheet together (US6).

The steps ask for the exam's details, its subjects or sections, the questions
and answers, the marking and the sheet's look, then show everything for a last
check. The sheet is laid out from those answers, so no separate sheet design is
needed. A school that already prints its own sheet picks that sheet's template
(mapped under Map printed sheet) instead.
"""

import json
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QDate, QStandardPaths, Qt, QTime, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDateEdit, QDialog,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget)

from omr_core.sheet import (DEFAULT_HEADING, DEFAULT_INSTRUCTIONS, LABELS, MAX_NUMBER_DIGITS, MAX_ROLL_DIGITS, SHAPES,
                            SheetSection, SheetSpec, layout, logo_jpeg, render)
from omr_core.store import Store
from omr_core.template import load


# The bundled templates: next to src/ in a source checkout, next to the packages in the installed app.
TEMPLATES = next((p for p in (Path(__file__).resolve().parents[2] / "templates",
                              Path(__file__).resolve().parents[1] / "templates") if p.is_dir()),
                 Path(__file__).resolve().parents[2] / "templates")
# Templates mapped in the sheet designer: %LOCALAPPDATA%\OMR\templates on Windows, next to the database.
USER_TEMPLATES = Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / "OMR" / "templates"

STEPS = ["Start", "Exam details", "Subjects and sections", "Questions and answers", "Marking", "Sheet look",
         "Review and create"]
class Ready(NamedTuple):
    """A ready-made layout: an exam's question pattern and marking, laid out on our own sheet."""
    sections: list  # (name, questions), or (name, questions, digits) for numeric answers
    total: int  # questions when there are no sections
    options: int
    right: float
    wrong: float
    roll: int = 6
    sets: int = 4  # 0 for none
    labels: str = "letters"
    shape: str = "pill"
    track: bool = False  # a sheet number printed on every sheet


def _parts(names: str, each: int) -> list:
    return [(name, each) for name in names.split(", ")]


# Patterns of national exams, from their published question counts and marking (see the README). The sheets
# are ours: no exam's official sheet or artwork is copied, and the wizard says so.
READY = {
    "Nepal · MECEE-BL / CEE pattern: 200 questions, +1 / -0.25": Ready(
        [("Zoology", 40), ("Botany", 40), ("Chemistry", 50), ("Physics", 50), ("MAT", 20)], 0, 4, 1, -0.25,
        shape="circle"),
    "Nepal · KUUMAT pattern: 100 questions, +1 / -0.25": Ready(_parts("Part 1, Part 2, Part 3, Part 4", 25), 0, 4,
                                                               1, -0.25, shape="circle"),
    "Nepal · TU CMAT pattern: 100 questions, no negative marking": Ready(
        _parts("Verbal, Quantitative, Logical reasoning, General awareness", 25), 0, 4, 1, 0, shape="circle"),
    "Nepal · IOE entrance mock: Maths, Physics, Chemistry, English, 100 questions": Ready(
        [("Mathematics", 30), ("Physics", 30), ("Chemistry", 25), ("English", 15)], 0, 4, 1, -0.1),
    "Nepal · Lok Sewa practice: 100 questions, +1 / -0.2": Ready([], 100, 4, 1, -0.2),
    "India · NEET-UG pattern: 180 questions, options 1-4, +4 / -1": Ready(
        [("Physics", 45), ("Chemistry", 45), ("Botany", 45), ("Zoology", 45)], 0, 4, 4, -1, roll=9, labels="numbers",
        shape="circle"),
    "India · JEE Main mock: 20 options + 5 numeric per subject, +4 / -1": Ready(
        [("Physics", 20), ("Physics numeric", 5, 3), ("Chemistry", 20), ("Chemistry numeric", 5, 3),
         ("Mathematics", 20), ("Mathematics numeric", 5, 3)], 0, 4, 4, -1, sets=0),
    "India · UPSC prelims GS pattern: 100 questions, +2 / -0.66": Ready([], 100, 4, 2, -0.66, roll=7,
                                                                        labels="lower", shape="circle"),
    "India · UPSC CSAT pattern: 80 questions, +2.5 / -0.83": Ready([], 80, 4, 2.5, -0.83, roll=7, labels="lower",
                                                                   shape="circle"),
    "India · NDA Maths pattern: 120 questions, +2.5 / -0.83": Ready([], 120, 4, 2.5, -0.83, roll=7, labels="lower",
                                                                    shape="circle"),
    "India · NDA GAT pattern: 150 questions, +4 / -1.33": Ready([], 150, 4, 4, -1.33, roll=7, labels="lower",
                                                                shape="circle"),
    "India · CTET pattern: 150 questions in 5 parts, no negative marking": Ready(
        _parts("Child development, Language I, Language II, Mathematics, Environmental studies", 30), 0, 4, 1, 0,
        roll=8, shape="circle"),
    "India · KCET pattern: 60 questions, no negative marking": Ready([], 60, 4, 1, 0, shape="circle"),
    "India · SSC CGL / CHSL mock: 100 questions, +2 / -0.5": Ready(
        _parts("Reasoning, General awareness, Quantitative aptitude, English", 25), 0, 4, 2, -0.5),
    "India · Bank PO / Clerk prelims mock: 100 questions, 5 options, +1 / -0.25": Ready(
        [("English", 30), ("Quantitative aptitude", 35), ("Reasoning", 35)], 0, 5, 1, -0.25),
    "India · RRB NTPC mock: 100 questions, +1 / -0.33": Ready(
        [("General awareness", 40), ("Mathematics", 30), ("Reasoning", 30)], 0, 4, 1, -0.33),
    "India · CUET mock: 50 questions, +5 / -1": Ready([], 50, 4, 5, -1),
    "Bangladesh · BCS preliminary pattern: 200 questions, +1 / -0.5": Ready([], 200, 4, 1, -0.5, shape="circle"),
    "Pakistan · MDCAT pattern: 180 questions, no negative marking": Ready(
        [("Biology", 81), ("Chemistry", 45), ("Physics", 36), ("English", 9), ("Logical reasoning", 9)], 0, 4, 1, 0,
        shape="circle"),
    "Turkey · YKS TYT pattern: 120 questions, 5 options, -0.25": Ready(
        [("Turkish", 40), ("Social sciences", 20), ("Mathematics", 40), ("Science", 20)], 0, 5, 1, -0.25, roll=9,
        sets=2, shape="circle"),
    "Class test: 50 questions, 1 mark each": Ready([], 50, 4, 1, 0, roll=5),
}
PATTERN_NOTE = ("Ready-made layouts match an exam's question pattern and marking on this app's own sheet; they are "
                "not the official answer sheets. Check the marks for your exam.")
BLANK = "Start blank"


def ready_from_json(text: str) -> Ready:
    """A saved template, checked: it is read back from the database, which a backup from another PC may fill."""
    try:
        r = Ready(**json.loads(text))
        sections = [tuple(s) for s in r.sections]
        ok = (all(len(s) in (2, 3) and isinstance(s[0], str) and s[0].strip()
                  and all(isinstance(n, int) and n >= 1 for n in s[1:]) and (len(s) == 2 or s[2] <= MAX_NUMBER_DIGITS)
                  for s in sections)
              and isinstance(r.total, int) and 0 <= r.total <= 300 and (r.total or sections)
              and isinstance(r.options, int) and 2 <= r.options <= 8
              and isinstance(r.roll, int) and 0 <= r.roll <= MAX_ROLL_DIGITS
              and isinstance(r.sets, int) and r.sets in (0, *range(2, 9))
              and all(isinstance(m, (int, float)) for m in (r.right, r.wrong))
              and r.labels in LABELS and r.shape in SHAPES and isinstance(r.track, bool))
    except (TypeError, ValueError):  # not JSON, not an object, or missing or unknown fields
        ok = False
    if not ok:
        raise ValueError("the saved template is damaged")
    return r._replace(sections=sections)


def spec_of(name: str, r: Ready) -> SheetSpec:
    """The sheet a ready-made layout prints, with the default look."""
    sections = [SheetSection(s[0], s[1], r.right, r.wrong, digits=s[2] if len(s) > 2 else 0) for s in r.sections]
    return SheetSpec(name, sum(s.questions for s in sections) or r.total, r.options, r.roll, r.sets, sections,
                     bubble_shape=r.shape, labels=r.labels, track=r.track)


def saved_templates(store: Store) -> tuple[dict[str, Ready], list[str]]:
    """The user's own templates, and the names of any that can't be used."""
    good, bad = {}, []
    for name, body in store.templates().items():
        try:
            good[name] = ready_from_json(body)
        except ValueError:
            bad.append(name)
    return good, bad

OWN_SHEET_SKIPS = {"Subjects and sections", "Questions and answers", "Sheet look"}  # the printed sheet decides these
SETS = ["No sets"] + [f"{n} sets (A to {'ABCDEFGH'[n - 1]})" for n in range(2, 9)]
COLOURS = [("Pink", "#e4007c"), ("Red", "#d32f2f"), ("Orange", "#ef6c00"), ("Green", "#2e7d32"),
           ("Teal", "#00838f"), ("Blue", "#1565c0"), ("Purple", "#6a1b9a"), ("Black", "#000000")]
OTHER_COLOUR = "Other colour…"
BUBBLE_SHAPES = [("Pill", "pill"), ("Oval", "oval"), ("Circle", "circle"), ("Rounded rectangle", "rounded"),
                 ("Rectangle", "rectangle")]
ANSWERED_WITH = ["Options"] + [f"Number, up to {n} digit{'s' if n > 1 else ''}" for n in range(1, MAX_NUMBER_DIGITS + 1)]


def _marks(value: float) -> QDoubleSpinBox:
    return QDoubleSpinBox(minimum=-100, maximum=100, value=value, decimals=2, singleStep=0.25)


class Deduction(QDoubleSpinBox):
    """Marks taken off, typed as a plain number: 0.25 shows as −0.25 and value() is -0.25.

    People read "negative marking" as already negative, so the sign is shown, never typed.
    A stored positive mark (a bonus for a wrong answer, never meant) loads as 0.
    """

    def __init__(self, value: float = 0.0):
        super().__init__(minimum=0, maximum=100, decimals=2, singleStep=0.25, prefix="−")
        self.setValue(value)
        self.setToolTip("Marks taken off; type 0.25 to take off a quarter mark, 0 for no negative marking")

    def value(self) -> float:
        return -super().value() or 0.0  # no -0.0

    def setValue(self, value: float):
        super().setValue(max(-value, 0))


class NewExamWizard(QDialog):
    def __init__(self, parent: QWidget, store: Store):
        super().__init__(parent)
        self.setWindowTitle("New exam")
        self.store = store
        self.exam_id: int | None = None
        self.made: dict | None = None  # the laid-out sheet, once the choices fit
        self.layout_problem = ""
        self.logo = b""
        default = TEMPLATES / "test-100.json"
        self.template_path = str(default) if default.exists() else ""
        self.timer = QTimer(self, singleShot=True, interval=300)  # redraw the preview once typing pauses
        self.timer.timeout.connect(self.update_preview)

        self.steps = QStackedWidget()
        for build in (self._start, self._details, self._sections, self._answers, self._marking, self._look,
                      self._review):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(4, 0, 4, 0)
            build(layout)
            self.steps.addWidget(page)

        self.rail = []
        rail = QVBoxLayout()
        for n, name in enumerate(STEPS, 1):
            label = QLabel(f"{n}.  {name}")
            self.rail.append(label)
            rail.addWidget(label)
        rail.addStretch()
        rail_box = QWidget(objectName="card")
        rail_box.setLayout(rail)
        rail_box.setFixedWidth(210)

        self.error = QLabel(objectName="error", wordWrap=True)
        self.back = QPushButton("Back")
        self.back.clicked.connect(lambda: self.move(-1))
        self.next = QPushButton("Next", objectName="primary")
        self.next.clicked.connect(self.forward)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(cancel)
        buttons.addWidget(self.error, 1)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        body = QHBoxLayout()
        body.addWidget(rail_box)
        body.addWidget(self.steps, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addLayout(buttons)
        self.resize(1040, 680)
        self.show_step(0)

    # -- steps --------------------------------------------------------------------------------------------

    def _start(self, layout: QVBoxLayout):
        layout.addWidget(QLabel("How will students mark their answers?", objectName="title"))
        self.make_sheet = QRadioButton("Make the answer sheet for me (recommended)")
        self.make_sheet.setChecked(True)
        self.own_sheet = QRadioButton("Use my own printed sheet")
        group = QButtonGroup(self)
        group.addButton(self.make_sheet)
        group.addButton(self.own_sheet)
        layout.addWidget(self.make_sheet)
        layout.addWidget(QLabel("Answer a few questions about the exam and the sheet is laid out for you, ready to "
                                "print.", objectName="muted", wordWrap=True))
        self.patterns = {**READY, **saved_templates(self.store)[0]}  # built-in names can't be saved over
        self.ready = QComboBox()
        self.ready.addItems([BLANK, *self.patterns])
        self.ready.setToolTip("Fills in the subjects, questions and marks; change anything on the next steps")
        self.ready.currentTextChanged.connect(self.use_ready)
        ready_row = QHBoxLayout()
        ready_row.addSpacing(24)
        ready_row.addWidget(QLabel("Start from"))
        ready_row.addWidget(self.ready, 1)
        layout.addLayout(ready_row)
        note = QLabel(PATTERN_NOTE, objectName="muted", wordWrap=True)
        note.setContentsMargins(24, 0, 0, 0)
        layout.addWidget(note)
        layout.addSpacing(12)
        layout.addWidget(self.own_sheet)
        layout.addWidget(QLabel("For a sheet you already print. Map it once under Map printed sheet, then pick its "
                                "template here.", objectName="muted", wordWrap=True))
        self.template_label = QLabel(objectName="muted")
        self.choose = QPushButton("Choose template…")
        self.choose.clicked.connect(self.choose_template)
        row = QHBoxLayout()
        row.addSpacing(24)
        row.addWidget(self.choose)
        row.addWidget(self.template_label, 1)
        layout.addLayout(row)
        layout.addStretch()
        self.own_sheet.toggled.connect(self._show_template)
        self._show_template()

    def _details(self, layout: QVBoxLayout):
        layout.addWidget(QLabel("About the exam", objectName="title"))
        self.name = QLineEdit(placeholderText="e.g. Mock test 3")
        self.class_name = QLineEdit(placeholderText="e.g. Class 10, Section A")
        self.date = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.time = QTimeEdit(QTime(10, 0))
        self.minutes = QSpinBox(minimum=0, maximum=600, value=90, suffix=" minutes", specialValueText="Not set")
        self.series = QComboBox(editable=True)
        self.series.addItems(["", *self.store.series_names()])
        self.series.lineEdit().setPlaceholderText("None, or e.g. JEE test series 2027")
        self.series.setToolTip("Exams in one test series share the student list and get a combined rank")
        form = QFormLayout()
        form.addRow("Exam name", self.name)
        form.addRow("Class", self.class_name)
        form.addRow("Date", self.date)
        form.addRow("Starts at", self.time)
        form.addRow("Duration", self.minutes)
        form.addRow("Test series", self.series)
        layout.addLayout(form)
        layout.addStretch()

    def _sections(self, layout: QVBoxLayout):
        layout.addWidget(QLabel("Subjects and sections", objectName="title"))
        layout.addWidget(QLabel("Leave the list empty for one set of questions. Add a row for each subject or "
                                "section; each starts its own column on the sheet and gets its own marks and score. "
                                "Questions answered with a number (e.g. JEE numeric questions) get a box of digits "
                                "each at the foot of the sheet.", objectName="muted", wordWrap=True))
        self.total = QSpinBox(minimum=1, maximum=300, value=100)
        total_row = QFormLayout()
        total_row.addRow("Number of questions", self.total)
        layout.addLayout(total_row)
        self.sections = QTableWidget(0, 4)
        self.sections.setHorizontalHeaderLabels(["Subject or section", "Questions", "Question numbers", "Answered with"])
        self.sections.verticalHeader().hide()
        self.sections.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sections.itemChanged.connect(self._sections_changed)
        add = QPushButton("Add subject or section")
        add.clicked.connect(self.add_section)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_section)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout.addWidget(self.sections, 1)
        layout.addLayout(buttons)

    def _answers(self, layout: QVBoxLayout):
        layout.addWidget(QLabel("Questions and answers", objectName="title"))
        self.options = QSpinBox(minimum=2, maximum=8, value=4)
        self.options.setToolTip("Up to 8 options fit on one A4 sheet")
        self.true_false = QCheckBox("True or false questions (bubbles T and F)")
        self.true_false.toggled.connect(lambda on: (self.options.setValue(2) if on else None,
                                                    self.options.setEnabled(not on), self.labels.setEnabled(not on)))
        self.labels = QComboBox()
        for name, value in (("A, B, C, D…", "letters"), ("a, b, c, d…", "lower"), ("1, 2, 3, 4…", "numbers")):
            self.labels.addItem(name, value)
        self.labels.setToolTip("What the bubbles show; the answer key and results still use A, B, C, D")
        self.roll = QSpinBox(minimum=0, maximum=MAX_ROLL_DIGITS, value=5, specialValueText="No roll number")
        self.sets = QComboBox()
        self.sets.addItems(SETS)
        self.sets.setCurrentIndex(3)  # A to D
        form = QFormLayout()
        form.addRow("Options per question", self.options)
        form.addRow("", self.true_false)
        form.addRow("Options shown as", self.labels)
        form.addRow("Roll number digits", self.roll)
        form.addRow("Question paper sets", self.sets)
        layout.addLayout(form)
        layout.addWidget(QLabel("Sets are versions of the paper with the questions in another order; each set gets "
                                "its own answer key.", objectName="muted", wordWrap=True))
        layout.addStretch()

    def _marking(self, layout: QVBoxLayout):
        layout.addWidget(QLabel("Marking", objectName="title"))
        self.correct, self.wrong, self.blank = _marks(1), Deduction(), Deduction()
        self.partial = QCheckBox("Partial marking: several bubbles may be filled, and picking some of a multi-correct "
                                 "answer (and no wrong option) earns part of its marks")
        marks = QHBoxLayout()
        for text, box in (("Correct", self.correct), ("Wrong", self.wrong), ("Blank", self.blank)):
            marks.addWidget(QLabel(text))
            marks.addWidget(box)
        marks.addStretch()
        self.default_marks = QWidget()
        default_layout = QVBoxLayout(self.default_marks)
        default_layout.setContentsMargins(0, 0, 0, 0)
        default_layout.addLayout(marks)
        default_layout.addWidget(self.partial)
        layout.addWidget(self.default_marks)
        self.section_marks = QTableWidget(0, 4)
        self.section_marks.setHorizontalHeaderLabels(["Subject or section", "Correct", "Wrong", "Partial marking"])
        self.section_marks.verticalHeader().hide()
        self.section_marks.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.section_marks, 1)
        self.marking_note = QLabel(objectName="muted", wordWrap=True)
        layout.addWidget(self.marking_note)

    def _look(self, layout: QVBoxLayout):
        layout.addWidget(QLabel("How the sheet looks", objectName="title"))
        self.heading = QLineEdit(DEFAULT_HEADING)
        self.colour = QComboBox()
        for name, value in COLOURS:
            self._add_colour(name, value)
        self.colour.addItem(OTHER_COLOUR)
        self.colour.activated.connect(self.colour_chosen)
        self.logo_label = QLabel("No logo", objectName="muted")
        logo = QPushButton("Choose logo…")
        logo.clicked.connect(self.choose_logo)
        no_logo = QPushButton("Remove")
        no_logo.clicked.connect(self.remove_logo)
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_label, 1)
        logo_row.addWidget(logo)
        logo_row.addWidget(no_logo)
        self.shape = QComboBox()
        for name, value in BUBBLE_SHAPES:
            self.shape.addItem(name, value)
        self.shape.setToolTip("Every shape reads the same; pick the one your students know")
        self.shape.currentIndexChanged.connect(self.timer.start)
        self.track = QCheckBox("Print a sheet number on every sheet")
        self.track.setToolTip("Each printed sheet gets its own number (0001, 0002…), read back when it is scanned, "
                              "so every paper sheet can be traced and missing or repeated sheets show")
        self.track.toggled.connect(self.timer.start)
        self.instructions = QPlainTextEdit("\n".join(DEFAULT_INSTRUCTIONS))
        self.instructions.setToolTip("One instruction per line; they are numbered for you")
        form = QFormLayout()
        form.addRow("Heading", self.heading)
        form.addRow("Colour", self.colour)
        form.addRow("Bubbles", self.shape)
        form.addRow("Sheet number", self.track)
        form.addRow("Logo", logo_row)
        form.addRow("Instructions", self.instructions)
        left = QWidget()
        left.setLayout(form)
        self.look_preview = QLabel(alignment=Qt.AlignCenter)
        row = QHBoxLayout()
        row.addWidget(left, 3)
        row.addWidget(self.look_preview, 2)
        layout.addLayout(row, 1)
        self.heading.textChanged.connect(self.timer.start)
        self.instructions.textChanged.connect(self.timer.start)

    def _review(self, layout: QVBoxLayout):
        layout.addWidget(QLabel("Check and create", objectName="title"))
        self.summary = QLabel(wordWrap=True, textFormat=Qt.RichText)
        self.summary.setAlignment(Qt.AlignTop)
        self.preview = QLabel(alignment=Qt.AlignCenter)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(self.preview)
        row = QHBoxLayout()
        row.addWidget(self.summary, 2)
        row.addWidget(scroll, 3)
        layout.addLayout(row, 1)

    # -- moving between steps -------------------------------------------------------------------------------

    def visible_steps(self) -> list[int]:
        return [i for i, name in enumerate(STEPS) if not (self.own_sheet.isChecked() and name in OWN_SHEET_SKIPS)]

    def show_step(self, index: int):
        self.error.clear()
        if STEPS[index] == "Marking":
            self._fill_section_marks()
        if STEPS[index] == "Sheet look":
            self.update_preview()
        if STEPS[index] == "Review and create":
            self.update_review()
        self.steps.setCurrentIndex(index)
        shown = self.visible_steps()
        for i, label in enumerate(self.rail):
            font = label.font()
            font.setBold(i == index)
            label.setFont(font)
            label.setText(f"{'●' if i == index else '✓' if i < index else '○'}  {STEPS[i]}")
            label.setEnabled(i in shown)
        self.back.setEnabled(index != shown[0])
        last = index == shown[-1]
        self.next.setText("Create exam" if last else "Next")

    def move(self, step: int):
        shown = self.visible_steps()
        position = shown.index(self.steps.currentIndex()) + step
        self.show_step(shown[max(0, min(position, len(shown) - 1))])

    def forward(self):
        problem = self.check_step(STEPS[self.steps.currentIndex()])
        if problem:
            self.error.setText(problem)
            return
        if self.steps.currentIndex() == self.visible_steps()[-1]:
            self.create()
        else:
            self.move(1)

    def check_step(self, name: str) -> str:
        """What stops this step going on, or ""."""
        if name == "Start" and self.own_sheet.isChecked():
            try:
                load(self.template_path)
            except (OSError, ValueError) as e:
                return f"Choose your sheet's template first ({e})" if self.template_path else "Choose your sheet's template"
        if name == "Exam details" and not self.name.text().strip():
            return "Give the exam a name"
        if name == "Subjects and sections":
            try:
                rows = self.read_sections()
            except ValueError as e:
                return str(e)
            names = [s.name for s in rows]
            if any(not n for n in names) or len(set(names)) != len(names):
                return "Every subject or section needs its own name"
        if name == "Review and create" and not self.own_sheet.isChecked() and self.made is None:
            return self.layout_problem or "Fix the choices above first"
        return ""

    def use_ready(self, name: str):
        """Fill the steps from a ready-made layout; the user can change anything after."""
        if name not in self.patterns:
            return
        sections, total, options, right, wrong, roll, sets, labels, shape, track = self.patterns[name]
        self.make_sheet.setChecked(True)
        self.true_false.setChecked(False)
        self.options.setValue(options)
        self.roll.setValue(roll)
        self.sets.setCurrentIndex(sets - 1 if sets else 0)
        self.labels.setCurrentIndex(self.labels.findData(labels))
        self.shape.setCurrentIndex(self.shape.findData(shape))
        self.track.setChecked(track)
        self.correct.setValue(right)
        self.wrong.setValue(wrong)
        self.sections.setRowCount(0)
        self.section_marks.setRowCount(0)  # new rows take the marks above
        if total:
            self.total.setValue(total)
        for section, count, *digits in sections:
            self.add_section()
            row = self.sections.rowCount() - 1
            self.sections.item(row, 0).setText(section)
            self.sections.item(row, 1).setText(str(count))
            self.sections.cellWidget(row, 3).setCurrentIndex(digits[0] if digits else 0)
        self._sections_changed()
        self._fill_section_marks()

    # -- sections ------------------------------------------------------------------------------------------

    def add_section(self):
        n = self.sections.rowCount()
        self.sections.blockSignals(True)
        self.sections.insertRow(n)
        self.sections.setItem(n, 0, QTableWidgetItem(f"Subject {n + 1}"))
        self.sections.setItem(n, 1, QTableWidgetItem(str(self.total.value()) if n == 0 else "25"))
        answered = QComboBox()
        answered.addItems(ANSWERED_WITH)
        answered.currentIndexChanged.connect(self._sections_changed)
        self.sections.setCellWidget(n, 3, answered)
        self.sections.blockSignals(False)
        self._sections_changed()

    def remove_section(self):
        row = self.sections.currentRow()
        self.sections.removeRow(row if row >= 0 else self.sections.rowCount() - 1)
        self._sections_changed()

    def read_sections(self) -> list[SheetSection]:
        out = []
        for r in range(self.sections.rowCount()):
            name = (self.sections.item(r, 0).text() if self.sections.item(r, 0) else "").strip()
            try:
                count = int(self.sections.item(r, 1).text())
                if count < 1:
                    raise ValueError
            except (AttributeError, ValueError):
                raise ValueError(f"row {r + 1}: the number of questions must be a whole number above 0") from None
            out.append(SheetSection(name, count, digits=self.sections.cellWidget(r, 3).currentIndex()))
        return out

    def _sections_changed(self, *_):
        """Show each row's question numbers, and let the rows decide the total."""
        self.sections.blockSignals(True)
        first = 1
        for r in range(self.sections.rowCount()):
            try:
                count = int(self.sections.item(r, 1).text())
            except (AttributeError, ValueError):
                count = 0
            item = QTableWidgetItem(f"{first} to {first + count - 1}" if count > 0 else "")
            item.setFlags(Qt.ItemIsEnabled)
            self.sections.setItem(r, 2, item)
            first += max(count, 0)
        self.sections.blockSignals(False)
        has_rows = self.sections.rowCount() > 0
        if has_rows:
            self.total.setValue(min(max(first - 1, 1), self.total.maximum()))
        self.total.setEnabled(not has_rows)

    # -- marking -------------------------------------------------------------------------------------------

    def _fill_section_marks(self):
        """One marking row per section, keeping marks already typed for a section of the same name."""
        kept = {}
        for r in range(self.section_marks.rowCount()):
            kept[self.section_marks.item(r, 0).text()] = (
                self.section_marks.cellWidget(r, 1).value(), self.section_marks.cellWidget(r, 2).value(),
                self.section_marks.item(r, 3).checkState() == Qt.Checked)
        try:
            rows = [] if self.own_sheet.isChecked() else self.read_sections()
        except ValueError:
            rows = []
        self.section_marks.setRowCount(len(rows))
        for r, s in enumerate(rows):
            correct, wrong, partial = kept.get(s.name, (self.correct.value(), self.wrong.value(),
                                                        self.partial.isChecked()))
            item = QTableWidgetItem(s.name)
            item.setFlags(Qt.ItemIsEnabled)
            self.section_marks.setItem(r, 0, item)
            self.section_marks.setCellWidget(r, 1, _marks(correct))
            self.section_marks.setCellWidget(r, 2, Deduction(wrong))
            box = QTableWidgetItem("Partial marks")
            box.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            box.setCheckState(Qt.Checked if partial else Qt.Unchecked)
            self.section_marks.setItem(r, 3, box)
        self.section_marks.setVisible(bool(rows))
        self.partial.setVisible(not rows and not self.own_sheet.isChecked())
        self.marking_note.setText(
            "Each subject or section has its own marks. For negative marking, type the marks taken off, e.g. 1."
            if rows else "For negative marking, type the marks taken off for a wrong answer, e.g. 0.25. You can change "
            "marks later on the exam's Marks and sections tab.")

    def sheet_sections(self) -> list[SheetSection]:
        rows = self.read_sections()
        if rows:
            self._fill_section_marks() if self.section_marks.rowCount() != len(rows) else None
            return [SheetSection(s.name, s.questions, self.section_marks.cellWidget(r, 1).value(),
                                 self.section_marks.cellWidget(r, 2).value(),
                                 self.section_marks.item(r, 3).checkState() == Qt.Checked, s.digits)
                    for r, s in enumerate(rows)]
        if self.partial.isChecked():  # partial marking needs a section to carry it
            return [SheetSection("All questions", self.total.value(), self.correct.value(), self.wrong.value(), True)]
        return []

    # -- the sheet -----------------------------------------------------------------------------------------

    def spec(self) -> SheetSpec:
        sections = self.sheet_sections()
        return SheetSpec(self.name.text().strip() or "Answer sheet",
                         sum(s.questions for s in sections) if sections else self.total.value(),
                         self.options.value(), self.roll.value(),
                         self.sets.currentIndex() and self.sets.currentIndex() + 1, sections,
                         self.colour.currentData() or COLOURS[0][1], self.heading.text(),
                         self.instructions.toPlainText().splitlines(), self.logo, self.true_false.isChecked(),
                         self.shape.currentData(), self.labels.currentData(), self.track.isChecked())

    def update_preview(self):
        self.layout_problem = ""
        try:
            self.made = layout(self.spec())
        except ValueError as e:
            self.made, self.layout_problem = None, str(e)
            if STEPS[self.steps.currentIndex()] == "Sheet look":
                self.error.setText(self.layout_problem)
            return
        self.error.clear()
        page = render(self.made, dpi=45)
        image = QImage(page.data, page.shape[1], page.shape[0], page.strides[0], QImage.Format_BGR888).copy()
        self.look_preview.setPixmap(QPixmap.fromImage(image))
        self.preview.setPixmap(QPixmap.fromImage(image).scaledToWidth(int(image.width() * 1.4),
                                                                      Qt.SmoothTransformation))

    def update_review(self):
        lines = [f"<b>{self.name.text().strip()}</b>"]
        when = f"{self.date.date().toString('d MMM yyyy')} at {self.time.time().toString('HH:mm')}"
        if self.minutes.value():
            when += f", {self.minutes.value()} minutes"
        lines.append(" · ".join(x for x in (self.class_name.text().strip(), when) if x))
        if self.series.currentText().strip():
            lines.append(f"Test series: {self.series.currentText().strip()}")
        if self.own_sheet.isChecked():
            self.made = None
            self.preview.clear()
            t = load(self.template_path)
            questions = len(t.questions())
            lines += [f"Your printed sheet: {t.name}, {questions} questions",
                      f"Marks: {self.correct.value():g} right, {self.wrong.value():g} wrong, "
                      f"{self.blank.value():g} blank"]
        else:
            self.update_preview()
            spec = self.spec()
            kind = "true or false" if spec.true_false else f"{spec.options} options each"
            lines.append(f"{spec.questions} questions, {kind}")
            for s in spec.sections:
                lines.append(f"&nbsp;&nbsp;{s.name}: {s.questions} questions"
                             + (f" answered with a number of up to {s.digits} digits" if s.digits else "")
                             + f", {s.correct:g} right, {s.wrong:g} wrong"
                             + (", partial marking" if s.partial and not s.digits else ""))
            if not spec.sections:
                lines.append(f"Marks: {self.correct.value():g} right, {self.wrong.value():g} wrong, "
                             f"{self.blank.value():g} blank")
            lines.append(f"Roll number: {spec.roll_digits} digits" if spec.roll_digits else "No roll number")
            lines.append(SETS[self.sets.currentIndex()])
            if spec.track:
                lines.append("A sheet number on every sheet, chosen when printing")
            if self.made is None:
                lines.append(f"<span style='color:#c62828'>{self.layout_problem}</span>")
        lines.append("<br>The answer key goes in on the exam's Answer key tab.")
        self.summary.setText("<br>".join(lines))

    # -- choices -------------------------------------------------------------------------------------------

    def _show_template(self, *_):
        self.choose.setEnabled(self.own_sheet.isChecked())
        try:
            self.template_label.setText(load(self.template_path).name if self.template_path else "None chosen")
        except (OSError, ValueError) as e:
            self.template_label.setText(f"Can't use it: {e}")

    def choose_template(self):
        start = USER_TEMPLATES if USER_TEMPLATES.is_dir() and any(USER_TEMPLATES.glob("*.json")) else TEMPLATES
        path, _ = QFileDialog.getOpenFileName(self, "Choose template", str(start), "Templates (*.json)")
        if path:
            self.template_path = path
            self._show_template()

    def _add_colour(self, name: str, value: str):
        swatch = QPixmap(16, 16)
        swatch.fill(QColor(value))
        self.colour.insertItem(max(self.colour.count() - (self.colour.findText(OTHER_COLOUR) >= 0), 0),
                               QIcon(swatch), name, value)

    def colour_chosen(self, index: int):
        if self.colour.itemText(index) == OTHER_COLOUR:
            chosen = QColorDialog.getColor(QColor(self.colour.itemData(0)), self, "Sheet colour")
            if not chosen.isValid():
                self.colour.setCurrentIndex(0)
                return
            value = chosen.name()
            if self.colour.findData(value) < 0:
                self._add_colour(value, value)
            self.colour.setCurrentIndex(self.colour.findData(value))
        self.update_preview()

    def choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Logo", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            self.logo = logo_jpeg(Path(path).read_bytes())
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Couldn't use that logo", str(e))
            return
        self.logo_label.setText(Path(path).name)
        self.update_preview()

    def remove_logo(self):
        self.logo = b""
        self.logo_label.setText("No logo")
        self.update_preview()

    # -- create --------------------------------------------------------------------------------------------

    def create(self):
        details = {"class": self.class_name.text().strip(), "date": self.date.date().toString(Qt.ISODate),
                   "time": self.time.time().toString("HH:mm"), "minutes": self.minutes.value(),
                   "series": self.series.currentText().strip()}
        try:
            text = (Path(self.template_path).read_text(encoding="utf-8") if self.own_sheet.isChecked()
                    else json.dumps(self.made))
            self.exam_id = self.store.create_exam(self.name.text(), text, details)
        except (OSError, ValueError) as e:
            self.error.setText(f"Can't create the exam: {e}")
            return
        self.store.save_scheme(self.exam_id, "", self.correct.value(), self.wrong.value(), self.blank.value())
        self.accept()
