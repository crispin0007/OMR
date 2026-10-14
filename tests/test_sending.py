"""Sending results: checked against a fake mail server and a fake SMS gateway on this PC; nothing real is sent."""

import json
import smtplib
import socket
import threading
import urllib.parse
from datetime import datetime, timedelta
from email import message_from_bytes

import pytest

from omr_core.sending import (GATEWAYS, EmailSettings, Mailer, Message, SmsSettings, fill, send_sms, sms_parts,
                              sms_request, to_whom, wait)


def test_fill_names_a_wrong_field():
    assert fill("{name}: {score}/{out_of}", {"name": "Asha", "score": 72, "out_of": 100}) == "Asha: 72/100"
    with pytest.raises(ValueError, match="uses {nmae}"):
        fill("Dear {nmae}", {"name": "Asha"})
    with pytest.raises(ValueError, match="stray"):
        fill("Dear {name", {"name": "Asha"})


def test_who_has_an_address_and_who_shares_one():
    ms = [Message("1", "A", "p@example.org", "", ""), Message("2", "B", "P@example.org", "", ""),
          Message("3", "C", "", "", "")]
    ready, missing, shared = to_whom(ms)
    assert [m.roll for m in ready] == ["1", "2"] and [m.roll for m in missing] == ["3"]
    assert shared == {"p@example.org": ["1", "2"]}


def test_wait_keeps_within_each_limit():
    now = datetime(2026, 10, 14, 12)
    assert wait([], (2, 10, 20), now) == timedelta(0)
    two = [now - timedelta(seconds=50), now - timedelta(seconds=10)]
    assert wait(two, (2, 10, 20), now) == timedelta(seconds=10)
    day = [now - timedelta(hours=h) for h in range(1, 21)]
    assert wait(day, (2, 100, 20), now) == timedelta(hours=4)  # the oldest of today's 20 leaves at 16:00


def test_sms_parts():
    assert sms_parts("a" * 160) == 1 and sms_parts("a" * 161) == 2 and sms_parts("नमस्ते") == 1
    assert sms_parts("न" * 71) == 2


class Opener:
    def __init__(self, status, answer):
        self.status, self.answer, self.requests = status, answer, []

    def __call__(self, request, timeout):
        self.requests.append(request)
        opener = self

        class Reply:
            status = opener.status

            def read(self, n):
                return opener.answer.encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass
        return Reply()


def test_twilio_gets_the_documented_request_and_a_refusal_is_reported():
    s = SmsSettings(kind="twilio", account="AC123", sender="+15005550006")
    ok = Opener(201, json.dumps({"sid": "SM1", "status": "queued"}))
    send_sms(s, "token", "+9779800000001", "Asha 72/100", opener=ok)
    r = ok.requests[0]
    assert r.full_url == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json" and r.method == "POST"
    assert urllib.parse.parse_qs(r.data.decode()) == {"To": ["+9779800000001"], "From": ["+15005550006"],
                                                      "Body": ["Asha 72/100"]}
    assert r.headers["Authorization"] == "Basic QUMxMjM6dG9rZW4="  # AC123:token
    with pytest.raises(ValueError, match="answered 400"):
        send_sms(s, "token", "+1", "x", opener=Opener(400, '{"message": "bad number"}'))
    with pytest.raises(ValueError, match="starts with AC"):
        send_sms(SmsSettings(kind="twilio", account="x"), "t", "+1", "x", opener=ok)


def test_a_custom_gateway_fills_its_form_or_json_and_checks_the_answer():
    s = GATEWAYS["Sparrow SMS (Nepal)"]
    s = SmsSettings(**{**s.__dict__, "sender": "Academy"})
    r = sms_request(s, "k&1", "9800000001", "Asha: 72/100 & rank 3")
    assert urllib.parse.parse_qs(r.data.decode()) == {"token": ["k&1"], "from": ["Academy"], "to": ["9800000001"],
                                                      "text": ["Asha: 72/100 & rank 3"]}
    j = SmsSettings(kind="http", url="https://sms.example.org/send?key={key}", headers="Content-Type: application/json",
                    body='{"to": "{to}", "text": "{message}"}', success='"ok"')
    r = sms_request(j, "a b", "+9779800000001", 'He said "hi"')
    assert r.full_url == "https://sms.example.org/send?key=a%20b"
    assert json.loads(r.data) == {"to": "+9779800000001", "text": 'He said "hi"'}
    send_sms(j, "k", "+1", "x", opener=Opener(200, '{"status": "ok"}'))
    with pytest.raises(ValueError, match="didn't say it was sent"):
        send_sms(j, "k", "+1", "x", opener=Opener(200, '{"status": "queued later"}'))
    with pytest.raises(ValueError, match="put {to} and {message}"):
        sms_request(SmsSettings(kind="http", url="https://x.example.org"), "", "1", "x")


class FakeSmtp:
    """Just enough of an SMTP server to take emails: what a real one is sent, kept in `received`."""

    def __init__(self, refuse: str = ""):
        self.received, self.refuse = [], refuse
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        conn, _ = self.sock.accept()
        f = conn.makefile("rwb")
        say = lambda line: (f.write(line.encode() + b"\r\n"), f.flush())  # noqa: E731
        say("220 fake")
        rcpt = []
        while line := f.readline():
            cmd = line.decode().strip()
            verb = cmd.split(" ")[0].upper()
            if verb == "EHLO":
                say("250-fake\r\n250 AUTH PLAIN")
            elif verb == "AUTH":
                say("235 ok")
            elif verb == "MAIL":
                rcpt = []
                say("250 ok")
            elif verb == "RCPT":
                rcpt.append(cmd)
                say("550 no such user" if self.refuse and self.refuse in cmd else "250 ok")
            elif verb == "DATA":
                say("354 go")
                data = b""
                while (chunk := f.readline()) != b".\r\n":
                    data += chunk
                self.received.append((rcpt, message_from_bytes(data)))
                say("250 queued")
            elif verb == "QUIT":
                say("221 bye")
                break
            else:
                say("250 ok")
        conn.close()


def test_emails_go_through_any_smtp_server_with_the_scorecard_attached():
    server = FakeSmtp(refuse="nobody@")
    s = EmailSettings(host="127.0.0.1", port=server.port, security="none", user="me", sender="results@example.org",
                      sender_name="First Academy", reply_to="office@example.org")
    mailer = Mailer(s, "app password")
    mailer.send(Message("12", "Asha", "asha@example.org", "Mock 1 result: Asha", "Dear Asha,\n72/100",
                        [("12.pdf", b"%PDF-1.4 fake", "application/pdf")]))
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        mailer.send(Message("13", "B", "nobody@example.org", "s", "b"))
    mailer.close()
    (rcpt, email), = server.received
    assert email["From"] == "First Academy <results@example.org>" and email["Reply-To"] == "office@example.org"
    assert email["Subject"] == "Mock 1 result: Asha" and "asha@example.org" in rcpt[0]
    parts = [p for p in email.walk() if p.get_filename()]
    assert [(p.get_filename(), p.get_payload(decode=True)) for p in parts] == [("12.pdf", b"%PDF-1.4 fake")]
    with pytest.raises(ValueError, match="type the mail server"):
        Mailer(EmailSettings(sender="a@example.org"), "")
