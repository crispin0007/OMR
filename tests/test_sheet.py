import json

import cv2
import numpy as np
import pytest

from omr_core.reader import read_page
from omr_core.sheet import SheetSection, SheetSpec, layout, logo_jpeg, render, write_pdf
from omr_core.store import Store
from omr_core.template import parse
from sheets import fill, random_marks, scan


@pytest.mark.parametrize("spec", [
    SheetSpec("Class test", 50, options=4, roll_digits=5, sets=4),
    SheetSpec("Entrance", 200, options=4, roll_digits=6, sets=2),
    SheetSpec("Long", 250, options=4, roll_digits=9, sets=8, colour="#1565c0"),
    SheetSpec("Quiz", 20, options=5, roll_digits=0, sets=0),
    SheetSpec("Mock", 90, options=4, roll_digits=3, sets=4,
              sections=[SheetSection("Physics", 30, 4, -1), SheetSection("Chemistry", 30, 4, -1),
                        SheetSection("Maths", 30, 4, -1)]),
])
def test_printed_sheet_reads_back_exactly(spec):
    d = layout(spec)
    t = parse(d)
    assert sum(g.rows for g in t.grids if g.kind == "questions") == spec.questions
    marks, answers, roll, set_code = random_marks(t, spec.questions)
    r = read_page(scan(fill(render(d), t, marks), angle=0.6, seed=1), t)
    assert (r.roll_number, r.set_code, r.answers, r.flags) == (roll, set_code, answers, [])


def test_printed_blank_sheet_reads_blank_and_upside_down_is_found():
    d = layout(SheetSpec("Blank", 100))
    t = parse(d)
    page = render(d)
    r = read_page(scan(page, upside_down=True), t)
    assert not any(r.answers.values()) and r.roll_number == "?????"


def test_sections_start_new_columns_and_reach_the_exam(tmp_path):
    d = layout(SheetSpec("Mock", 12, sections=[SheetSection("Physics", 5, 4, -1), SheetSection("Maths", 7, 3, -1)]))
    firsts = [g["first"] for g in d["grids"] if g["kind"] == "questions"]
    assert firsts == [1, 6]
    s = Store(tmp_path / "omr.db")
    exam = s.exam(s.create_exam("Mock", json.dumps(d)))
    assert [(x.name, x.first, x.last, x.correct, x.wrong) for x in exam.sections] == [
        ("Physics", 1, 5, 4, -1), ("Maths", 6, 12, 3, -1)]


@pytest.mark.parametrize("colour", ["#e4007c", "#ef6c00", "#2e7d32", "#1a237e", "#000000"])
@pytest.mark.parametrize("grey", [False, True])
def test_any_colour_reads_back_from_colour_and_grey_scans(colour, grey):
    d = layout(SheetSpec("Colour", 100, colour=colour))
    t = parse(d)
    marks, answers, roll, set_code = random_marks(t, 5)
    page = scan(fill(render(d), t, marks), angle=-0.4, seed=2)
    r = read_page(cv2.cvtColor(page, cv2.COLOR_BGR2GRAY) if grey else page, t)
    assert (r.roll_number, r.set_code, r.answers, r.flags) == (roll, set_code, answers, [])
    # Only the roll number and set filled: the bubbles' printed letters must not look like faint marks.
    ids = {k: v for k, v in marks.items() if t.grids[k[0]].kind != "questions"}
    page = scan(fill(render(d), t, ids), seed=3)
    r = read_page(cv2.cvtColor(page, cv2.COLOR_BGR2GRAY) if grey else page, t)
    assert not any(r.answers.values()) and r.flags == []


def test_heading_logo_and_instructions_are_printed(tmp_path):
    logo = np.full((40, 120, 3), 255, np.uint8)
    cv2.rectangle(logo, (10, 10), (110, 30), (0, 128, 0), -1)
    spec = SheetSpec("Branded", 40, heading="Unit Test Academy", instructions=["Bring your own pen.", "", "Be quiet."],
                     logo=logo_jpeg(cv2.imencode(".png", logo)[1].tobytes()))
    d = layout(spec)
    assert d["print"]["heading"] == "Unit Test Academy" and d["print"]["instructions"] == ["Bring your own pen.", "Be quiet."]
    write_pdf(json.loads(json.dumps(d)), tmp_path / "s.pdf")  # survives saving as JSON
    page = render(d, 100)
    top_left = page[:round(25 / 25.4 * 100), :round(70 / 25.4 * 100)]
    assert ((top_left[:, :, 1] > 100) & (top_left[:, :, 2] < 60)).any()  # the green logo


@pytest.mark.parametrize("change, why", [
    ({"colour": "pink"}, "colour"),
    ({"logo_jpeg": "not base64!"}, "logo"),
    ({"logo_jpeg": "aGVsbG8="}, "logo"),
    ({"instructions": "one line"}, "text"),
])
def test_bad_print_choices_in_a_template_are_refused(change, why, tmp_path):
    d = layout(SheetSpec("X", 10))
    d["print"].update(change)
    with pytest.raises(ValueError, match=why):
        write_pdf(d, tmp_path / "x.pdf")


def test_logo_must_be_an_image():
    with pytest.raises(ValueError, match="image"):
        logo_jpeg(b"not an image")


@pytest.mark.parametrize("spec, why", [
    (SheetSpec("X", 10, roll_digits=10), "0 to 9 digits"),
    (SheetSpec("X", 10, instructions=["A long instruction that goes on and on. " * 4] * 4), "shorten"),
    (SheetSpec("Big", 400), "don't fit"),
    (SheetSpec("", 10), "name"),
    (SheetSpec("X", 10, options=9), "2 to 8"),
    (SheetSpec("X", 10, sets=1), "sets"),
    (SheetSpec("X", 10, sections=[SheetSection("A", 4)]), "add up"),
    (SheetSpec("X", 10, sections=[SheetSection("A", 5), SheetSection("A", 5)]), "own name"),
])
def test_bad_choices_say_why(spec, why):
    with pytest.raises(ValueError, match=why):
        layout(spec)


def test_bad_sections_in_a_template_are_refused(tmp_path):
    d = layout(SheetSpec("Mock", 10, sections=[SheetSection("A", 10, 4, -1)]))
    d["sections"][0]["correct"] = "four"
    with pytest.raises(ValueError):
        Store(tmp_path / "omr.db").create_exam("Mock", json.dumps(d))
