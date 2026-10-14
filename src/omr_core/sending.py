"""Sending each student their result: by email through any SMTP server, or by SMS through Twilio or any HTTP
gateway. Nothing is sent from here on its own; the app shows who gets what, asks, and sends one at a time
within the provider's limits, logging each one so nobody gets the same message twice.

Passwords and API keys are passed in by the caller, which keeps them in the system's credential store; they are
never saved here, in the database or in a log.
"""

import base64
import json
import smtplib
import ssl
import string
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr

from .students import check_email, check_phone

FIELDS = {"name": "the student's name", "roll": "roll number", "exam": "exam name", "institute": "institute name",
          "score": "score", "out_of": "full marks", "percent": "percentage", "rank": "rank",
          "of": "students ranked", "percentile": "percentile", "sections": "score in each section",
          "date": "exam date"}
SUBJECT = "{exam} result: {name}"
EMAIL_BODY = """Dear {name},

Your result in {exam}: {score} out of {out_of} ({percent}%), rank {rank} of {of}.
{sections}

Your scorecard is attached.

{institute}"""
SMS_BODY = "{institute}: {name} ({roll}) scored {score}/{out_of} in {exam}, rank {rank} of {of}."

# Sending limits by provider: (per minute, per hour, per day). What providers publish changes, so these start
# the settings and can be typed over.
LIMITS = {"Gmail": (20, 100, 450), "Google Workspace": (30, 500, 1900), "Microsoft 365 / Outlook": (30, 1000, 9500),
          "Zoho Mail": (10, 100, 250), "Amazon SES, Brevo, Mailgun…": (60, 3000, 50000),
          "Twilio": (60, 3000, 50000), "Other": (10, 100, 300)}
SERVERS = {"Gmail": ("smtp.gmail.com", 587, "starttls"), "Google Workspace": ("smtp.gmail.com", 587, "starttls"),
           "Microsoft 365 / Outlook": ("smtp.office365.com", 587, "starttls"),
           "Zoho Mail": ("smtp.zoho.com", 465, "ssl")}


def fill(template: str, values: dict[str, object]) -> str:
    """The template with each {field} replaced. Raises ValueError naming a field that doesn't exist or a brace
    left open, so a typo shows before anything is sent."""
    try:
        names = [f for _, f, _, _ in string.Formatter().parse(template) if f is not None]
    except ValueError as e:
        raise ValueError(f"the message has a stray {{ or }}: {e}") from e
    unknown = [f for f in names if f not in values]
    if unknown:
        raise ValueError(f"the message uses {{{unknown[0]}}}, which isn't one of the fields: "
                         + ", ".join(f"{{{f}}}" for f in FIELDS))
    return template.format_map({k: v for k, v in values.items()})


@dataclass
class Message:
    roll: str
    name: str
    to: str  # an email or a phone number; "" when the student has none
    subject: str
    body: str
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)  # (file name, data, MIME type)


def to_whom(messages: list[Message]) -> tuple[list[Message], list[Message], dict[str, list[str]]]:
    """(messages with an address, those without, address to the roll numbers sharing it when more than one)."""
    ready = [m for m in messages if m.to]
    shared: dict[str, list[str]] = {}
    for m in ready:
        shared.setdefault(m.to.lower(), []).append(m.roll)
    return ready, [m for m in messages if not m.to], {a: r for a, r in shared.items() if len(r) > 1}


def address(student, channel: str) -> str:
    """The student's email or phone, checked; "" when missing or not right."""
    try:
        return check_email(student.email) if channel == "email" else check_phone(student.phone)
    except ValueError:
        return ""


# -- limits --------------------------------------------------------------------------------------------------

