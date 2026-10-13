import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from omr_core.reader import UnreadablePage, read_page
from omr_core.sheet import PAPERS, SheetSection, SheetSpec, layout, logo_jpeg, render, write_pdf
from omr_core.store import Store
from omr_core.template import load, parse
from sheets import draw, fill, photo, random_marks, reprint, scan


@pytest.mark.parametrize("spec", [
    SheetSpec("Class test", 50, options=4, roll_digits=5, sets=4),
    SheetSpec("Entrance", 200, options=4, roll_digits=6, sets=2),
    SheetSpec("Long", 250, options=4, roll_digits=9, sets=8, colour="#1565c0"),
    SheetSpec("Quiz", 20, options=5, roll_digits=0, sets=0),
    SheetSpec("Mock", 90, options=4, roll_digits=3, sets=4,
              sections=[SheetSection("Physics", 30, 4, -1), SheetSection("Chemistry", 30, 4, -1),
                        SheetSection("Maths", 30, 4, -1)]),
    SheetSpec("True or false", 40, options=2, roll_digits=4, sets=0, true_false=True),
    SheetSpec("Multi", 30, options=4, roll_digits=4, sets=0,
              sections=[SheetSection("One answer", 15), SheetSection("Several", 15, partial=True)]),
])
def test_printed_sheet_reads_back_exactly(spec):
    d = layout(spec)
    t = parse(d)
    assert sum(g.rows for g in t.grids if g.kind == "questions") == spec.questions
    marks, answers, roll, set_code = random_marks(t, spec.questions)
    r = read_page(scan(fill(render(d), t, marks), angle=0.6, seed=1), t)
    assert (r.roll_number, r.set_code, r.answers, r.flags) == (roll, set_code, answers, [])


CEE = [SheetSection("Zoology", 40), SheetSection("Botany", 40), SheetSection("Chemistry", 50),
       SheetSection("Physics", 50), SheetSection("MAT", 20)]


@pytest.mark.parametrize("options", [4, 5])
def test_more_sections_than_columns_follow_one_another_down_the_columns(options):
    d = layout(SheetSpec("CEE", 200, options=options, roll_digits=5, sets=0, sections=CEE))
    t = parse(d)
    questions = [g for g in t.grids if g.kind == "questions"]
    assert sum(g.rows for g in questions) == 200 and len({round(g.origin[0]) for g in questions}) == 5
    starts = {g.first for g in questions}
    assert {1, 41, 81, 131, 181} <= starts  # every section starts its own grid, under its heading
    marks, answers, roll, set_code = random_marks(t, 7)
    r = read_page(scan(fill(render(d), t, marks), angle=0.5, seed=3), t)
    assert (r.roll_number, r.answers, r.flags) == (roll, answers, [])


@pytest.mark.parametrize("seed", [1, 2])
def test_a_tilted_dim_compressed_phone_photo_reads_back(seed):
    d = layout(SheetSpec("Phone", 200, roll_digits=5, sets=4))
    t = parse(d)
    marks, answers, roll, set_code = random_marks(t, seed)
    r = read_page(photo(fill(render(d), t, marks), seed=seed), t)
    wrong = [q for q in answers if r.answers[q] != answers[q] and f"Q{q}" not in {w for w, _ in r.flags}]
    assert (r.roll_number, r.set_code, wrong) == (roll, set_code, [])


def test_another_layout_is_not_read_with_this_sheet():
    """A sheet without the orientation bar, such as one a school prints itself, isn't read as this exam's."""
    other = load(Path(__file__).parent.parent / "templates" / "test-100.json")
    page = photo(draw(other, {}), dim=0.4)
    with pytest.raises(UnreadablePage, match="orientation mark"):
        read_page(page, parse(layout(SheetSpec("Ours", 100))))


@pytest.mark.parametrize("paper,scale,stretch,dpi", [
    ("A4", 0.7, 1, 200), ("A4", 0.85, 1, 150), ("Letter", 0.94, 1, 200), ("Legal", 1.0, 1, 200),
    ("A3", 1.0, 1, 200), ("A3", 1.414, 1, 150), ("A5", 0.707, 1, 200), ("A4", 0.95, 0.97, 200),
])
def test_the_sheet_reads_the_same_at_any_print_size_and_paper(paper, scale, stretch, dpi):
    d = layout(SheetSpec("Paper", 200, roll_digits=5, sets=4))
    t = parse(d)
    marks, answers, roll, set_code = random_marks(t, 4)
    page = scan(reprint(fill(render(d), t, marks), PAPERS[paper], scale, stretch, dpi), angle=0.5, seed=2)
    r = read_page(page, t)
    assert (r.roll_number, r.set_code, r.answers, r.flags) == (roll, set_code, answers, [])


