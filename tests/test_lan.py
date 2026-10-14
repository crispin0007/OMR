import json
from pathlib import Path

import numpy as np
import pytest

from omr_core.lan import MainPC, MainServer, pc_name, send_waiting
from omr_core.reader import PageResult
from omr_core.store import Store
from omr_core.students import Student

TEMPLATE = (Path(__file__).parent.parent / "templates" / "test-100.json").read_text(encoding="utf-8")


def test_operators_log_in_with_their_pin_and_the_first_is_an_admin(tmp_path):
    s = Store(tmp_path / "omr.db")
    with pytest.raises(ValueError, match="first operator must be an admin"):
        s.add_operator("Ravi", "1234", "operator")
    with pytest.raises(ValueError, match="at least 4"):
        s.add_operator("Asha", "12", "admin")
    s.add_operator("Asha", "9876", "admin")
    s.add_operator("Ravi", "1234", "operator")
    assert s.operators() == [("Asha", "admin"), ("Ravi", "operator")]
    assert (s.login("Ravi", "1234"), s.login("Ravi", "9876"), s.login("Nobody", "1234")) == ("operator", None, None)
    assert b"1234" not in (tmp_path / "omr.db").read_bytes()  # only a hash of the PIN is kept
    with pytest.raises(ValueError, match="keep one admin"):
        s.remove_operator("Asha")
    s.add_operator("Ravi", "5555", "admin")  # a new PIN and role
    assert s.login("Ravi", "5555") == "admin"
    s.remove_operator("Asha")
    assert s.operators() == [("Ravi", "admin")]


def page(roll: str) -> PageResult:
    return PageResult(roll, "A", {1: "A", 2: "B"}, [("Q2", "two marks")], aligned=np.full((40, 30), 200, np.uint8))


def test_a_scanning_pc_scans_into_the_main_pcs_exam_and_nothing_is_lost_or_doubled(tmp_path):
    main = Store(tmp_path / "main" / "omr.db")
    exam = main.create_exam("Mock 7", TEMPLATE)
    main.save_scheme(exam, "AB", 4, -1, 0)
    main.set_students(exam, [Student("101", "Asha Rai", phone="+919800000000")])
    main.add_operator("Asha", "9876", "admin")
    main.add_operator("Ravi", "1234", "operator")
    seen = []
    server = MainServer(tmp_path / "main" / "omr.db", port=0, on_page=seen.append)
    try:
        there = MainPC(f"127.0.0.1:{server.port}")
        with pytest.raises(PermissionError, match="join code is wrong"):
            there.join("WRONG", "Ravi", "1234")
        with pytest.raises(PermissionError, match="name or PIN"):
            there.join(main.join_code.lower(), "Ravi", "0000")
        name = there.join(main.join_code.lower(), "Ravi", "1234")
        assert [e["name"] for e in there.exams()] == ["Mock 7"]

        pc = Store(tmp_path / "pc" / "omr.db")
        local = pc.copy_exam(there.exam(exam), there.address, exam, there.token, name)
        e = pc.exam(local)
        assert (e.name, e.answer_key, e.correct, e.wrong) == ("Mock 7", "AB", 4, -1)
        assert pc.students(local)["101"].name == "Asha Rai"
        first = pc.add_page(local, "scanner", "scanner", 1, page("101"))
        pc.add_page(local, "scanner", "scanner", 2, None, "unreadable: no corner marks",
                    np.zeros((20, 20), np.uint8))
        assert send_waiting(pc, local) == (2, [])
        assert pc.unsent(local) == [] and seen == [exam, exam]
        got = main.pages(exam)
        assert [p.result and p.result.roll_number for p in got] == ["101", None]
        assert got[0].result.answers == {1: "A", 2: "B"} and got[0].result.flags == [("Q2", "two marks")]
        assert got[0].batch == f"scanner  ·  {pc_name()}, Ravi"
        assert main.image(got[0].id).shape == (40, 30) and got[1].problem == "unreadable: no corner marks"

        # The answer was lost on the way back: sending the page again saves nothing new.
        pc.db.execute("DELETE FROM sent WHERE page_id = ?", (first.id,))
        pc.db.commit()
        assert send_waiting(pc, local) == (1, []) and len(main.pages(exam)) == 2

        # Joining the same exam again brings the copy up to date and keeps what was scanned here.
        main.save_scheme(exam, "BB", 4, -1, 0)
        assert pc.copy_exam(there.exam(exam), there.address, exam, there.token, name) == local
        assert pc.exam(local).answer_key == "BB" and len(pc.pages(local)) == 2

        # Pages that aren't pages are refused and stay waiting; the rest still go.
        bad = pc.add_page(local, "scanner", "scanner", 3, page("102"))
        pc.db.execute("UPDATE page SET answers = '[1]' WHERE id = ?", (bad.id,))
        pc.add_page(local, "scanner", "scanner", 4, page("103"))
        pc.db.commit()
        sent, refused = send_waiting(pc, local)
        assert sent == 1 and refused == ["scanner, page 3: not a page: its answers"] and pc.unsent(local) == [bad.id]

        # Taken out on the main PC: it can't send any more, and the page keeps waiting.
        main.remove_station(there.token)
        with pytest.raises(PermissionError, match="isn't joined"):
            send_waiting(pc, local)
        assert pc.unsent(local) == [bad.id]
    finally:
        server.stop()
    with pytest.raises(OSError):  # the main PC is off
        send_waiting(pc, local)


