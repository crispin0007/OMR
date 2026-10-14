"""The student directory: the institute's students with their batch and contacts, kept once for every exam.

Each student keeps one Student ID for good; their roll number can change from exam to exam, and an exam's list
links each roll number to a student here (Students tab). An exam takes its list from here by batch (Use a batch…),
or from Excel.
"""

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from omr_core.store import Store
from omr_core.students import Student, read_students, same_roll

from .dashboard import ShownPage
from .progress import AttendanceDialog, ProfileDialog

ALL = "All batches"
COLUMNS = ["Student ID", "Name", "Class", "Batch", "Email", "Phone", "Exams taken"]


class StudentDialog(QDialog):
    """Add or change one student; saved only when every field checks out."""

    def __init__(self, parent, store: Store, student: Student | None = None):
        super().__init__(parent)
        self.store, self.old = store, student
        self.setWindowTitle("Change student" if student else "Add student")
        s = student or Student("", "")
        batch = QComboBox(editable=True)
        batch.addItems(["", *store.batches()])
        batch.setCurrentText(s.batch)
        self.edits = {key: batch.lineEdit() if key == "batch" else QLineEdit(getattr(s, key))
                      for key in ("roll_number", "name", "class_name", "batch", "email", "phone")}
        self.edits["phone"].setPlaceholderText("with the country code, e.g. +977 98…")
        self.edits["roll_number"].setPlaceholderText(f"registration number, or empty for {store.new_id()}")
        form = QFormLayout(self)
        for key, label in (("roll_number", "Student ID"), ("name", "Name"), ("class_name", "Class"),
                           ("batch", "Batch"), ("email", "Email"), ("phone", "Phone")):
            form.addRow(label, batch if key == "batch" else self.edits[key])
        self.problem = QLabel(objectName="error", wordWrap=True)
        form.addRow(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self):
        student = Student(**{key: edit.text() for key, edit in self.edits.items()})
        if not student.roll_number.strip():
            student = replace(student, roll_number=self.store.new_id())
        try:
            self.store.save_student(student, self.old.roll_number if self.old else "")
        except ValueError as e:
            self.problem.setText(f"Not saved: {e}.")
            return
        self.accept()