@pytest.mark.parametrize("paper", list(PAPERS))
def test_the_pdf_fits_the_chosen_paper_and_reads(paper, tmp_path):
    d = layout(SheetSpec("Paper", 100))
    write_pdf(d, tmp_path / "s.pdf", paper)
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(tmp_path / "s.pdf"))
    assert [round(v / 72 * 25.4) for v in pdf[0].get_size()] == [round(v) for v in PAPERS[paper]]
    pdf.close()
    r = read_page(render(d, dpi=150, paper=paper), parse(d))
    assert not any(r.answers.values()) and {why for _, why in r.flags} == {"blank"}  # only roll and set unfilled


def test_a_sheet_too_big_for_a_page_is_refused():
    with pytest.raises(ValueError, match="don't fit"):
        layout(SheetSpec("Huge", 300, options=8, sections=[SheetSection(f"S{i}", 60) for i in range(5)]))


def test_true_false_and_partial_sections_reach_the_template():
    with pytest.raises(ValueError, match="2 options"):
        layout(SheetSpec("Bad", 10, options=4, true_false=True))
    t = parse(layout(SheetSpec("Mixed", 20, sections=[SheetSection("A", 10), SheetSection("B", 10, partial=True)])))
    assert [g.multi for g in t.grids if g.kind == "questions"] == [False, True]
    d = layout(SheetSpec("Several", 10, roll_digits=0, sets=0, sections=[SheetSection("B", 10, partial=True)]))
    t = parse(d)
    gi = next(i for i, g in enumerate(t.grids) if g.kind == "questions")
    r = read_page(scan(fill(render(d), t, {(gi, 0, 0): "pen", (gi, 0, 2): "pen"}), angle=0.3, seed=4), t)
    assert r.answers[1] == "AC" and r.flags == []
    assert json.loads(json.dumps(d))["sections"][0]["partial"] is True


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


JEE = [s for name in ("Physics", "Chemistry", "Maths")
       for s in (SheetSection(name, 20, 4, -1), SheetSection(f"{name} numeric", 5, 4, -1, digits=3))]


def test_numeric_questions_get_digit_boxes_and_read_back():
    d = layout(SheetSpec("JEE", 75, roll_digits=8, sets=4, sections=JEE))
    t = parse(d)
    numeric = [g.first for g in t.grids if g.kind == "numeric"]
    assert numeric == [*range(21, 26), *range(46, 51), *range(71, 76)] and t.questions() == list(range(1, 76))
    assert d["sections"][1] == {"name": "Physics numeric", "first": 21, "last": 25, "correct": 4, "wrong": -1,
                                "blank": 0.0, "partial": False}
    for seed in (5, 6):
        marks, answers, roll, set_code = random_marks(t, seed)
        page = fill(render(d), t, marks)
        for image in (scan(page, angle=0.6, seed=seed), photo(page, seed=seed)):
            r = read_page(image, t)
            assert (r.roll_number, r.set_code, r.answers, r.flags) == (roll, set_code, answers, [])


def test_a_doubtful_number_is_flagged_not_guessed():
    d = layout(SheetSpec("JEE", 75, roll_digits=8, sets=4, sections=JEE))
    t = parse(d)
    at = {g.first: i for i, g in enumerate(t.grids) if g.kind == "numeric"}
    marks = {(at[21], 4, 0): "pen", (at[21], 2, 2): "pen",  # 4, a blank column, 2
             (at[22], 3, 0): "pen", (at[22], 5, 0): "pen",  # two digits in one column
             (at[23], 0, 0): "pen", (at[23], 0, 1): "pen", (at[23], 7, 2): "pen",  # 007
             (at[24], 9, 1): "pen", (at[24], 1, 2): "pen",  # right-aligned 91
             (at[25], 6, 1): "half"}
    r = read_page(scan(fill(render(d), t, marks), seed=2), t)
    assert {q: r.answers[q] for q in range(21, 26)} == {21: "4?2", 22: "?", 23: "7", 24: "91", 25: ""}
    assert [f for f in r.flags if f[0] in {"Q21", "Q22", "Q23", "Q24", "Q25"}] == [
        ("Q21", "gap between digits"), ("Q22", "multiple marks"), ("Q25", "unclear mark")]


def test_numeric_answers_that_dont_fit_are_refused():
    with pytest.raises(ValueError, match="1 to 6 digits"):
        layout(SheetSpec("Big", 10, sections=[SheetSection("N", 10, digits=7)]))
    with pytest.raises(ValueError, match="don't fit"):
        layout(SheetSpec("Many", 100, sections=[SheetSection("MCQ", 60), SheetSection("N", 40, digits=4)]))