def test_the_main_pc_refuses_what_isnt_a_page(tmp_path):
    main = Store(tmp_path / "omr.db")
    exam = main.create_exam("Mock", TEMPLATE)
    token = main.join(main.join_code, "", "", "PC-2")  # no operators: nobody logs in
    by = main.station(token)
    good = {"batch": "b", "file": "f", "page_no": 1, "read_at": "2026-10-14T10:00:00", "roll_number": "12",
            "set_code": "A", "answers": json.dumps({"1": "A"}), "flags": "[]", "problem": "", "serial": "",
            "name_read": "[]"}
    for bad, image, why in (({**good, "page_no": "1"}, None, "not a page"),
                            ({**good, "answers": "{\"x\": 1}"}, None, "its answers"),
                            ({**good, "flags": "[[1]]"}, None, "its flags"),
                            ({**good, "roll_number": None}, None, "not a page"),
                            (good, b"<script>", "its image")):
        with pytest.raises(ValueError, match=why):
            main.receive_page(exam, "pc:1", bad, image, by)
    with pytest.raises(KeyError):
        main.receive_page(exam + 1, "pc:1", good, None, by)
    assert main.receive_page(exam, "pc:1", good, None, by) == main.receive_page(exam, "pc:1", good, None, by)
    assert main.pages(exam)[0].batch == "b  ·  PC-2"
    main.delete_exam(exam)
    with pytest.raises(KeyError):
        main.receive_page(exam, "pc:2", good, None, by)


def test_a_phone_photographs_sheets_into_the_exam_and_is_told_to_retake_a_bad_photo(tmp_path):
    import base64
    import ssl
    import urllib.request

    import cv2

    from omr_core.lan import make_cert
    from omr_core.template import load
    from sheets import camera, draw, photo, random_marks

    main = Store(tmp_path / "omr.db")
    exam = main.create_exam("Mock 7", TEMPLATE)
    token = main.add_station("Ravi", "Phone")
    cert = make_cert(tmp_path / "cert")
    assert make_cert(tmp_path / "cert") == cert and b"PRIVATE KEY" in cert[1].read_bytes()  # made once, kept
    seen = []
    server = MainServer(tmp_path / "omr.db", port=0, on_page=seen.append, cert=cert)
    try:
        secure, plain = server.phone_links(exam, token)
        assert secure.startswith("https://") and plain.startswith("http://") and f"t={token}" in secure
        insecure = ssl.create_default_context()
        insecure.check_hostname, insecure.verify_mode = False, ssl.CERT_NONE  # as the phone, once told to trust it
        base = f"https://127.0.0.1:{server.secure_port}"
        page = urllib.request.urlopen(f"{base}/phone?exam={exam}&t={token}", context=insecure).read().decode()
        assert "Mock 7" in page and "getUserMedia" in page and token in page and "http://" not in page
        with pytest.raises(urllib.error.HTTPError, match="401"):
            urllib.request.urlopen(f"{base}/phone?exam={exam}&t=wrong", context=insecure)
        assert "Mock 7" in urllib.request.urlopen(f"http://127.0.0.1:{server.port}/phone?exam={exam}&t={token}"
                                                  ).read().decode()  # the plain link, for the upload button

        def send(image, uid):
            jpeg = base64.b64encode(cv2.imencode(".jpg", image)[1].tobytes()).decode()
            req = urllib.request.Request(f"{base}/exams/{exam}/photo", method="POST", headers={"X-Token": token},
                                         data=json.dumps({"uid": uid, "image": jpeg}).encode())
            return json.loads(urllib.request.urlopen(req, context=insecure).read())

        t = load(Path(__file__).parent.parent / "templates" / "test-100.json")
        marks, answers, roll, _ = random_marks(t, 5)
        sheet = photo(draw(t, marks), width=1800, quality=80)
        assert send(sheet, "phone:1") == {"ok": True, "new": True, "roll": roll, "to_check": 0}
        assert send(sheet, "phone:1")["new"] is False  # sent again after a dropped answer
        assert send(sheet, "phone:2")["new"] is False  # the same sheet taken twice in a row
        retake = send(np.full((900, 700, 3), 230, np.uint8), "phone:3")
        assert retake["ok"] is False and "corner marks" in retake["why"]
        blurred = send(camera(draw(t, random_marks(t, 6)[0]), t, blur=7), "phone:4")
        assert blurred["ok"] is False and "blurred" in blurred["why"]
        assert send(camera(draw(t, random_marks(t, 6)[0]), t, light=0.4, keystone=0.06), "phone:5")["ok"]
        got, _ = main.pages(exam)
        assert got.result.roll_number == roll and got.result.answers == answers and seen == [exam, exam]
        assert got.batch.startswith("Phone, Ravi")
    finally:
        server.stop()
