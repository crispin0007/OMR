"""Exams page: create exams and open one. Each exam keeps its own template, key, marks, students and sheets.

Back up copies every exam into one file; Restore adds the exams in such a file, on this PC or a new one.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressDialog, QPushButton,
                               QTabBar, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from omr_core.store import TRASH_DAYS, Folder, Store

from .dashboard import ShownPage
from .help import steps_html
from .new_exam import TEMPLATES, USER_TEMPLATES, NewExamWizard  # noqa: F401  (TEMPLATES is used by window.py)
from .series import SeriesDialog
from .several_pcs import JoinDialog

class ExamsPage(ShownPage):
    """Every exam; click one to open its page."""

    opened = Signal(object)  # exam id

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.open_id: int | None = None
        self.purged: list[str] = []  # exams the Trash deleted for good when the app started
        self.admin = True  # an operator logged in can't restore backups or delete exams for good
        new = QPushButton("New exam…", objectName="primary")
        new.clicked.connect(self.new_exam)
        backup = QPushButton("Back up…", toolTip="Save every exam, with its sheets, corrections and students, "
                             "in one file to keep safe or take to another PC")
        backup.clicked.connect(self.backup)
        restore = QPushButton("Restore…", toolTip="Add the exams in a backup file; exams already here stay as they are")
        restore.clicked.connect(self.restore)
        self.restore_backup = restore
        join = QPushButton("Scan into another PC…", toolTip="Scan on this PC into an exam kept on another PC on "
                           "your network; each page is sent there")
        join.clicked.connect(self.join)
        self.series = QPushButton("Test series…", toolTip="Rank students on their combined score over the exams "
                                  "of a test series")
        self.series.clicked.connect(lambda: SeriesDialog(self, self.store, program=self.program_chosen()).exec())
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
        top.addWidget(join)
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
        self.search = QLineEdit(placeholderText="Search exams", clearButtonEnabled=True)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(lambda _: self.redraw())
        actions = QHBoxLayout()
        actions.addWidget(self.views)
        actions.addWidget(self.search)
        actions.addStretch()
        for b in (self.open_button, self.unarchive, self.restore_button, self.delete_button, self.empty):
            actions.addWidget(b)
        self.start = QLabel(f"<h3>Getting started</h3>{steps_html()}", objectName="card", wordWrap=True,
                            textFormat=Qt.RichText)
        self.start.setContentsMargins(20, 12, 20, 12)
        self.start.setMaximumWidth(760)
        self.table = QTableWidget(0, 6)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self.clicked)
        self.table.itemSelectionChanged.connect(self.enable)
        self.tree = QTreeWidget(headerHidden=True)
        self.tree.setMaximumWidth(260)
        self.tree.currentItemChanged.connect(lambda *_: self.redraw_list())
        self.new_program = QPushButton("New program…", toolTip="A course you prepare students for, e.g. IOE, "
                                       "Medical or CMAT, with its own exams and test series")
        self.new_program.clicked.connect(lambda: self.edit_folder(None, None))
        self.new_category = QPushButton("New category…", toolTip="A group of exams inside the chosen program, "
                                        "e.g. Chapter tests or Full mocks")
        self.new_category.clicked.connect(lambda: self.edit_folder(None, self.program_chosen()))
        self.change_folder = QPushButton("Change…")
        self.change_folder.clicked.connect(lambda: self.edit_folder(self.folder_chosen(), None))
        self.delete_folder = QPushButton("Delete…")
        self.delete_folder.clicked.connect(self.remove_folder)
        side = QVBoxLayout()
        side.addWidget(QLabel("Programs", objectName="muted"))
        side.addWidget(self.tree, 1)
        for b in (self.new_program, self.new_category, self.change_folder, self.delete_folder):
            side.addWidget(b)
        self.side = QWidget()
        self.side.setLayout(side)
        self.side.setMaximumWidth(260)
        right = QVBoxLayout()
        right.addLayout(actions)
        right.addWidget(self.table, 1)
        body = QHBoxLayout()
        body.addWidget(self.side)
        body.addLayout(right, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.note)
        layout.addLayout(body, 1)
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
        self.fill_tree()
        self.redraw_list()

    def fill_tree(self):
        """Programs with their categories, and how many exams each has (theirs and their categories')."""
        chosen = self.tree.currentItem().data(0, Qt.UserRole) if self.tree.currentItem() else "all"
        folders = self.store.folders()
        where = self.store.exam_folders()
        kept = [i for i, *_ in self.store.exams("kept")]
        parents = {f.id: f.parent for f in folders}

        def count(folder) -> int:
            return sum(where.get(i) == folder or parents.get(where.get(i)) == folder for i in kept)
        self.tree.blockSignals(True)
        self.tree.clear()
        top = QTreeWidgetItem([f"All exams ({len(kept)})"])
        top.setData(0, Qt.UserRole, "all")
        self.tree.addTopLevelItem(top)
        items = {"all": top}
        for f in folders:
            if f.parent is None:
                items[f.id] = self._folder_item(f, count(f.id))
                self.tree.addTopLevelItem(items[f.id])
        for f in folders:
            if f.parent in items:
                items[f.id] = self._folder_item(f, count(f.id))
                items[f.parent].addChild(items[f.id])
        if folders:
            none = QTreeWidgetItem([f"No program ({sum(where.get(i) is None for i in kept)})"])
            none.setData(0, Qt.UserRole, "none")
            self.tree.addTopLevelItem(none)
            items["none"] = none
        self.tree.expandAll()
        self.tree.setCurrentItem(items.get(chosen, top))
        self.tree.blockSignals(False)

    @staticmethod
    def _folder_item(f: Folder, n: int) -> QTreeWidgetItem:
        item = QTreeWidgetItem([f"{f.name} ({n})"])
        item.setData(0, Qt.UserRole, f.id)
        if f.colour:
            dot = QPixmap(12, 12)
            dot.fill(QColor(f.colour))
            item.setIcon(0, dot)
        return item

    def folder_chosen(self) -> int | None:
        """The program or category picked in the tree; None for All exams or No program."""
        item = self.tree.currentItem()
        data = item.data(0, Qt.UserRole) if item else None
        return data if isinstance(data, int) else None

    def program_chosen(self) -> int | None:
        """The program picked, or the program of the category picked."""
        folder = self.folder_chosen()
        parents = {f.id: f.parent for f in self.store.folders()}
        return parents.get(folder) or folder

    def redraw_list(self):
        view = self.view()
        trash = self.store.trash()
        folders = {f.id: f for f in self.store.folders()}
        where = self.store.exam_folders()
        picked = self.tree.currentItem().data(0, Qt.UserRole) if self.tree.currentItem() else "all"
        words = self.search.text().lower().split()

        def shown(exam_id: int, name: str) -> bool:
            folder = where.get(exam_id)
            inside = (picked == "all" or view == "trash" or picked == "none" and folder is None
                      or folder == picked or folder in folders and folders[folder].parent == picked)
            return inside and all(w in name.lower() for w in words)

        def path(exam_id: int) -> str:
            f = folders.get(where.get(exam_id))
            return "" if f is None else f"{folders[f.parent].name} › {f.name}" if f.parent in folders else f.name
        exams = [e for e in self.store.exams(view) if shown(e[0], e[1])] if view != "trash" else []
        trash = [t for t in trash if shown(t[0], t[1])] if view == "trash" else trash
        archived = len(self.store.exams("archived"))
        self.views.setTabText(1, f"Archived ({archived})" if archived else "Archived")
        self.views.setTabText(2, f"Trash ({len(self.store.trash())})" if self.store.trash() else "Trash")
        anything = bool(self.store.exams("kept") or self.store.trash())
        self.views.setVisible(bool(archived or self.store.trash() or view != "active"))
        notes = {"active": "Click an exam to open it: scan, check, set the key and marks, see results and print its "
                           "sheet. Everything is saved as you work."
                           if exams or words or picked != "all" else
                           "Create an exam to start: New exam walks you through it and makes its sheet."
                           if not anything else "No exams on the list. Archived exams and the Trash are above.",
                 "archived": "Finished exams put away from the list. They keep their sheets and results, stay in "
                             "test series and backups, and open as usual.",
                 "trash": f"Deleted exams, with everything read for them. Each is deleted for good {TRASH_DAYS} days "
                          "after it was moved here; until then Restore brings it back as it was."}
        note = notes[view]
        if isinstance(picked, int) and picked in folders and view != "trash":
            ids = {e[0] for e in exams}
            series = {self.store.exam(i).details.get("series") for i in ids} - {None, ""}
            note = (f"{folders[picked].name}: {len(exams)} exam{'s' if len(exams) != 1 else ''}, "
                    f"{len(series)} test series, {sum(e[3] for e in exams):,} sheets read. New exam puts the new one "
                    "here.  " + note)
        if self.purged:
            note += (f"\n\nDeleted for good after {TRASH_DAYS} days in the Trash: {', '.join(self.purged)}.")
        self.note.setText(note)
        self.side.setVisible(anything)
        self.search.setVisible(anything)
        self.table.setVisible(anything)
        self.series.setVisible(bool(self.store.series_names()))
        self.shrink.setVisible(self.store.png_pages() > 0)
        self.start.setVisible(not anything)  # first run: what to do, in order
        if view == "trash":
            now = datetime.now()
            self.table.setHorizontalHeaderLabels(["Exam", "Deleted", "Sheets", "Deleted for good", "Program", ""])
            rows = [(i, (name, at.replace("T", "  "), str(pages), _left(at, now), path(i), ""))
                    for i, name, at, pages in trash]
        else:
            self.table.setHorizontalHeaderLabels(["Exam", "Created", "Sheets", "Students", "Program", ""])
            rows = [(i, (name, created.replace("T", "  "), str(pages), str(students or ""), path(i),
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
        chosen = self.folder_chosen()
        self.new_category.setEnabled(self.program_chosen() is not None)
        self.change_folder.setEnabled(chosen is not None)
        self.delete_folder.setEnabled(chosen is not None)

    def edit_folder(self, folder_id: int | None, parent: int | None):
        folder = next((f for f in self.store.folders() if f.id == folder_id), None)
        dialog = FolderDialog(self, self.store, folder, parent)
        if dialog.exec():
            self.redraw()
            self.tree.setCurrentItem(next(self._items(dialog.saved), self.tree.currentItem()))

    def _items(self, folder_id: int):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item.data(0, Qt.UserRole) == folder_id:
                yield item
            stack += [item.child(i) for i in range(item.childCount())]

    def remove_folder(self):
        folder = next(f for f in self.store.folders() if f.id == self.folder_chosen())
        what = "category" if folder.parent else "program and its categories"
        to = "its program" if folder.parent else "No program"
        if QMessageBox.question(self, "Delete", f"Delete the {what} “{folder.name}”? Its exams are kept and move to "
                                f"{to}.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.store.delete_folder(folder.id)
            self.redraw()

    def enable(self):
        view, chosen = self.view(), self.chosen() is not None
        for button, shown in ((self.open_button, view == "archived"), (self.unarchive, view == "archived"),
                              (self.restore_button, view == "trash"), (self.delete_button, view == "trash"),
                              (self.empty, view == "trash")):
            button.setVisible(shown)
            button.setEnabled((chosen or button is self.empty and bool(self.store.trash()))
                              and (self.admin or button in (self.open_button, self.unarchive)))
        self.restore_backup.setEnabled(self.admin)

    def chosen(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def clicked(self, row: int, _):
        if self.view() == "active":  # elsewhere a click picks the exam for the buttons
            self.opened.emit(self.table.item(row, 0).data(Qt.UserRole))

    def put_back_archived(self):
        self.store.set_archived(self.chosen(), False)
        self.redraw_list()

    def restore_from_trash(self):
        exam = self.chosen()
        self.store.put_back(exam)
        self.redraw_list()

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
            self.store.set_exam_folder(wizard.exam_id, self.folder_chosen())
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

    def join(self):
        dialog = JoinDialog(self, self.store)
        if dialog.exec():
            self.opened.emit(dialog.exam_id)

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


class FolderDialog(QDialog):
    """A program or a category: its name, colour and the institute its exams print."""

    def __init__(self, parent, store: Store, folder: Folder | None, program: int | None):
        super().__init__(parent)
        self.store, self.folder = store, folder
        self.parent_id = folder.parent if folder else program
        kind = "category" if self.parent_id else "program"
        self.setWindowTitle(f"Change {kind}" if folder else f"New {kind}")
        self.saved: int | None = None
        self.name = QLineEdit(folder.name if folder else "")
        self.name.setPlaceholderText("e.g. Full mocks" if self.parent_id else "e.g. IOE, Medical or CMAT")
        self.colour = folder.colour if folder else ""
        self.colour_button = QPushButton()
        self.colour_button.clicked.connect(self.pick_colour)
        self.institute = QComboBox()
        self.institute.addItem("The default" if not self.parent_id else "As its program", None)
        for i, inst, _ in store.institutes():
            self.institute.addItem(inst.name, i)
        if folder and folder.institute is not None:
            self.institute.setCurrentIndex(max(0, self.institute.findData(folder.institute)))
        self.institute.setEnabled(self.institute.count() > 1)
        self.problem = QLabel(objectName="error", wordWrap=True)
        form = QFormLayout(self)
        form.addRow("Name", self.name)
        form.addRow("Colour", self.colour_button)
        form.addRow("Institute", self.institute)
        form.addRow(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.show_colour()

    def show_colour(self):
        self.colour_button.setText(self.colour or "None")
        self.colour_button.setStyleSheet(f"QPushButton {{ background: {self.colour}; color: white; }}"
                                         if self.colour else "")

    def pick_colour(self):
        colour = QColorDialog.getColor(QColor(self.colour or "#1565c0"), self, "Colour")
        if colour.isValid():
            self.colour = colour.name()
            self.show_colour()

    def save(self):
        try:
            self.saved = self.store.save_folder(self.name.text(), self.parent_id, self.colour,
                                                self.institute.currentData(), self.folder.id if self.folder else None)
        except ValueError as e:
            self.problem.setText(f"Not saved: {e}.")
            return
        self.accept()