def wait(sent_at: list[datetime], limits: tuple[int, int, int], now: datetime) -> timedelta:
    """How long to wait before the next message so as not to pass (per minute, per hour, per day); zero to send
    now. `sent_at` are the times of messages already sent on this account (any exam)."""
    longest = timedelta(0)
    for most, span in zip(limits, (timedelta(minutes=1), timedelta(hours=1), timedelta(days=1))):
        recent = sorted(t for t in sent_at if t > now - span)
        if most and len(recent) >= most:
            longest = max(longest, recent[len(recent) - most] + span - now)
    return longest


# -- email ---------------------------------------------------------------------------------------------------

@dataclass
class EmailSettings:
    host: str = ""
    port: int = 587
    security: str = "starttls"  # "starttls", "ssl" or "none" (a test server only)
    user: str = ""
    sender: str = ""  # the From address
    sender_name: str = ""
    reply_to: str = ""
    cc: str = ""


def check_email_settings(s: EmailSettings) -> EmailSettings:
    """Raises ValueError for settings that can't work."""
    if not s.host.strip() or " " in s.host.strip():
        raise ValueError("type the mail server, e.g. smtp.gmail.com")
    if not 0 < s.port < 65536:
        raise ValueError("the port is a number from 1 to 65535, usually 587 or 465")
    if s.security not in ("starttls", "ssl", "none"):
        raise ValueError("pick the security")
    if not check_email(s.sender):
        raise ValueError("type the From address")
    for a in (s.reply_to, s.cc):
        check_email(a)
    return s


def email_message(s: EmailSettings, m: Message) -> EmailMessage:
    e = EmailMessage()
    e["From"] = formataddr((s.sender_name, s.sender)) if s.sender_name else s.sender
    e["To"] = m.to
    if s.cc:
        e["Cc"] = s.cc
    if s.reply_to:
        e["Reply-To"] = s.reply_to
    e["Subject"] = m.subject
    e.set_content(m.body)
    for name, data, mime in m.attachments:
        main, sub = mime.split("/")
        e.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return e


class Mailer:
    """One connection to the mail server for a run of emails. Raises OSError or smtplib.SMTPException when the
    server can't be reached or refuses the sign-in."""

    def __init__(self, s: EmailSettings, password: str, timeout: float = 30):
        self.s = check_email_settings(s)
        context = ssl.create_default_context()
        if s.security == "ssl":
            self.smtp = smtplib.SMTP_SSL(s.host, s.port, timeout=timeout, context=context)
        else:
            self.smtp = smtplib.SMTP(s.host, s.port, timeout=timeout)
            if s.security == "starttls":
                self.smtp.starttls(context=context)
        if s.user:
            self.smtp.login(s.user, password)

    def send(self, m: Message):
        """Raises smtplib.SMTPException when the server refuses this email."""
        self.smtp.send_message(email_message(self.s, m))

    def close(self):
        try:
            self.smtp.quit()
        except (OSError, smtplib.SMTPException):
            pass  # already gone; nothing is lost, every email was logged as it went


# -- SMS -----------------------------------------------------------------------------------------------------

@dataclass
class SmsSettings:
    kind: str = "twilio"  # "twilio" or "http"
    account: str = ""  # Twilio: the account SID (the user name is the same, or an API key SID)
    user: str = ""
    sender: str = ""  # Twilio: the From number; HTTP: the sender ID, as {sender}
    url: str = ""  # HTTP: with {to}, {message}, {sender}, {key} where the gateway wants them
    method: str = "POST"
    headers: str = ""  # HTTP: one "Name: value" a line
    body: str = ""  # HTTP: form or JSON, by the Content-Type header
    success: str = ""  # HTTP: text the reply must contain to count as sent; "" for any 2xx reply


# Gateways whose request is documented. The reply that means "sent" isn't, so it is any 2xx answer.
GATEWAYS = {"Sparrow SMS (Nepal)": SmsSettings(
    kind="http", url="https://api.sparrowsms.com/v2/sms/", method="POST",
    headers="Content-Type: application/x-www-form-urlencoded",
    body="token={key}&from={sender}&to={to}&text={message}")}


