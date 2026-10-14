"""Institutes: the name, logo and details printed on an institute's sheets, scorecards and exports.

One is the default for every exam; an exam can pick another under Exam settings. The preview is a real
scorecard, made as it is typed.
"""

import tempfile
from pathlib import Path

import pypdfium2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from omr_core.branding import Institute, check, prepare_logo
from omr_core.export import sample_scorecard
from omr_core.store import Store

FIELDS = [("name", "Name"), ("address", "Address"), ("phone", "Phone"), ("email", "Email"), ("website", "Website"),
          ("motto", "Motto"), ("signer_name", "Signed by"), ("signer_title", "Their title"),
          ("footer", "Footer line")]
HINTS = {"name": "e.g. Sunrise Academy", "signer_name": "e.g. R. Sharma; leave empty for no signature line",
         "signer_title": "e.g. Principal", "footer": "e.g. Results are provisional until published on the notice board",
         "motto": "optional"}


def logo_pixmap(logo: bytes, height: int) -> QPixmap:
    image = QImage.fromData(logo)
    return QPixmap.fromImage(image).scaledToHeight(height, Qt.SmoothTransformation) if not image.isNull() else QPixmap()


class InstitutesDialog(QDialog):
    def __init__(self, parent, store: Store):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Institutes")
        self.resize(1080, 720)
        self.current: int | None = None  # the id being edited; None for a new one not saved yet
        self.logo = b""
        self.colour = Institute.colour

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda item, _: self.load(item.data(Qt.UserRole) if item else None))
        new = QPushButton("New")
        new.clicked.connect(self.new)
        self.default = QPushButton("Make default")
        self.default.setToolTip("Exams that haven't picked an institute use the default one")
        self.default.clicked.connect(self.make_default)
        self.delete = QPushButton("Delete…")
        self.delete.clicked.connect(self.remove)
        left = QVBoxLayout()
        left.addWidget(QLabel("Your institutes", objectName="muted"))
        left.addWidget(self.list, 1)
        for b in (new, self.default, self.delete):
            left.addWidget(b)

        self.edits: dict[str, QLineEdit | QPlainTextEdit] = {}
        form = QFormLayout()
        for key, label in FIELDS:
            edit = QPlainTextEdit() if key == "address" else QLineEdit()
            if key == "address":
                edit.setFixedHeight(52)
                edit.setPlaceholderText("Street, city")
                edit.textChanged.connect(self.changed)
            else:
                edit.setPlaceholderText(HINTS.get(key, ""))
                edit.textEdited.connect(self.changed)
            self.edits[key] = edit
            form.addRow(label, edit)
        self.logo_view = QLabel("No logo", objectName="muted")
        self.logo_view.setFixedHeight(64)
        pick = QPushButton("Choose logo…")
        pick.setToolTip("A PNG or JPEG; empty margins are trimmed. A transparent PNG looks best.")
        pick.clicked.connect(self.pick_logo)
        self.drop_logo = QPushButton("Remove")
        self.drop_logo.clicked.connect(lambda: self.set_logo(b""))
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_view)
        logo_row.addWidget(pick)
        logo_row.addWidget(self.drop_logo)
        logo_row.addStretch()
        form.insertRow(1, "Logo", logo_row)
        self.colour_button = QPushButton()
        self.colour_button.setFixedWidth(120)
        self.colour_button.clicked.connect(self.pick_colour)
        form.insertRow(2, "Colour", self.colour_button)
        self.problem = QLabel(objectName="error", wordWrap=True)
        self.save_button = QPushButton("Save", objectName="primary")
        self.save_button.clicked.connect(self.save)
        middle = QVBoxLayout()
        middle.addLayout(form)
        middle.addWidget(self.problem)
        middle.addWidget(self.save_button, 0, Qt.AlignLeft)
        middle.addStretch()

        self.preview = QLabel(alignment=Qt.AlignHCenter | Qt.AlignTop)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(self.preview)
        scroll.setMinimumWidth(440)
        right = QVBoxLayout()
        right.addWidget(QLabel("Preview: a scorecard", objectName="muted"))
        right.addWidget(scroll, 1)
        self.timer = QTimer(self, singleShot=True, interval=250)  # typing redraws once it pauses
        self.timer.timeout.connect(self.draw_preview)

        body = QHBoxLayout()
        body.addLayout(left, 2)
        body.addLayout(middle, 4)
        body.addLayout(right, 4)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)
        self.fill_list()
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.new()

    # -- the list ------------------------------------------------------------------------------------------

    def fill_list(self, select: int | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        for i, inst, default in self.store.institutes():
            item = QListWidgetItem(inst.name + ("  (default)" if default else ""))
            item.setData(Qt.UserRole, i)
            if inst.logo:
                item.setIcon(logo_pixmap(inst.logo, 32))
            self.list.addItem(item)
            if i == select:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.delete.setEnabled(self.list.count() > 0)

    def load(self, institute_id: int | None):
        rows = {i: (inst, d) for i, inst, d in self.store.institutes()}
        inst, default = rows.get(institute_id, (Institute(""), False))
        self.current = institute_id if institute_id in rows else None
        for key, edit in self.edits.items():
            (edit.setPlainText if isinstance(edit, QPlainTextEdit) else edit.setText)(getattr(inst, key))
        self.colour = inst.colour
        self.set_logo(inst.logo)
        self.default.setEnabled(self.current is not None and not default)
        self.problem.clear()
        self.draw_preview()

    def new(self):
        self.list.clearSelection()
        self.list.setCurrentItem(None)
        self.load(None)
        self.edits["name"].setFocus()

    # -- editing -------------------------------------------------------------------------------------------

    def institute(self) -> Institute:
        values = {key: edit.toPlainText() if isinstance(edit, QPlainTextEdit) else edit.text()
                  for key, edit in self.edits.items()}
        return Institute(**values, colour=self.colour, logo=self.logo)

    def changed(self):
        self.timer.start()

    def set_logo(self, logo: bytes):
        self.logo = logo
        if logo:
            self.logo_view.setPixmap(logo_pixmap(logo, 60))
        else:
            self.logo_view.setPixmap(QPixmap())
            self.logo_view.setText("No logo")
        self.drop_logo.setEnabled(bool(logo))
        self.changed()

    def pick_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Logo", "", "Pictures (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        try:
            logo = prepare_logo(Path(path).read_bytes())
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Can't use that logo", f"{Path(path).name}\n\n{e}")
            return
        self.set_logo(logo)

    def pick_colour(self):
        colour = QColorDialog.getColor(QColor(self.colour), self, "Institute colour")
        if colour.isValid():
            self.colour = colour.name()
            self.changed()

    def save(self) -> bool:
        try:
            self.current = self.store.save_institute(self.institute(), self.current)
        except ValueError as e:
            self.problem.setText(f"Not saved: {e}.")
            return False
        self.problem.clear()
        self.fill_list(self.current)
        self.default.setEnabled(not dict((i, d) for i, _, d in self.store.institutes())[self.current])
        return True

    def make_default(self):
        if self.current is not None:
            self.store.set_default_institute(self.current)
            self.fill_list(self.current)
            self.default.setEnabled(False)

    def remove(self):
        if self.current is None:
            return
        name = self.institute().name or "this institute"
        if QMessageBox.question(self, "Delete institute", f"Delete {name}? Its exams print the default institute "
                                "instead. Exams and results are not touched.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.store.delete_institute(self.current)
        self.fill_list()
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.new()

    # -- preview -------------------------------------------------------------------------------------------

    def draw_preview(self):
        self.colour_button.setText(self.colour)
        self.colour_button.setStyleSheet(f"QPushButton {{ background: {self.colour}; color: white; }}")
        try:
            inst = check(self.institute())
        except ValueError as e:
            if self.institute().name.strip():  # an empty name while starting a new one isn't worth a warning
                self.problem.setText(f"{e}.")
            inst = None
        else:
            self.problem.clear()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            path = Path(d) / "preview.pdf"
            sample_scorecard(path, inst)
            pdf = pypdfium2.PdfDocument(str(path))
            try:
                image = pdf[0].render(scale=1.6).to_pil().convert("RGB")
            finally:
                pdf.close()
        data = image.tobytes()
        qimage = QImage(data, image.width, image.height, 3 * image.width, QImage.Format_RGB888).copy()
        self.preview.setPixmap(QPixmap.fromImage(qimage).scaledToWidth(420, Qt.SmoothTransformation))

    def reject(self):
        if self.current is None and self.institute().name.strip() or self.current is not None and self._unsaved():
            answer = QMessageBox.question(self, "Save changes", "Save the changes to this institute?",
                                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                          QMessageBox.Save)
            if answer == QMessageBox.Cancel or answer == QMessageBox.Save and not self.save():
                return
        super().reject()

    def _unsaved(self) -> bool:
        saved = {i: inst for i, inst, _ in self.store.institutes()}.get(self.current)
        try:
            return saved != check(self.institute())
        except ValueError:
            return True


class InstituteSettings(QWidget):
    """The Settings row: the default institute, and the button to edit them."""

    def __init__(self, store: Store, edited):
        super().__init__()
        self.store = store
        self.edited = edited  # called after the dialog closes, to redraw what shows the institute
        self.logo = QLabel()
        self.label = QLabel(objectName="muted")
        edit = QPushButton("Institutes…")
        edit.setToolTip("Your institute's name, logo, address and signature, for sheets, scorecards and exports")
        edit.clicked.connect(self.open)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.logo)
        row.addWidget(self.label)
        row.addWidget(edit)
        row.addStretch()
        self.refresh()

    def refresh(self):
        default = next((inst for _, inst, d in self.store.institutes() if d), None)
        self.label.setText(f"Default: {default.name}" if default else "None yet: scorecards print no letterhead")
        self.logo.setPixmap(logo_pixmap(default.logo, 28) if default and default.logo else QPixmap())

    def open(self):
        InstitutesDialog(self, self.store).exec()
        self.refresh()
        self.edited()
