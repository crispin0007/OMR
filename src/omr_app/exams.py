"""Exams page: create exams and open one. Each exam keeps its own template, key, marks, students and sheets.

Back up copies every exam into one file; Restore adds the exams in such a file, on this PC or a new one.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressDialog,
                               QPushButton, QTabBar, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from omr_core.store import TRASH_DAYS, Store

from .dashboard import ShownPage
from .help import steps_html
from .new_exam import TEMPLATES, USER_TEMPLATES, NewExamWizard  # noqa: F401  (TEMPLATES is used by window.py)
from .series import SeriesDialog

class ExamsPage(ShownPage):
    """Every exam; click one to open its page."""

    opened = Signal(object)  # exam id

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.open_id: int | None = None
        self.purged: list[str] = []  # exams the Trash deleted for good when the app started
        new = QPushButton("New exam…", objectName="primary")
        new.clicked.connect(self.new_exam)
        backup = QPushButton("Back up…", toolTip="Save every exam, with its sheets, corrections and students, "
                             "in one file to keep safe or take to another PC")
        backup.clicked.connect(self.backup)
        restore = QPushButton("Restore…", toolTip="Add the exams in a backup file; exams already here stay as they are")
        restore.clicked.connect(self.restore)
        self.series = QPushButton("Test series…", toolTip="Rank students on their combined score over the exams "
                                  "of a test series")
        self.series.clicked.connect(lambda: SeriesDialog(self, self.store).exec())
        self.shrink = QPushButton("Make smaller…", toolTip="Sheets read by an older version keep a large picture "
                                  "of each page; save them the new, smaller way")
        self.shrink.clicked.connect(self.shrink_images)
        top = QHBoxLayout()
        top.addWidget(QLabel("Exams", objectName="title"))
        top.addStretch()
        top.addWidget(self.shrink)
        top.addWidget(self.series)
        top.addWidget(backup)
        top.addWidget(restore)
        top.addWidget(new)
        self.note = QLabel(objectName="muted", wordWrap=True)
        self.views = QTabBar(drawBase=False)
        for label in ("Exams", "Archived", "Trash"):
            self.views.addTab(label)
        self.views.currentChanged.connect(lambda _: self.redraw())
        self.open_button = QPushButton("Open")
        self.open_button.clicked.connect(lambda: self.opened.emit(self.chosen()))
        self.unarchive = QPushButton("Put back on the list", toolTip="Show this exam with the others again")
        self.unarchive.clicked.connect(self.put_back_archived)
        self.restore_button = QPushButton("Restore", objectName="primary",
                                          toolTip="Take the exam out of the Trash, with everything read for it")
        self.restore_button.clicked.connect(self.restore_from_trash)
        self.delete_button = QPushButton("Delete for good…")
        self.delete_button.clicked.connect(self.delete_for_good)
        self.empty = QPushButton("Empty Trash…")
        self.empty.clicked.connect(self.empty_trash)
        actions = QHBoxLayout()
        actions.addWidget(self.views)
        actions.addStretch()
        for b in (self.open_button, self.unarchive, self.restore_button, self.delete_button, self.empty):
            actions.addWidget(b)
        self.start = QLabel(f"<h3>Getting started</h3>{steps_html()}", objectName="card", wordWrap=True,
                            textFormat=Qt.RichText)
        self.start.setContentsMargins(20, 12, 20, 12)
        self.start.setMaximumWidth(760)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Exam", "Created", "Sheets", "Students", ""])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self.clicked)
        self.table.itemSelectionChanged.connect(self.enable)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.note)
        layout.addLayout(actions)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.start, 0, Qt.AlignTop)
        layout.addStretch()
        self.refresh()

    def refresh(self, open_id: int | None = ...):
        if open_id is not ...:
            self.open_id = open_id
        super().refresh()

    def view(self) -> str:
        return ("active", "archived", "trash")[self.views.currentIndex()]

    def redraw(self):
        view = self.view()
        exams = self.store.exams(view) if view != "trash" else []
        trash = self.store.trash()
        archived = len(self.store.exams("archived"))
        self.views.setTabText(1, f"Archived ({archived})" if archived else "Archived")
        self.views.setTabText(2, f"Trash ({len(trash)})" if trash else "Trash")
        self.views.setVisible(bool(archived or trash or view != "active"))
        anything = bool(self.store.exams("kept") or trash)
        notes = {"active": "Click an exam to open it: scan, check, set the key and marks, see results and print its "
                           "sheet. Everything is saved as you work."
                           if exams else "Create an exam to start: New exam walks you through it and makes its sheet."
                           if not anything else "No exams on the list. Archived exams and the Trash are above.",
                 "archived": "Finished exams put away from the list. They keep their sheets and results, stay in "
                             "test series and backups, and open as usual.",
                 "trash": f"Deleted exams, with everything read for them. Each is deleted for good {TRASH_DAYS} days "
                          "after it was moved here; until then Restore brings it back as it was."}
        note = notes[view]
        if self.purged:
            note += (f"\n\nDeleted for good after {TRASH_DAYS} days in the Trash: {', '.join(self.purged)}.")
        self.note.setText(note)
        self.table.setVisible(bool(exams) or view == "trash" and bool(trash))
        self.series.setVisible(bool(self.store.series_names()))
        self.shrink.setVisible(self.store.png_pages() > 0)
        self.start.setVisible(not anything)  # first run: what to do, in order
        if view == "trash":
            now = datetime.now()
            self.table.setHorizontalHeaderLabels(["Exam", "Deleted", "Sheets", "Deleted for good", ""])
            rows = [(i, (name, at.replace("T", "  "), str(pages), _left(at, now), ""))
                    for i, name, at, pages in trash]
        else:
            self.table.setHorizontalHeaderLabels(["Exam", "Created", "Sheets", "Students", ""])
            rows = [(i, (name, created.replace("T", "  "), str(pages), str(students or ""),
                         "open now" if i == self.open_id else "")) for i, name, created, pages, students in exams]
        self.table.setRowCount(len(rows))
        for row, (id_, texts) in enumerate(rows):
            for col, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, id_)
                self.table.setItem(row, col, item)
        self.table.clearSelection()
        self.table.resizeColumnsToContents()
        self.enable()

    def enable(self):
        view, chosen = self.view(), self.chosen() is not None
        for button, shown in ((self.open_button, view == "archived"), (self.unarchive, view == "archived"),
                              (self.restore_button, view == "trash"), (self.delete_button, view == "trash"),
                              (self.empty, view == "trash")):
            button.setVisible(shown)
            button.setEnabled(chosen or button is self.empty and bool(self.store.trash()))

    def chosen(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def clicked(self, row: int, _):
        if self.view() == "active":  # elsewhere a click picks the exam for the buttons
            self.opened.emit(self.table.item(row, 0).data(Qt.UserRole))

    def put_back_archived(self):
        self.store.set_archived(self.chosen(), False)
        self.redraw()

    def restore_from_trash(self):
        exam = self.chosen()
        self.store.put_back(exam)
        self.redraw()

    def delete_for_good(self):
        exam = self.chosen()
        name = self.table.item(self.table.currentRow(), 0).text()
        if QMessageBox.question(self, "Delete for good", f"Delete “{name}” and every sheet read for it for good? "
                                "This can't be undone.", QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        self.store.delete_exam(exam)
        self.redraw()

    def empty_trash(self):
        trash = self.store.trash()
        if QMessageBox.question(self, "Empty Trash", f"Delete the {len(trash)} exam{'s' if len(trash) > 1 else ''} "
                                f"in the Trash, and every sheet read for them, for good? This can't be undone.\n\n"
                                + ", ".join(name for _, name, _, _ in trash), QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        for i, *_ in trash:
            self.store.delete_exam(i)
        self.redraw()

    def new_exam(self):
        wizard = NewExamWizard(self, self.store)
        if wizard.exec():
            self.opened.emit(wizard.exam_id)

    def backup(self):
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Back up every exam", str(docs / f"OMR backup {date.today()}.db"),
                                              "OMR backup (*.db)")
        if not path:
            return
        try:
            self.store.backup(path)
        except (OSError, sqlite3.Error) as e:
            QMessageBox.warning(self, "Couldn't back up", f"{path}\n\n{e}")
            return
        QMessageBox.information(self, "Backed up", f"Every exam is saved in {path}.\n\nKeep it on a USB drive or "
                                "another PC; Restore… there brings the exams back.")

    def shrink_images(self):
        pages = self.store.png_pages()
        if QMessageBox.question(
                self, "Make the exams smaller",
                f"{pages} scanned pages were saved by an older version with a large picture of each page. Saving "
                "them the new way makes the exams several times smaller. Answers, marks and corrections don't "
                "change, and Review still shows each page clearly.\n\nFirst, save a backup of every exam.",
                QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Ok) != QMessageBox.Ok:
            return
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        path, _ = QFileDialog.getSaveFileName(self, "Backup before making the exams smaller",
                                              str(docs / f"OMR backup {date.today()}.db"), "OMR backup (*.db)")
        if not path:
            return
        try:
            self.store.backup(path)
        except (OSError, sqlite3.Error) as e:
            QMessageBox.warning(self, "Couldn't back up", f"{path}\n\n{e}\n\nNothing was changed.")
            return
        progress = QProgressDialog("Making the exams smaller…", "Stop", 0, pages, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        def step(done: int, total: int) -> bool:
            progress.setValue(done)
            QApplication.processEvents()
            return not progress.wasCanceled()
        try:
            before, after = self.store.shrink_images(step)
        except (OSError, sqlite3.Error) as e:
            progress.close()
            QMessageBox.warning(self, "Couldn't finish", f"{e}\n\nThe pages done so far are saved; the rest are as "
                                f"they were. Your backup is in {path}.")
            return
        progress.close()
        self.refresh()
        QMessageBox.information(self, "Done", f"The exams went from {before / 1e6:,.0f} MB to {after / 1e6:,.0f} MB."
                                + (f"\n\n{self.store.png_pages()} pages are left for next time."
                                   if self.store.png_pages() else "") + f"\n\nYour backup is in {path}.")

    def restore(self):
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getOpenFileName(self, "Restore exams from a backup", docs, "OMR backup (*.db)")
        if not path:
            return
        try:
            restored, skipped = self.store.restore(path)
        except sqlite3.Error as e:
            QMessageBox.warning(self, "Can't restore that file", f"{path}\n\nIt isn't an OMR backup ({e}).")
            return
        except OSError as e:
            QMessageBox.warning(self, "Can't restore that file", f"{path}\n\n{e}")
            return
        self.refresh()
        lines = [f"Restored {', '.join(restored)}." if restored else "No new exams in it."]
        if skipped:
            lines.append(f"Already here, left as they are: {', '.join(skipped)}.")
        QMessageBox.information(self, "Restore", "\n\n".join(lines))


def _left(deleted_at: str, now: datetime) -> str:
    """When an exam moved to the Trash at `deleted_at` is deleted for good, in days from `now`."""
    days = TRASH_DAYS - (now - datetime.fromisoformat(deleted_at)).days
    return "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"
