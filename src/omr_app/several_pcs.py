"""Several PCs on one exam (specs/005-several-pcs): logging in, operators, letting other PCs in, and joining
a main PC's exam from a scanning PC."""

import threading

import numpy as np
import zxingcpp
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from omr_core.lan import MainPC, addresses, send_waiting
from omr_core.store import ROLES, Store

from .theme import settings


class LoginDialog(QDialog):
    """Who is using this PC, once it has operators."""

    def __init__(self, parent, store: Store):
        super().__init__(parent)
        self.setWindowTitle("Log in")
        self.store = store
        self.role = None
        self.name = QComboBox(editable=False)
        self.name.addItems([n for n, _ in store.operators()])
        self.pin = QLineEdit(echoMode=QLineEdit.Password)
        self.error = QLabel(objectName="muted")
        form = QFormLayout(self)
        form.addRow("Who are you?", self.name)
        form.addRow("PIN", self.pin)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Log in")
        buttons.accepted.connect(self.log_in)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def log_in(self):
        self.role = self.store.login(self.name.currentText(), self.pin.text())
        if self.role is None:
            self.error.setText("That PIN isn't right. Ask an admin if you've forgotten it.")
            self.pin.clear()
            return
        self.accept()


class OperatorDialog(QDialog):
    """Add an operator, or give one a new PIN or role."""

    def __init__(self, parent, store: Store, name: str = "", role: str = "operator"):
        super().__init__(parent)
        self.setWindowTitle("Operator")
        self.store = store
        self.name = QLineEdit(name, readOnly=bool(name))
        self.pin = QLineEdit(echoMode=QLineEdit.Password, placeholderText="4 or more numbers or letters")
        self.role = QComboBox()
        self.role.addItems(ROLES)
        self.role.setCurrentText(role if store.operators() else "admin")
        form = QFormLayout(self)
        form.addRow("Name", self.name)
        form.addRow("PIN", self.pin)
        form.addRow("Role", self.role)
        form.addRow(QLabel("An admin can do everything. An operator can scan, review and see results, but can't "
                           "change the answer key or marks, delete sheets or exams, or manage operators.",
                           objectName="muted", wordWrap=True))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self):
        try:
            self.store.add_operator(self.name.text(), self.pin.text(), self.role.currentText())
        except ValueError as e:
            QMessageBox.warning(self, "Can't save", str(e).capitalize() + ".")
            return
        self.accept()


class OperatorsDialog(QDialog):
    def __init__(self, parent, store: Store):
        super().__init__(parent)
        self.setWindowTitle("Operators")
        self.store = store
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Role"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        add = QPushButton("Add…", objectName="primary")
        add.clicked.connect(lambda: (OperatorDialog(self, store).exec(), self.refresh()))
        self.change = QPushButton("New PIN or role…")
        self.change.clicked.connect(self.change_one)
        self.remove = QPushButton("Remove")
        self.remove.clicked.connect(self.remove_one)
        row = QHBoxLayout()
        for b in (add, self.change, self.remove):
            row.addWidget(b)
        row.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("With operators, the app asks who is using it when it opens, and the other PCs that "
                                "scan into this one sign in with a name and PIN from this list. With none, nobody "
                                "logs in.", objectName="muted", wordWrap=True))
        layout.addWidget(self.table)
        layout.addLayout(row)
        self.resize(460, 360)
        self.refresh()

    def chosen(self) -> tuple[str, str] | None:
        rows = self.table.selectionModel().selectedRows()
        return self.store.operators()[rows[0].row()] if rows else None

    def refresh(self):
        ops = self.store.operators()
        self.table.setRowCount(len(ops))
        for r, (name, role) in enumerate(ops):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(role))

    def change_one(self):
        if chosen := self.chosen():
            OperatorDialog(self, self.store, *chosen).exec()
            self.refresh()

    def remove_one(self):
        if chosen := self.chosen():
            try:
                self.store.remove_operator(chosen[0])
            except ValueError as e:
                QMessageBox.warning(self, "Can't remove", str(e).capitalize() + ".")
            self.refresh()


