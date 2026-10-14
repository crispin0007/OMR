"""Emailing and texting each student their result: set up once under Settings, then Send to students… on Results.

Both are off until set up, and the app works fully offline without them. Server and gateway settings are kept in
the app's settings file; passwords and API keys only in the system's credential store (Windows Credential
Manager), never in the database, a backup or the send log.
"""

import json
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from omr_core import sending
from omr_core.sending import (EMAIL_BODY, FIELDS, GATEWAYS, LIMITS, SERVERS, SMS_BODY, SUBJECT, WHATSAPP_BODY,
                              EmailSettings, Mailer, Message, SmsSettings, check_email_settings, check_sms_settings,
                              international, send_sms, sms_parts, to_whom, wait, whatsapp_link)
from omr_core.store import Store
from omr_core.students import same_roll

from .theme import settings

SERVICE = "OMR Checker"


# -- secrets and settings ------------------------------------------------------------------------------------

def get_secret(name: str) -> str:
    """A saved password or API key; "" when none is saved or the system has no credential store."""
    try:
        import keyring
        return keyring.get_password(SERVICE, name) or ""
    except Exception:  # keyring raises its own errors, and ImportError when it isn't installed
        return ""


def set_secret(name: str, value: str):
    """Keep a password or API key in the system's credential store. Raises RuntimeError when there is none."""
    try:
        import keyring
        keyring.set_password(SERVICE, name, value)
    except Exception as e:
        raise RuntimeError(f"this PC has no credential store to keep it safely ({e})") from e


def load(channel: str) -> tuple[EmailSettings | SmsSettings | None, dict]:
    """The saved settings for "email" or "sms" (None when not set up) and their extras: the limits, a preset's
    name and, for SMS, the country code."""
    raw = settings().value(f"sending/{channel}", "")
    try:
        d = json.loads(raw) if raw else None
        kind = EmailSettings if channel == "email" else SmsSettings
        return (kind(**d["settings"]), d["extra"]) if d else (None, {})
    except (ValueError, TypeError, KeyError):
        return None, {}  # the file was edited by hand: set it up again


def save(channel: str, s, extra: dict):
    settings().setValue(f"sending/{channel}", json.dumps({"settings": asdict(s), "extra": extra}))


def secret_name(channel: str, s) -> str:
    if channel == "email":
        return f"smtp:{s.user or s.sender}@{s.host}"
    return f"twilio:{s.user or s.account}" if s.kind == "twilio" else f"sms:{s.url.split('?')[0]}"


def limits_row(values: tuple[int, int, int]) -> tuple[QWidget, list[QSpinBox]]:
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    spins = []
    for v, unit in zip(values, ("a minute", "an hour", "a day")):
        spin = QSpinBox(minimum=1, maximum=1000000, value=v, suffix=f" {unit}")
        spins.append(spin)
        h.addWidget(spin)
    return row, spins


# -- set up --------------------------------------------------------------------------------------------------

