import json
from pathlib import Path

import pytest

from omr_core.reader import PageResult, read_page
from omr_core.store import Store
from omr_core.template import parse
from sheets import draw, random_marks, scan

TEMPLATE = json.loads((Path(__file__).parent.parent / "templates" / "test-100.json").read_text(encoding="utf-8"))


def template(with_grid: bool) -> dict:
    d = json.loads(json.dumps(TEMPLATE))
    d["barcode_mm"] = [140, 55, 55, 18]  # blank paper on the test sheet
    if not with_grid:
        d["grids"] = [g for g in d["grids"] if g["kind"] != "roll_number"]
    return d


@pytest.mark.parametrize("code, qr", [("2026-0042", False), ("S0042", True)])
def test_barcode_is_the_roll_number(code, qr):
    t = parse(template(with_grid=False))
    marks, answers, _, set_code = random_marks(t, 2)
    r = read_page(scan(draw(t, marks, barcode=code, qr=qr), angle=0.7, seed=2), t)
    assert (r.roll_number, r.set_code, r.answers, r.flags) == (code, set_code, answers, [])


def test_unreadable_barcode_goes_to_review():
    t = parse(template(with_grid=False))
    r = read_page(scan(draw(t, {})), t)
    assert r.roll_number == "?" and ("roll number", "barcode not readable") in r.flags


def test_barcode_and_bubbles_must_agree():
    t = parse(template(with_grid=True))
    marks, _, roll, _ = random_marks(t, 3)
    assert read_page(scan(draw(t, marks, barcode=roll), seed=3), t).flags == []
    r = read_page(scan(draw(t, marks, barcode="99999"), seed=3), t)
    assert r.roll_number == roll and ("roll number", "barcode says 99999") in r.flags


def test_barcode_area_must_be_on_the_page():
    d = template(with_grid=True)
    d["barcode_mm"] = [180, 55, 55, 18]
    with pytest.raises(ValueError):
        parse(d)


def test_correcting_a_barcode_roll_number(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", json.dumps(template(with_grid=False)))
    page = s.add_page(exam, "b", "a.png", 1, PageResult("?", "A", {q: "" for q in range(1, 101)},
                                                        [("roll number", "barcode not readable")]))
    with pytest.raises(ValueError):
        s.correct(page.id, "roll number", "  ", "me")
    fixed = s.correct(page.id, "roll number", "s-0042", "me")
    assert fixed.result.roll_number == "s-0042" and fixed.result.flags == []