class OtherPcsDialog(QDialog):
    """On the main PC: let other PCs in, its address and join code, and the PCs that joined."""

    def __init__(self, parent, store: Store, window):
        super().__init__(parent)
        self.setWindowTitle("Other PCs")
        self.store, self.window_ = store, window
        self.on = QPushButton(checkable=True)
        self.on.clicked.connect(self.toggle)
        self.where = QLabel(wordWrap=True)
        self.where.setTextInteractionFlags(Qt.TextSelectableByMouse)
        new_code = QPushButton("New join code", toolTip="PCs that already joined keep working; new ones need the new code")
        new_code.clicked.connect(lambda: (store.new_join_code(), self.refresh()))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["PC", "Operator", "Joined"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        remove = QPushButton("Take out", toolTip="The PC can't send any more pages until it joins again")
        remove.clicked.connect(self.take_out)
        top = QHBoxLayout()
        top.addWidget(self.on)
        top.addWidget(new_code)
        top.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Other PCs on your network can scan into this PC's exams with OMR Checker: on that "
                                "PC, go to Exams and press Scan into another PC. Every page is saved on that PC and "
                                "sent here, so nothing is lost if the network drops.", objectName="muted",
                                wordWrap=True))
        layout.addLayout(top)
        layout.addWidget(self.where)
        layout.addWidget(QLabel("PCs that joined", objectName="muted"))
        layout.addWidget(self.table)
        layout.addWidget(remove)
        self.resize(560, 420)
        self.refresh()

    def toggle(self):
        self.window_.let_pcs_in(self.on.isChecked())
        self.refresh()

    def refresh(self):
        server = self.window_.server
        self.on.setChecked(server is not None)
        self.on.setText("Stop letting other PCs in" if server else "Let other PCs scan into this PC")
        if server:
            self.where.setText(f"<b>This PC's address:</b> {' or '.join(addresses())}<br>"
                               f"<b>Join code:</b> {self.store.join_code}")
        else:
            self.where.setText(self.window_.server_error or "Other PCs can't reach this one now.")
        stations = self.store.stations()
        self.table.setRowCount(len(stations))
        for r, (_, operator, pc, joined) in enumerate(stations):
            for c, text in enumerate((pc, operator or "–", joined.replace("T", " "))):
                self.table.setItem(r, c, QTableWidgetItem(text))

    def take_out(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.store.remove_station(self.store.stations()[rows[0].row()][0])
            self.refresh()


class PcsSettings(QWidget):
    """The Settings row: operators, and other PCs scanning into this one."""

    def __init__(self, window):
        super().__init__()
        self.window_ = window
        self.label = QLabel(objectName="muted")
        self.operators = QPushButton("Operators…")
        self.operators.clicked.connect(lambda: (OperatorsDialog(self, window.store).exec(), self.refresh()))
        self.pcs = QPushButton("Other PCs…")
        self.pcs.clicked.connect(lambda: (OtherPcsDialog(self, window.store, window).exec(), self.refresh()))
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.label)
        row.addWidget(self.operators)
        row.addWidget(self.pcs)
        row.addStretch()
        self.refresh()

    def refresh(self):
        n = len(self.window_.store.operators())
        self.label.setText((f"{n} operators" if n else "No logins") + (", other PCs can scan in"
                                                                       if self.window_.server else ""))
        for b in (self.operators, self.pcs):
            b.setEnabled(self.window_.admin)


class JoinDialog(QDialog):
    """On a scanning PC: join a main PC and pick the exam to scan into. `exam_id` is the copy made here."""

    def __init__(self, parent, store: Store):
        super().__init__(parent)
        self.setWindowTitle("Scan into another PC's exam")
        self.store = store
        self.main: MainPC | None = None
        self.main_name = ""
        self.exam_id: int | None = None
        s = settings()
        self.address = QLineEdit(str(s.value("join/address", "")), placeholderText="e.g. 192.168.1.10")
        self.code = QLineEdit(placeholderText="shown on the main PC under Settings, Other PCs")
        self.name = QLineEdit(str(s.value("join/name", "")), placeholderText="leave empty if the main PC has no logins")
        self.pin = QLineEdit(echoMode=QLineEdit.Password)
        connect = QPushButton("Connect", objectName="primary")
        connect.clicked.connect(self.connect_main)
        self.exams = QComboBox()
        self.exams.setEnabled(False)
        self.status = QLabel(objectName="muted", wordWrap=True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Scan into this exam")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.open_exam)
        self.buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(QLabel("Pages you scan are saved on this PC and sent to the main PC as you go; they wait here "
                           "whenever the main PC can't be reached.", objectName="muted", wordWrap=True))
        form.addRow("Main PC's address", self.address)
        form.addRow("Join code", self.code)
        form.addRow("Your name", self.name)
        form.addRow("PIN", self.pin)
        form.addRow(connect)
        form.addRow("Exam", self.exams)
        form.addRow(self.status)
        form.addRow(self.buttons)
        self.resize(480, 0)

    def connect_main(self):
        self.main = MainPC(self.address.text())
        try:
            self.main_name = self.main.join(self.code.text(), self.name.text(), self.pin.text())
            exams = self.main.exams()
        except PermissionError as e:
            self.status.setText(f"The main PC said: {e}.")
            return
        except (OSError, ValueError) as e:
            self.status.setText(f"Can't reach the main PC at {self.main.address}: {e}. Check the address, that both "
                                "PCs are on the same network, and that the main PC lets other PCs in.")
            return
        s = settings()
        s.setValue("join/address", self.address.text().strip())
        s.setValue("join/name", self.name.text().strip())
        self.exams.clear()
        for e in exams:
            self.exams.addItem(e["name"], e["id"])
        self.exams.setEnabled(bool(exams))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(exams))
        self.status.setText(f"Connected to {self.main_name}." if exams else
                            f"Connected to {self.main_name}, but it has no open exams.")

    def open_exam(self):
        remote = self.exams.currentData()
        try:
            self.exam_id = self.store.copy_exam(self.main.exam(remote), self.main.address, remote, self.main.token,
                                                self.main_name)
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.status.setText(f"Couldn't get the exam from the main PC: {e}")
            return
        self.accept()


