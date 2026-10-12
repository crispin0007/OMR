import json

import pytest

from omr_core.reader import read_page
from omr_core.sheet import SheetSection, SheetSpec, layout, render
from omr_core.store import Store
from omr_core.template import parse
from sheets import fill, random_marks, scan


@pytest.mark.parametrize("spec", [
    SheetSpec("Class test", 50, options=4, roll_digits=5, sets=4),
    SheetSpec("Entrance", 200, options=4, roll_digits=6, sets=2),
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


@pytest.mark.parametrize("spec, why", [
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