class EmailSetup(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Email: set up")
        s, extra = load("email")
        s = s or EmailSettings()
        self.provider = QComboBox()
        self.provider.addItems(list(LIMITS)[:5] + ["Other"])
        self.provider.setCurrentText(extra.get("preset", "Gmail"))
        self.provider.activated.connect(self.preset)
        self.host = QLineEdit(s.host)
        self.port = QSpinBox(minimum=1, maximum=65535, value=s.port)
        self.security = QComboBox()
        for label, key in (("STARTTLS (usually port 587)", "starttls"), ("SSL (usually port 465)", "ssl"),
                           ("None (a test server only)", "none")):
            self.security.addItem(label, key)
        self.security.setCurrentIndex(self.security.findData(s.security))
        self.user = QLineEdit(s.user)
        self.password = QLineEdit(echoMode=QLineEdit.Password)
        self.password.setPlaceholderText("saved in Credential Manager" if get_secret(secret_name("email", s))
                                         else "an app password, not your account's own")
        self.sender = QLineEdit(s.sender, placeholderText="results@your-institute.edu.np")
        self.sender_name = QLineEdit(s.sender_name, placeholderText="your institute's name")
        self.reply_to = QLineEdit(s.reply_to, placeholderText="optional: where replies go")
        self.cc = QLineEdit(s.cc, placeholderText="optional: a copy of every email, e.g. the office")
        row, self.limits = limits_row(tuple(extra.get("limits", LIMITS["Gmail"])))
        form = QFormLayout(self)
        form.addRow(QLabel("Results are sent from your own email account. Gmail and Outlook need 2-step "
                           "verification and an app password. The password is kept in Windows Credential "
                           "Manager, never in your exams or backups.", objectName="muted", wordWrap=True))
        for label, w in (("Provider", self.provider), ("Server", self.host), ("Port", self.port),
                         ("Security", self.security), ("User name", self.user), ("Password", self.password),
                         ("From address", self.sender), ("From name", self.sender_name),
                         ("Reply to", self.reply_to), ("Copy to", self.cc), ("At most", row)):
            form.addRow(label, w)
        self.problem = QLabel(objectName="error", wordWrap=True)
        form.addRow(self.problem)
        test = QPushButton("Send a test email…")
        test.clicked.connect(self.test)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.addButton(test, QDialogButtonBox.ActionRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        if not s.host:
            self.preset()

    def preset(self):
        name = self.provider.currentText()
        if name in SERVERS:
            host, port, security = SERVERS[name]
            self.host.setText(host)
            self.port.setValue(port)
            self.security.setCurrentIndex(self.security.findData(security))
        for spin, v in zip(self.limits, LIMITS.get(name, LIMITS["Other"])):
            spin.setValue(v)

    def settings(self) -> EmailSettings:
        return check_email_settings(EmailSettings(
            self.host.text().strip(), self.port.value(), self.security.currentData(), self.user.text().strip(),
            self.sender.text().strip(), self.sender_name.text().strip(), self.reply_to.text().strip(),
            self.cc.text().strip()))

    def secret(self, s: EmailSettings) -> str:
        return self.password.text() or get_secret(secret_name("email", s))

    def save(self) -> bool:
        try:
            s = self.settings()
            if self.password.text():
                set_secret(secret_name("email", s), self.password.text())
        except (ValueError, RuntimeError) as e:
            self.problem.setText(f"Not saved: {e}.")
            return False
        save("email", s, {"preset": self.provider.currentText(), "limits": [x.value() for x in self.limits]})
        self.accept()
        return True

    def test(self):
        try:
            s = self.settings()
        except ValueError as e:
            self.problem.setText(f"{e}.")
            return
        to, ok = QInputDialog.getText(self, "Send a test email", "Send it to", text=s.sender)
        if not ok or not to.strip():
            return
        try:
            mailer = Mailer(s, self.secret(s))
            try:
                mailer.send(Message("", "", to.strip(), "OMR Checker: test email",
                                    "This is a test from OMR Checker. If it arrived, results can be sent from "
                                    "this account."))
            finally:
                mailer.close()
        except Exception as e:  # smtplib and ssl raise many kinds; each is a message for the person
            self.problem.setText(f"The test didn't go: {e}")
            return
        self.problem.clear()
        QMessageBox.information(self, "Sent", f"A test email went to {to.strip()}. If it isn't in the inbox, look "
                                "in spam; see the guide about SPF, DKIM and DMARC for your own domain.")


class SmsSetup(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("SMS: set up")
        s, extra = load("sms")
        s = s or SmsSettings()
        self.kind = QComboBox()
        self.kind.addItems(["Twilio", *GATEWAYS, "Another gateway"])
        self.kind.setCurrentText(extra.get("preset", "Twilio"))
        self.kind.activated.connect(self.preset)
        self.account = QLineEdit(s.account, placeholderText="AC…")
        self.user = QLineEdit(s.user, placeholderText="optional: an API key SID (SK…) instead of the account")
        self.sender = QLineEdit(s.sender, placeholderText="Twilio: +1…; a gateway: your sender ID")
        self.url = QLineEdit(s.url, placeholderText="https://… with {to} {message} {sender} {key} where needed")
        self.method = QComboBox()
        self.method.addItems(["POST", "GET"])
        self.method.setCurrentText(s.method)
        self.headers = QPlainTextEdit(s.headers)
        self.headers.setFixedHeight(48)
        self.body = QPlainTextEdit(s.body)
        self.body.setFixedHeight(48)
        self.success = QLineEdit(s.success, placeholderText="optional: text in the reply that means sent")
        self.key = QLineEdit(echoMode=QLineEdit.Password)
        self.key.setPlaceholderText("saved in Credential Manager" if (s.account or s.url) and get_secret(
            secret_name("sms", s)) else "the auth token or API key")
        self.code = QLineEdit(extra.get("code", ""), placeholderText="e.g. +977; empty sends numbers as saved")
        row, self.limits = limits_row(tuple(extra.get("limits", LIMITS["Twilio"])))
        self.form = form = QFormLayout(self)
        form.addRow(QLabel("Texts go through your own SMS account. The token or key is kept in Windows Credential "
                           "Manager. In India, an SMS needs a DLT-registered template and sender ID; register the "
                           "message with your provider first.", objectName="muted", wordWrap=True))
        for label, w in (("Service", self.kind), ("Account SID", self.account), ("API key SID", self.user),
                         ("Send from", self.sender), ("Address", self.url), ("Method", self.method),
                         ("Headers", self.headers), ("Body", self.body), ("Sent when the reply has", self.success),
                         ("Token or key", self.key), ("Country code", self.code), ("At most", row)):
            form.addRow(label, w)
        self.problem = QLabel(objectName="error", wordWrap=True)
        form.addRow(self.problem)
        test = QPushButton("Send a test SMS…")
        test.clicked.connect(self.test)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.addButton(test, QDialogButtonBox.ActionRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.show_fields()

    def preset(self):
        name = self.kind.currentText()
        if name in GATEWAYS:
            g = GATEWAYS[name]
            self.url.setText(g.url)
            self.method.setCurrentText(g.method)
            self.headers.setPlainText(g.headers)
            self.body.setPlainText(g.body)
            self.success.setText(g.success)
        for spin, v in zip(self.limits, LIMITS["Twilio" if name == "Twilio" else "Other"]):
            spin.setValue(v)
        self.show_fields()

    def show_fields(self):
        twilio = self.kind.currentText() == "Twilio"
        for w in (self.account, self.user):
            self.form.setRowVisible(w, twilio)
        for w in (self.url, self.method, self.headers, self.body, self.success):
            self.form.setRowVisible(w, not twilio)

    def settings(self) -> SmsSettings:
        twilio = self.kind.currentText() == "Twilio"
        return check_sms_settings(SmsSettings(
            "twilio" if twilio else "http", self.account.text().strip() if twilio else "",
            self.user.text().strip() if twilio else "", self.sender.text().strip(), self.url.text().strip(),
            self.method.currentText(), self.headers.toPlainText(), self.body.toPlainText(),
            self.success.text()))

    def extra(self) -> dict:
        code = self.code.text().strip()
        if code and not (code.startswith("+") and code[1:].isdigit() and len(code) <= 4):
            raise ValueError("the country code is + and up to 3 digits, e.g. +977")
        return {"preset": self.kind.currentText(), "limits": [x.value() for x in self.limits], "code": code}

    def save(self) -> bool:
        try:
            s, extra = self.settings(), self.extra()
            if self.key.text():
                set_secret(secret_name("sms", s), self.key.text())
        except (ValueError, RuntimeError) as e:
            self.problem.setText(f"Not saved: {e}.")
            return False
        save("sms", s, extra)
        self.accept()
        return True

    def test(self):
        try:
            s, extra = self.settings(), self.extra()
        except ValueError as e:
            self.problem.setText(f"{e}.")
            return
        to, ok = QInputDialog.getText(self, "Send a test SMS", "Your phone number")
        if not ok or not to.strip():
            return
        try:
            send_sms(s, self.key.text() or get_secret(secret_name("sms", s)),
                     international(sending.check_phone(to), extra["code"]), "A test from OMR Checker.")
        except (ValueError, OSError) as e:
            self.problem.setText(f"The test didn't go: {e}")
            return
        self.problem.clear()
        QMessageBox.information(self, "Sent", "The gateway took the test SMS. It should arrive in a minute.")


class SendingSettings(QWidget):
    """The Settings row: whether email and SMS are set up, and the buttons to set them up."""

    def __init__(self):
        super().__init__()
        self.label = QLabel(objectName="muted")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.label)
        for text, dialog in (("Email…", EmailSetup), ("SMS…", SmsSetup)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, d=dialog: (d(self).exec(), self.refresh()))
            row.addWidget(b)
        row.addStretch()
        self.refresh()

    def refresh(self):
        email, sms = load("email")[0], load("sms")[0]
        on = [n for n, s in (("email", email), ("SMS", sms)) if s]
        self.label.setText(f"Results can go by {' and '.join(on)}" if on else "Off: results aren't sent")


# -- send ----------------------------------------------------------------------------------------------------

class SendDialog(QDialog):
    """Who gets what, a test to yourself, then each message in turn within the limits, each one logged."""

    def __init__(self, parent, store: Store, exam_id: int, exam: sending.Exam, to_check: int):
        super().__init__(parent)
        self.setWindowTitle(f"Send results: {exam.name}")
        self.resize(1000, 860)
        self.store, self.exam_id, self.exam, self.to_check = store, exam_id, exam, to_check
        self.directory = {same_roll(s.roll_number): s for s in store.directory()}
        saved = store.exam(exam_id).details.get("messages", {})
        self.queue: list[Message] = []
        self.future: Future | None = None
        self.pool = ThreadPoolExecutor(1)
        self.mailer = None
        self.timer = QTimer(self, interval=200)
        self.timer.timeout.connect(self.step)

        self.channel = QComboBox()
        for label, key in (("Email", "email"), ("SMS", "sms")):
            if load(key)[0]:
                self.channel.addItem(label, key)
        self.channel.addItem("WhatsApp (you press Send for each)", "whatsapp")  # needs no setting up
        self.code = QLineEdit(str(settings().value("sending/whatsapp_code", "") or load("sms")[1].get("code", "")),
                              placeholderText="e.g. +977 or +91", maxLength=5)
        self.code.setToolTip("Put in front of phone numbers saved without their country code")
        self.code.textChanged.connect(self.update)
        self.channel.activated.connect(lambda _: self.update())
        self.subject = QLineEdit(saved.get("subject", SUBJECT))
        self.body = QPlainTextEdit()
        self.texts = {"email": saved.get("email", EMAIL_BODY), "sms": saved.get("sms", SMS_BODY),
                      "whatsapp": saved.get("whatsapp", WHATSAPP_BODY)}
        self.pdf = QCheckBox("Attach the PDF scorecard", checked=saved.get("pdf", True))
        self.html = QCheckBox("Attach the report page (opens in any browser)", checked=saved.get("html", False))
        self.again = QCheckBox("Send again to students already sent this exam's result")
        for w in (self.subject, self.body):
            w.textChanged.connect(self.update)
        self.again.toggled.connect(lambda _: self.update())
        self.preview = QLabel(objectName="card", wordWrap=True, textInteractionFlags=Qt.TextSelectableByMouse)
        self.preview.setContentsMargins(12, 8, 12, 8)
        self.preview.setMaximumHeight(180)
        self.body.setFixedHeight(130)
        self.problem = QLabel(objectName="error", wordWrap=True)
        self.note = QLabel(objectName="muted", wordWrap=True)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Roll number", "Name", "To", "Status"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.log = QTableWidget(0, 6)
        self.log.setHorizontalHeaderLabels(["Time", "Roll number", "By", "To", "Result", "Why"])
        self.log.setEditTriggers(QTableWidget.NoEditTriggers)
        self.log.verticalHeader().hide()
        self.log.horizontalHeader().setStretchLastSection(True)
        tabs = QTabWidget()
        tabs.addTab(self.table, "Who gets what")
        tabs.addTab(self.log, "Send log")
        self.bar = QProgressBar()
        self.bar.hide()
        self.status = QLabel(objectName="muted", wordWrap=True)
        self.test_button = QPushButton("Send a test to me…")
        self.test_button.clicked.connect(self.test)
        self.send_button = QPushButton("Send…", objectName="primary")
        self.send_button.clicked.connect(self.start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(lambda: self.finish("Stopped. Send… goes on with the students not sent."))
        self.stop_button.hide()
        form = QFormLayout()
        form.addRow("Send by", self.channel)
        form.addRow("Country code", self.code)
        self.code_label = form.labelForField(self.code)
        form.addRow("Subject", self.subject)
        self.subject_label = form.labelForField(self.subject)
        form.addRow("Message", self.body)
        form.addRow("", QLabel("Fields: " + ", ".join(f"{{{k}}} {v}" for k, v in FIELDS.items()), objectName="muted",
                               wordWrap=True))
        self.attach_row = QWidget()
        attach = QHBoxLayout(self.attach_row)
        attach.setContentsMargins(0, 0, 0, 0)
        attach.addWidget(self.pdf)
        attach.addWidget(self.html)
        attach.addStretch()
        form.addRow("", self.attach_row)
        buttons = QHBoxLayout()
        buttons.addWidget(self.again)
        buttons.addStretch()
        for b in (self.test_button, self.stop_button, self.send_button):
            buttons.addWidget(b)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("The first student's message:", objectName="muted"))
        layout.addWidget(self.preview)
        layout.addWidget(self.problem)
        layout.addWidget(self.note)
        layout.addWidget(tabs, 1)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        self.current = self.channel.currentData()
        self.body.setPlainText(self.texts.get(self.current or "email", ""))
        self.update()

    def kind(self) -> str:
        return self.channel.currentData() or ""

    def update(self):
        kind = self.kind()
        if kind and kind != self.current:  # the text box holds each channel's own message
            self.texts[self.current or "email"] = self.body.toPlainText()
            self.current = kind
            self.body.blockSignals(True)
            self.body.setPlainText(self.texts[kind])
            self.body.blockSignals(False)
        email, whatsapp = kind == "email", kind == "whatsapp"
        for w in (self.subject, self.pdf, self.html):
            w.setEnabled(email)
        for w in (self.code, self.code_label):
            w.setVisible(whatsapp)
        for w in (self.subject, self.subject_label, self.attach_row):
            w.setVisible(not whatsapp)  # a chat has no subject, and a link can't carry a file
        self.send_button.setText("Open the next in WhatsApp" if whatsapp else "Send…")
        self.messages: list[Message] = []
        problem = ""
        if not kind:
            problem = "Email and SMS aren't set up. Set them up under Settings, Send results."
        elif self.to_check:
            problem = (f"{self.to_check} marks still wait on Review. Check them first: a result sent can't be "
                       "taken back.")
        try:
            self.messages = sending.messages(self.exam, kind or "email", self.subject.text(),
                                             self.body.toPlainText(), self.directory,
                                             not self.store.rolls_change)
        except ValueError as e:
            problem = f"{e}."
        if kind in ("sms", "whatsapp"):
            code = load("sms")[1].get("code", "") if kind == "sms" else self.code.text().strip()
            for m in self.messages:
                m.to = international(m.to, code)
        if whatsapp and not problem and any(m.to and not m.to.startswith("+") for m in self.messages):
            problem = "Some phone numbers have no country code. Type it in Country code, e.g. +977."
        self.problem.setText(problem)
        first = self.messages[0] if self.messages else None
        if first:
            head = f"To: {first.to or '(no address)'}\nSubject: {first.subject}\n\n" if email else (
                f"To: {first.to or '(no number)'}  ·  {sms_parts(first.body)} SMS\n\n")
            self.preview.setText(head + first.body)
        sent = self.store.sent_to(self.exam_id, kind) if kind else set()
        if whatsapp:
            self.preview.setText(f"To: {first.to or '(no number)'} on WhatsApp\n\n{first.body}" if first else "")
        ready, missing, shared = to_whom(self.messages)
        self.queue = [m for m in ready if self.again.isChecked() or m.roll not in sent]
        queued = {m.roll for m in self.queue}
        shared_rolls = {r for rolls in shared.values() for r in rolls}
        self.table.setRowCount(len(self.messages))
        for row, m in enumerate(self.messages):
            status = ("No address" if not m.to else ("Opened" if whatsapp else "Already sent") if m.roll not in queued
                      else "Shares an address" if m.roll in shared_rolls else "To open" if whatsapp else "Will send")
            for col, text in enumerate((m.roll, m.name, m.to, status)):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.note.setText((f"Each chat opens in WhatsApp with the message typed in; press Send there, then come back "
                           f"for the next. {len(self.queue)} to open, " if whatsapp else
                           f"{len(self.queue)} will be sent, ")
                          + f"{len(missing)} have no {'email' if email else 'phone'} (add it in the Student directory), "
                          f"{len(ready) - len(self.queue)} already {'opened' if whatsapp else 'sent'}."
                          + (f" {len(shared)} addresses are shared by more than one student; they get one message "
                             "each." if shared else ""))
        self.fill_log()
        idle = self.future is None and not self.timer.isActive()
        self.send_button.setEnabled(idle and not problem and bool(self.queue))
        self.test_button.setEnabled(idle and bool(kind) and not problem and bool(self.messages))

    def fill_log(self):
        rows = self.store.send_log(self.exam_id)
        self.log.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, v in enumerate(values):
                self.log.setItem(r, c, QTableWidgetItem(v.replace("T", " ") if c == 0 else v))
        self.log.resizeColumnsToContents()

    def remember(self):
        self.texts[self.kind() or "email"] = self.body.toPlainText()
        self.store.set_messages(self.exam_id, {"subject": self.subject.text(), "email": self.texts["email"],
                                               "sms": self.texts["sms"], "whatsapp": self.texts["whatsapp"],
                                               "pdf": self.pdf.isChecked(), "html": self.html.isChecked()})
        settings().setValue("sending/whatsapp_code", self.code.text().strip())

    def test(self):
        kind = self.kind()
        s, extra = load(kind)
        to, ok = QInputDialog.getText(self, "Send a test to me", "Your email" if kind == "email" else
                                      "Your phone number", text=s.sender if kind == "email" and s else "")
        if not ok or not to.strip():
            return
        m = self.messages[0]
        to = international(to.strip(), self.code.text().strip()) if kind == "whatsapp" else to.strip()
        test = Message(m.roll, m.name, to, f"TEST: {m.subject}", m.body, self.attach(m))
        try:
            self.deliver(kind, test, close=True)
        except Exception as e:  # each is a message for the person
            QMessageBox.warning(self, "The test didn't go", str(e))
            return
        QMessageBox.information(self, "Test sent", f"The first student's message is open in WhatsApp for {to}. Send it "
                                "there and check it." if kind == "whatsapp" else
                                f"The first student's message went to {to} only. Check it, then Send….")

    def attach(self, m: Message) -> list:
        if self.kind() != "email":
            return []
        g = next(g for g in self.exam.graded if g.page.result.roll_number == m.roll)
        return sending.attachments(self.exam, g, self.pdf.isChecked(), self.html.isChecked())

    def start(self):
        if self.kind() == "whatsapp":
            self.open_next()
            return
        n = len(self.queue)
        typed, ok = QInputDialog.getText(
            self, "Send results", f"Send {n} {'emails' if self.kind() == 'email' else 'SMS'} now? A result sent "
            f"can't be taken back.\n\nType {n} to send.")
        if not ok or typed.strip() != str(n):
            return
        self.remember()
        self.sent = self.failed = 0
        self.bar.setRange(0, n)
        self.bar.setValue(0)
        self.bar.show()
        self.stop_button.show()
        self.send_button.setEnabled(False)
        self.test_button.setEnabled(False)
        self.timer.start()

    def open_next(self):
        """Open the next student's chat in WhatsApp, logged as opened: whether it was sent, only WhatsApp knows."""
        self.remember()
        m = self.queue[0]
        try:
            self.deliver("whatsapp", m)
        except ValueError as e:
            self.store.log_send(self.exam_id, m.roll, "whatsapp", m.to, "failed", str(e)[:300])
            self.status.setText(f"Not opened: {e}")
        else:
            self.store.log_send(self.exam_id, m.roll, "whatsapp", m.to, "opened", "opened to send by hand")
            self.status.setText(f"{m.name}'s chat is open in WhatsApp. Press Send there, then Open the next.")
        self.update()

    def deliver(self, kind: str, m: Message, close: bool = False):
        """Send one message, on the sending thread or here for a test. Raises what the server or gateway raised."""
        if kind == "whatsapp":
            if not QDesktopServices.openUrl(QUrl(whatsapp_link(m.to, m.body))):
                raise ValueError("this PC has no browser or WhatsApp to open the chat in")
            return
        s, extra = load(kind)
        secret = get_secret(secret_name(kind, s))
        if kind == "sms":
            send_sms(s, secret, m.to, m.body)
            return
        if self.mailer is None or close:
            self.mailer = Mailer(s, secret)
        try:
            self.mailer.send(m)
        finally:
            if close:
                self.mailer.close()
                self.mailer = None

    def step(self):
        """Every 200 ms: note the message just sent, then send the next one when the limits allow."""
        kind = self.kind()
        if self.future is not None:
            if not self.future.done():
                return
            m, error = self.sending, self.future.exception()
            self.future = None
            refused = error is not None and (isinstance(error, ValueError) or "Recipient" in type(error).__name__)
            self.store.log_send(self.exam_id, m.roll, kind, m.to, "failed" if error else "sent",
                                str(error)[:300] if error else "")
            self.sent += error is None
            self.failed += error is not None
            self.bar.setValue(self.sent + self.failed)
            if error is not None and not refused:  # the server or gateway itself: stop rather than fail everyone
                self.finish(f"Stopped: {error}. {self.sent} sent. Fix the settings, then Send… goes on with the "
                            "rest.")
                return
        if not self.queue:
            self.finish(f"Done: {self.sent} sent" + (f", {self.failed} failed (see the Send log)" if self.failed
                                                     else "") + ".")
            return
        now = datetime.now()
        pause = wait(self.store.send_times(kind, now - timedelta(days=1)), tuple(load(kind)[1].get(
            "limits", LIMITS["Other"])), now)
        if pause > timedelta(minutes=10):
            self.finish(f"The day's limit is reached: {self.sent} sent, {len(self.queue)} left. Send… goes on with "
                        f"them after {(now + pause):%d %b %H:%M}.")
            return
        if pause:
            self.status.setText(f"{self.sent} sent; waiting {pause.seconds} s to keep within the limit…")
            return
        m = self.queue.pop(0)
        m.attachments = self.attach(m)
        self.sending = m
        self.status.setText(f"Sending {self.sent + self.failed + 1} of {self.bar.maximum()}: {m.name}…")
        self.future = self.pool.submit(self.deliver, kind, m)

    def finish(self, text: str):
        self.timer.stop()
        if self.future is not None:  # stopped mid-send: let that one finish and log it
            error = self.future.exception()
            self.store.log_send(self.exam_id, self.sending.roll, self.kind(), self.sending.to,
                                "failed" if error else "sent", str(error)[:300] if error else "")
            self.future = None
        if self.mailer is not None:
            self.pool.submit(self.mailer.close).result()
            self.mailer = None
        self.stop_button.hide()
        self.status.setText(text)
        self.update()

    def reject(self):
        if self.timer.isActive():
            self.finish("Stopped.")
        self.remember()
        self.pool.shutdown(wait=True)
        super().reject()