def check_sms_settings(s: SmsSettings) -> SmsSettings:
    if s.kind == "twilio":
        if not s.account.startswith("AC") or not s.account[2:].isalnum():
            raise ValueError("the Twilio account SID starts with AC")
        check_phone(s.sender)
        if not s.sender:
            raise ValueError("type the Twilio number to send from, with its country code")
    elif s.kind == "http":
        if urllib.parse.urlsplit(s.url).scheme not in ("http", "https"):
            raise ValueError("the gateway address starts with https://")
        if s.method not in ("GET", "POST"):
            raise ValueError("the method is GET or POST")
        for line in s.headers.splitlines():
            if line.strip() and ":" not in line:
                raise ValueError(f"a header is “Name: value”, not {line.strip()!r}")
        if "{message}" not in s.url + s.body or "{to}" not in s.url + s.body:
            raise ValueError("put {to} and {message} where the gateway wants the number and the text")
    else:
        raise ValueError("pick Twilio or another gateway")
    return s


def sms_request(s: SmsSettings, secret: str, to: str, text: str) -> urllib.request.Request:
    """The HTTP request that sends one SMS."""
    check_sms_settings(s)
    if s.kind == "twilio":
        auth = base64.b64encode(f"{s.user or s.account}:{secret}".encode()).decode()
        data = urllib.parse.urlencode({"To": to, "From": s.sender, "Body": text}).encode()
        return urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{s.account}/Messages.json",
                                      data=data, method="POST", headers={"Authorization": f"Basic {auth}"})
    headers = dict((k.strip(), v.strip()) for k, v in (line.split(":", 1) for line in s.headers.splitlines()
                                                        if line.strip()))
    values = {"to": to, "message": text, "sender": s.sender, "key": secret}
    quote = lambda v: urllib.parse.quote(v, safe="")  # noqa: E731
    url = s.url.format_map({k: quote(v) for k, v in values.items()})
    kind = next((v for k, v in headers.items() if k.lower() == "content-type"), "").lower()
    if "json" in kind:
        body = s.body.replace("{", "\x00").replace("}", "\x01")  # JSON's own braces aren't fields
        for k, v in values.items():
            body = body.replace(f"\x00{k}\x01", json.dumps(v)[1:-1])
        body = body.replace("\x00", "{").replace("\x01", "}")
    else:
        body = s.body.format_map({k: urllib.parse.quote_plus(v) for k, v in values.items()})
    data = body.encode() if s.method == "POST" and body else None
    return urllib.request.Request(url, data=data, method=s.method, headers=headers)


def send_sms(s: SmsSettings, secret: str, to: str, text: str, opener=urllib.request.urlopen, timeout: float = 30):
    """Send one SMS. Raises ValueError with the gateway's answer when it isn't sent, OSError when it can't be
    reached."""
    try:
        with opener(sms_request(s, secret, to, text), timeout=timeout) as reply:
            status, answer = reply.status, reply.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, answer = e.code, e.read(4000).decode("utf-8", "replace")
    if not 200 <= status < 300:
        raise ValueError(f"the gateway answered {status}: {answer[:300]}")
    if s.kind == "twilio":
        try:
            reply = json.loads(answer)
        except ValueError:
            reply = {}
        if not reply.get("sid") or reply.get("status") in ("failed", "undelivered"):
            raise ValueError(f"Twilio didn't take it: {answer[:300]}")
    elif s.success and s.success not in answer:
        raise ValueError(f"the gateway's answer didn't say it was sent: {answer[:300]}")


def sms_parts(text: str) -> int:
    """How many SMS a text takes: 160 characters in one (153 a part when longer), or 70 (67 a part) when it has
    characters outside plain GSM text, e.g. Devanagari."""
    gsm = all(ord(c) < 128 for c in text)
    one, part = (160, 153) if gsm else (70, 67)
    return 1 if len(text) <= one else -(-len(text) // part)
