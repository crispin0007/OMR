import json

import numpy as np
import pypdfium2

from omr_core.export import grade
from omr_core.marking import ANSWER, CHECK, DROP, READ, RIGHT, WRONG, mark_sheet, write_marked_sheets
from omr_core.reader import SCALE, PageResult
from omr_core.sheet import SheetSection, SheetSpec, layout
from omr_core.store import Store
from omr_core.template import parse

SPEC = SheetSpec("JEE", 6, roll_digits=3, sets=0, sections=[SheetSection("MCQ", 4), SheetSection("Numeric", 2, digits=3)])


def setup():
    t = parse(layout(SPEC))
    page = np.full((round(t.page[1] * SCALE), round(t.page[0] * SCALE)), 255, np.uint8)
    radius = round(max(t.bubble) / 2 * SCALE) + 3

    def on_ring(q: int, option: str, row: int | None = None):  # the pixel just right of the bubble, on its ring
        g = t.grid_for(q)
        x, y = g.centre(q - g.first if row is None else row, g.options.index(option) if row is None else 0)
        return round(y * SCALE), round(x * SCALE) + radius
    return t, page, on_ring, radius


def test_right_wrong_missed_dropped_and_bonus_are_coloured():
    t, page, on_ring, radius = setup()
    r = PageResult("012", "", {1: "A", 2: "B", 3: "", 4: "C", 5: "42", 6: ""}, [])
    key = {1: "A", 2: "C", 3: "D", 4: "-", 5: "42", 6: "7"}
    out = mark_sheet(page, t, r, key)
    assert tuple(out[on_ring(1, "A")]) == RIGHT
    assert tuple(out[on_ring(2, "B")]) == WRONG and tuple(out[on_ring(2, "C")]) == ANSWER  # the right one, missed
    assert tuple(out[on_ring(3, "D")]) == ANSWER  # left blank: the right answer is shown
    assert tuple(out[on_ring(4, "C")]) == DROP and tuple(out[on_ring(4, "A")]) == (255, 255, 255)  # nothing missed
    assert tuple(mark_sheet(page, t, r, {3: "*"})[on_ring(3, "D")]) == (255, 255, 255)  # bonus: no answer to show
    assert tuple(mark_sheet(page, t, r, {1: "*"})[on_ring(1, "A")]) == RIGHT
    assert tuple(mark_sheet(page, t, r, {})[on_ring(1, "A")]) == READ  # no key yet: only what was read
    g5, g6 = t.grid_for(5), t.grid_for(6)
    assert tuple(out[round(g5.centre(0, 0)[1] * SCALE) - radius, round(g5.centre(0, 0)[0] * SCALE)]) == RIGHT
    assert tuple(out[round(g6.centre(0, 0)[1] * SCALE) - radius, round(g6.centre(0, 0)[0] * SCALE)]) == ANSWER
    roll = next(g for g in t.grids if g.kind == "roll_number")
    x, y = roll.centre(1, 1)
    assert tuple(out[round(y * SCALE), round(x * SCALE) + radius]) == READ  # the second digit, 1


def test_every_bubble_and_boxes_to_check():
    t, page, *_ = setup()
    r = PageResult("012", "", {q: "" for q in range(1, 7)}, [])
    g = t.grid_for(2)
    x, y = g.centre(1, 3)
    edge = round(y * SCALE), round(x * SCALE) + round(max(t.bubble) / 2 * SCALE)
    assert tuple(mark_sheet(page, t, r, {})[edge]) == (255, 255, 255)
    b, g_, r_ = mark_sheet(page, t, r, {}, every_bubble=True)[edge].astype(int)
    assert (b, g_, r_) != (255, 255, 255) and b > r_  # a thin line, smoothed: GUIDE blended with the paper
    out = mark_sheet(page, t, r, {}, boxes=[(10, 10, 30, 30)])
    assert tuple(out[round(10 * SCALE), round(20 * SCALE)]) == CHECK


def test_marked_sheets_pdf_has_a_page_per_student(tmp_path):
    t, page, *_ = setup()
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", json.dumps(layout(SPEC)))
    for roll in ("001", "002"):
        s.add_page(exam, "b", f"{roll}.png", 1, PageResult(roll, "", {1: "A", 2: "B", 3: "", 4: "C", 5: "4", 6: ""}, []))
    graded = grade(t, s.pages(exam), "A C D A 42 7", 4, -1, 0)
    images = {p.id: page for p in s.pages(exam)}
    images[s.pages(exam)[1].id] = None  # no image saved: left out
    assert write_marked_sheets(tmp_path / "marked.pdf", "Mock", t, graded, images.get) == 1
    pdf = pypdfium2.PdfDocument(tmp_path / "marked.pdf")
    assert len(pdf) == 1 and "Roll number 001" in pdf[0].get_textpage().get_text_range()
