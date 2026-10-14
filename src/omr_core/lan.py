"""Several PCs on one exam (specs/005-several-pcs): the main PC answers on the office network, and a scanning
PC sends it each page it saved. Plain HTTP and JSON from the standard library, so nothing else is installed.

Every request but joining carries the token the main PC gave when the PC joined. A page is sent with an id of
its own, so a page sent twice (the answer lost on the way back) is saved once."""

import base64
import json
import re
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .store import Store

PORT = 47615
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

    def _handle(self, method: str):
        store = self.server.store
        try:
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


class MainServer:
    """The main PC answering other PCs, on its own thread with its own connection to the database at `db_path`.
    `on_page(exam_id)` is called on that thread after each page is saved."""

    def __init__(self, db_path: str | Path, port: int = PORT, on_page=None):
        self.httpd = _Server(("", port), _Handler)
        self.httpd.on_page = on_page
        self.port = self.httpd.server_address[1]
        self.db_path = db_path
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        self.httpd.store = Store(self.db_path)
        try:
            self.httpd.serve_forever()
        finally:
            self.httpd.store.close()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()


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
