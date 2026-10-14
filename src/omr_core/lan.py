"""Several PCs on one exam (specs/005-several-pcs): the main PC answers on the office network, and a scanning
PC sends it each page it saved. Plain HTTP and JSON from the standard library, so nothing else is installed.

Every request but joining carries the token the main PC gave when the PC joined. A page is sent with an id of
its own, so a page sent twice (the answer lost on the way back) is saved once."""

import base64
import ipaddress
import json
import re
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np

from .phone_page import phone_page
from .reader import BLURRED, read_or_reason, sharpness
from .store import Store

PORT = 47615  # and PORT + 1 for the secure address phones' cameras need
MAX_BODY = 20_000_000  # a page's image is well under 1 MB; anything this big isn't a page
TIMEOUT = 15


def pc_name() -> str:
    return socket.gethostname()


def addresses() -> list[str]:
    """This PC's addresses on the network, the one used to reach others first, for other PCs to type in."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # nothing is sent; this only picks the network card in use
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    return [a for i, a in enumerate(found) if a not in found[:i] and not a.startswith("127.")] or ["127.0.0.1"]


class _Handler(BaseHTTPRequestHandler):
    server: "_Server"
    timeout = TIMEOUT

    def log_message(self, *args):
        pass  # nothing on a console nobody reads

    def _reply(self, status: int, body: object):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= MAX_BODY:
            raise ValueError("no body, or one too big to be a page")
        body = json.loads(self.rfile.read(n))
        if not isinstance(body, dict):
            raise ValueError("not a request")
        return body

    def _page(self, html: str, status: int = 200):
        data = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _photo(self, exam_id: int, by: tuple[str, str]):
        """A phone's photo of a sheet: read here, and saved only when it reads, else the phone is told to retake."""
        b = self._body()
        photo = cv2.imdecode(np.frombuffer(base64.b64decode(str(b.get("image", "")), validate=True), np.uint8),
                             cv2.IMREAD_COLOR)
        if photo is None:
            raise ValueError("that isn't a photo")
        store = self.server.store
        template = store.exam(exam_id).template
        result, problem = read_or_reason(photo, template)
        if result is None:
            why = problem.removeprefix("unreadable: ")
            return self._reply(200, {"ok": False, "why": f"{why}. Get all four corner marks in, flat and in "
                                                             "good light."})
        if sharpness(result.aligned, template) < BLURRED:  # the phone takes photos loosely; this is the check
            return self._reply(200, {"ok": False, "why": "the photo is blurred. Hold the phone still and let it "
                                                         "focus."})
        page_id, new = store.receive_photo(exam_id, b.get("uid"), result, by)
        if new and self.server.on_page:
            self.server.on_page(exam_id)
        return self._reply(200, {"ok": True, "new": new, "roll": result.roll_number, "to_check": len(result.flags)})

    def _handle(self, method: str):
        store = self.server.store
        try:
            url = urllib.parse.urlsplit(self.path)
            if method == "GET" and url.path == "/phone":
                q = urllib.parse.parse_qs(url.query)
                token, exam = q.get("t", [""])[0], q.get("exam", [""])[0]
                by = store.station(token)
                if by is None or not exam.isdigit():
                    return self._page("<p>This link has been taken out. Scan the QR code on the PC again.</p>", 401)
                e = store.exam(int(exam))
                return self._page(phone_page(e.id, e.name, token, by[0] or by[1], e.template))
            if method == "POST" and self.path == "/join":
                b = self._body()
                token = store.join(str(b.get("code", "")), str(b.get("name", "")), str(b.get("pin", "")),
                                   str(b.get("pc", "")))
                return self._reply(200, {"token": token, "main": pc_name()})
            by = store.station(self.headers.get("X-Token", ""))
            if by is None:
                return self._reply(401, {"error": "this PC isn't joined to the main PC, or was taken out"})
            if method == "GET" and self.path == "/exams":
                return self._reply(200, [{"id": i, "name": n, "created": c} for i, n, c, *_ in store.exams()])
            if m := re.fullmatch(r"/exams/(\d+)", self.path):
                return self._reply(200, store.exam_copy(int(m[1])))
            if method == "POST" and (m := re.fullmatch(r"/exams/(\d+)/photo", self.path)):
                return self._photo(int(m[1]), by)
            if method == "POST" and (m := re.fullmatch(r"/exams/(\d+)/pages", self.path)):
                b = self._body()
                image = base64.b64decode(b["image"], validate=True) if b.get("image") is not None else None
                page_id = store.receive_page(int(m[1]), b.get("uid"), b.get("page"), image, by)
                if self.server.on_page:
                    self.server.on_page(int(m[1]))
                return self._reply(200, {"page_id": page_id})
            return self._reply(404, {"error": "no such request"})
        except PermissionError as e:
            return self._reply(403, {"error": str(e)})
        except KeyError:
            return self._reply(404, {"error": "the main PC has no such open exam"})
        except (ValueError, TypeError) as e:  # json, base64 and bad pages are ValueErrors
            return self._reply(400, {"error": str(e) or "not a page"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


class _Server(HTTPServer):
    store: Store
    on_page = None

    def handle_error(self, request, client_address):
        pass  # a phone turning down the certificate, or a dropped connection: nothing to do or to print


class MainServer:
    """The main PC answering other PCs and phones, each address on its own thread with its own connection to the
    database at `db_path`. With `cert` (certificate and key files) phones also get a secure address, on the next
    port, for their camera. `on_page(exam_id)` is called on a server's thread after each page is saved."""

    def __init__(self, db_path: str | Path, port: int = PORT, on_page=None, cert: tuple[Path, Path] | None = None):
        self.db_path = db_path
        self.servers = [_Server(("", port), _Handler)]
        self.port = self.servers[0].server_address[1]
        self.secure_port = None
        if cert:
            secure = _Server(("", self.port + 1 if port else 0), _Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(*cert)
            secure.socket = context.wrap_socket(secure.socket, server_side=True, do_handshake_on_connect=False)
            self.servers.append(secure)
            self.secure_port = secure.server_address[1]
        self.threads = []
        for httpd in self.servers:
            httpd.on_page = on_page
            self.threads.append(threading.Thread(target=self._serve, args=(httpd,), daemon=True))
            self.threads[-1].start()

    def _serve(self, httpd: "_Server"):
        httpd.store = Store(self.db_path)
        try:
            httpd.serve_forever()
        finally:
            httpd.store.close()

    def stop(self):
        for httpd in self.servers:
            httpd.shutdown()
            httpd.server_close()
        for t in self.threads:
            t.join()

    def phone_links(self, exam_id: int, token: str) -> tuple[str, str]:
        """(the secure link with the live camera, or "" without a certificate; the plain link) for a phone."""
        host = addresses()[0]
        query = urllib.parse.urlencode({"exam": exam_id, "t": token})
        return (f"https://{host}:{self.secure_port}/phone?{query}" if self.secure_port else "",
                f"http://{host}:{self.port}/phone?{query}")


def make_cert(folder: str | Path) -> tuple[Path, Path]:
    """A certificate for this PC's addresses, made here and kept in `folder`, for phones' secure link: made again
    when the PC's address changed. Phones warn once that nobody vouches for it, which is expected on a local
    network."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    folder = Path(folder)
    cert, key = folder / "phone-cert.pem", folder / "phone-key.pem"
    wanted = {ipaddress.ip_address(a) for a in addresses()} | {ipaddress.ip_address("127.0.0.1")}
    if cert.exists() and key.exists():
        try:
            have = x509.load_pem_x509_certificate(cert.read_bytes()).extensions.get_extension_for_class(
                x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
            if wanted <= set(have):
                return cert, key
        except (ValueError, x509.ExtensionNotFound):
            pass  # made again below
    private = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"OMR Checker on {pc_name()}")])
    now = datetime.now(timezone.utc)
    made = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(a) for a in sorted(wanted, key=str)]
                                                       + [x509.DNSName("localhost")]), critical=False)
            .sign(private, hashes.SHA256()))
    folder.mkdir(parents=True, exist_ok=True)
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    cert.write_bytes(made.public_bytes(serialization.Encoding.PEM))
    return cert, key


class MainPC:
    """A scanning PC's way to the main PC at `address` ("host" or "host:port")."""

    def __init__(self, address: str, token: str = "", timeout: float = TIMEOUT):
        address = address.strip()
        self.address = address if ":" in address else f"{address}:{PORT}"
        self.token, self.timeout = token, timeout

    def _call(self, path: str, body: dict | None = None):
        req = urllib.request.Request(f"http://{self.address}{path}", method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "X-Token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                why = json.loads(e.read()).get("error", "")
            except (ValueError, AttributeError):
                why = ""
            if e.code in (401, 403):
                raise PermissionError(why or "the main PC refused this PC") from None
            raise ValueError(why or f"the main PC answered {e.code}") from None
        except ValueError as e:  # not JSON: something else answers on that address
            raise ConnectionError(f"{self.address} isn't the main PC: {e}") from None

    def join(self, code: str, name: str, pin: str) -> str:
        """Join the main PC as operator `name`: the main PC's name. Keeps the token for later calls."""
        r = self._call("/join", {"code": code, "name": name, "pin": pin, "pc": pc_name()})
        self.token = r["token"]
        return r["main"]

    def exams(self) -> list[dict]:
        return self._call("/exams")

    def exam(self, exam_id: int) -> dict:
        return self._call(f"/exams/{exam_id}")

    def send(self, exam_id: int, uid: str, page: dict, image: bytes | None) -> int:
        return self._call(f"/exams/{exam_id}/pages", {
            "uid": uid, "page": page, "image": base64.b64encode(image).decode() if image is not None else None})[
            "page_id"]


def send_waiting(store: Store, exam_id: int) -> tuple[int, list[str]]:
    """Send the main PC each page of a linked exam it hasn't saved, oldest first: (pages sent, why each page the
    main PC refused was refused). A refused page stays waiting here. Raises OSError when the main PC can't be
    reached and PermissionError when this PC was taken out; the pages not sent stay waiting."""
    address, remote_id, token, _ = store.link(exam_id)
    main = MainPC(address, token)
    pc = store.pc_id()
    sent, refused = 0, []
    for page_id in store.unsent(exam_id):
        page, image = store.page_to_send(page_id)
        try:
            main.send(remote_id, f"{pc}:{page_id}", page, image)
        except ValueError as e:
            refused.append(f"{page['file']}, page {page['page_no']}: {e}")
            continue
        store.mark_sent(page_id)
        sent += 1
    return sent, refused