class DirectoryPage(ShownPage):
    changed = Signal()

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.search = QLineEdit(placeholderText="Search by name, Student ID, email or phone", clearButtonEnabled=True)
        self.search.textChanged.connect(lambda _: self.redraw())
        self.batch = QComboBox()
        self.batch.activated.connect(lambda _: self.redraw())
        add = QPushButton("Add student…")
        add.clicked.connect(self.add)
        self.edit_button = QPushButton("Change…")
        self.edit_button.clicked.connect(self.edit)
        self.remove_button = QPushButton("Remove…")
        self.remove_button.clicked.connect(self.remove)
        self.profile_button = QPushButton("Profile…", toolTip="Every exam the student took, their trend and weak "
                                          "sections")
        self.profile_button.clicked.connect(self.profile)
        attendance = QPushButton("Attendance…", toolTip="Who sat which exam, by batch and program")
        attendance.clicked.connect(lambda: AttendanceDialog(self, self.store).exec())
        load = QPushButton("Import from Excel…", objectName="primary",
                           toolTip="Student ID (or roll number) and name columns, and optionally class, batch, email and "
                           "phone")
        load.clicked.connect(self.import_students)
        top = QHBoxLayout()
        top.addWidget(QLabel("Student directory", objectName="title"))
        top.addStretch()
        for b in (self.profile_button, attendance, add, self.edit_button, self.remove_button, load):
            top.addWidget(b)
        self.rolls_change = QCheckBox("Roll numbers change from exam to exam", checked=store.rolls_change, toolTip=(
            "On: a roll number is only who an exam's list (or a name confirmed on Scanned sheets) says it is. "
            "Off: a roll number not on an exam's list is the student with that Student ID."))
        self.rolls_change.toggled.connect(self.set_rolls_change)
        filters = QHBoxLayout()
        filters.addWidget(self.search, 2)
        filters.addWidget(self.batch, 1)
        filters.addWidget(self.rolls_change)
        self.note = QLabel(objectName="muted", wordWrap=True)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)
        self.table.itemSelectionChanged.connect(self.enable)
        self.table.cellDoubleClicked.connect(lambda *_: self.profile())
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.note)
        layout.addLayout(filters)
        layout.addWidget(self.table, 1)
        self.students: list[Student] = []
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.redraw()  # exams taken change as sheets are read elsewhere

    def redraw(self):
        everyone = self.store.directory()
        chosen = self.batch.currentText() or ALL
        self.batch.clear()
        self.batch.addItems([ALL, *self.store.batches()])
        self.batch.setCurrentText(chosen)
        words = self.search.text().strip().lower().split()
        batch = self.batch.currentText()
        self.students = [s for s in everyone if (batch == ALL or s.batch == batch)
                         and all(any(w in v.lower() for v in (s.roll_number, s.name, s.email, s.phone)) for w in words)]
        taken = self.store.exams_taken()
        self.note.setText(f"{len(everyone)} students. Each keeps their Student ID in every exam, whatever roll number "
                          "they sit under; reports go to these emails and phones."
                          if everyone else "No students yet. Import an Excel list, or add them one by one. Each "
                          "exam can then take its list from here by batch.")
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.students))
        for row, s in enumerate(self.students):
            for col, value in enumerate((s.roll_number, s.name, s.class_name, s.batch, s.email, s.phone,
                                         taken.get(same_roll(s.roll_number), 0))):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, value)
                item.setData(Qt.UserRole, s.roll_number)
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.enable()

    def chosen(self) -> list[Student]:
        rolls = {self.table.item(i.row(), 0).data(Qt.UserRole) for i in self.table.selectionModel().selectedRows()}
        return [s for s in self.students if s.roll_number in rolls]

    def enable(self):
        chosen = self.chosen()
        self.edit_button.setEnabled(len(chosen) == 1)
        self.profile_button.setEnabled(len(chosen) == 1)
        self.remove_button.setEnabled(bool(chosen))

    def profile(self):
        chosen = self.chosen()
        if len(chosen) == 1:
            ProfileDialog(self, self.store, chosen[0]).exec()

    def add(self):
        if StudentDialog(self, self.store).exec():
            self.done()

    def edit(self):
        chosen = self.chosen()
        if len(chosen) == 1 and StudentDialog(self, self.store, chosen[0]).exec():
            self.done()

    def remove(self):
        chosen = self.chosen()
        if QMessageBox.question(self, "Remove students", f"Take {len(chosen)} student{'s' if len(chosen) > 1 else ''} "
                                "out of the directory? Exams keep their own lists and results.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.store.remove_students([s.roll_number for s in chosen])
            self.done()

    def import_students(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import students", "", "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            students, problems = read_students(path, None)
            students = [replace(s, roll_number=s.student_id or s.roll_number) for s in students]
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Can't import students", str(e))
            return
        if not students:
            QMessageBox.warning(self, "Can't import students", "No usable rows.\n\n" + "\n".join(problems[:30]))
            return
        added, updated = self.store.add_to_directory(students)
        self.done()
        text = f"Added {added} students" + (f" and updated {updated} already here" if updated else "") + "."
        if problems:
            more = f"\n…and {len(problems) - 30} more" if len(problems) > 30 else ""
            text += f"\n\n{len(problems)} problems:\n" + "\n".join(problems[:30]) + more
        QMessageBox.information(self, "Students imported", text)

    def set_rolls_change(self, on: bool):
        self.store.rolls_change = on
        self.done()  # exams taken are counted again

    def done(self):
        self.redraw()
        self.changed.emit()