def refresh_copy(store: Store, exam_id: int) -> str:
    """Bring a linked exam's key, marks and list up to date from its main PC; "" or why it couldn't."""
    address, remote, token, main_name = store.link(exam_id)
    try:
        store.copy_exam(MainPC(address, token, timeout=3).exam(remote), address, remote, token, main_name)
    except PermissionError:
        return f"{main_name} took this PC out; join it again to send pages."
    except (OSError, ValueError, KeyError, TypeError):
        return f"Can't reach {main_name} now, so the answer key may not be its latest."
    return ""


class Sender(QObject):
    """Sends a linked exam's waiting pages on its own thread and database connection; `done` says how it went:
    (exam id, pages sent, refused pages, what stopped it or "")."""

    done = Signal(int, int, list, str)

    def __init__(self, db_path: str | Path):
        super().__init__()
        self.db_path = db_path
        self.busy = False

    def start(self, exam_id: int):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._run, args=(exam_id,), daemon=True).start()

    def _run(self, exam_id: int):
        store = Store(self.db_path)
        sent, refused, error = 0, [], ""
        try:
            sent, refused = send_waiting(store, exam_id)
        except PermissionError:
            error = "taken out"
        except OSError:
            error = "unreachable"
        finally:
            store.close()
            self.busy = False
        self.done.emit(exam_id, sent, refused, error)


def qr_pixmap(text: str, size: int = 260) -> QPixmap:
    make = getattr(zxingcpp, "create_barcode", None)  # zxing-cpp 3; write_barcode before it
    image = np.ascontiguousarray(make(text, zxingcpp.BarcodeFormat.QRCode).to_image(scale=8, add_quiet_zones=True)
                                 if make else zxingcpp.write_barcode(zxingcpp.BarcodeFormat.QRCode, text, size, size))
    q = QImage(image.data, image.shape[1], image.shape[0], image.strides[0], QImage.Format_Grayscale8).copy()
    return QPixmap.fromImage(q).scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation)


class PhoneDialog(QDialog):
    """The QR code a phone on the same Wi-Fi opens to photograph sheets into the open exam, and how many came."""

    def __init__(self, parent, links: tuple[str, str], exam_name: str, arrived):
        super().__init__(parent)
        self.setWindowTitle("Scan with a phone")
        secure, plain = links
        code = QLabel(alignment=Qt.AlignCenter)
        code.setPixmap(qr_pixmap(secure or plain))
        self.count, self.got = QLabel(objectName="muted"), 0
        self.count.setText("Waiting for the first sheet…")
        arrived.connect(self.one_more)
        self.finished.connect(lambda _: arrived.disconnect(self.one_more))
        steps = QLabel(wordWrap=True, textInteractionFlags=Qt.TextSelectableByMouse)
        steps.setText(
            f"<b>Photograph the sheets of {exam_name} with a phone</b><ol>"
            "<li>Connect the phone to the same Wi-Fi as this PC.</li>"
            "<li>Open the phone's camera and point it at this QR code, then open the link.</li>"
            + ("<li>The phone warns that the connection isn't private, because the address belongs to this PC and "
               "not to a website. That is expected here: tap <b>Advanced</b>, then <b>Proceed</b> (or "
               "<b>Show details</b>, then <b>visit this website</b> on an iPhone). It asks once.</li>"
               "<li>Allow the camera. Put each sheet down flat in good light and hold the phone over it until its "
               "four corner marks sit in the targets and turn green: it takes the photo by itself, says the roll "
               "number read, and waits for the next sheet.</li></ol>" if secure else
               "<li>Press <b>Photos…</b> for each sheet.</li></ol>")
            + f"<p>Without the warning, open <a href='{plain}'>{plain}</a> instead, and press <b>Photos…</b> "
              "for each sheet.</p>"
            "<p>Each sheet is read here; a photo that can't be read is never saved, and the phone asks for it "
            "again. Keep the phone's page open until it says everything is sent.</p>")
        steps.setOpenExternalLinks(False)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(code)
        row.addWidget(steps, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.count)
        layout.addWidget(close)
        self.resize(760, 0)

    def one_more(self, _exam_id: int):
        self.got += 1
        self.count.setText(f"Sheets received while this is open: {self.got}. They're on Scanned sheets.")
