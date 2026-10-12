from pathlib import Path

import pypdfium2
from openpyxl import load_workbook

from omr_core.export import grade, write_excel, write_scorecards
from omr_core.reader import PageResult
from omr_core.store import Store

TEMPLATE = (Path(__file__).parent.parent / "templates" / "test-100.json").read_text(encoding="utf-8")


def exam_with_pages(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock 1", TEMPLATE)
    t = s.exam(exam).template
    key = "AB*-" + "A" * 96
    for roll, first, flags in (("111", "ABCD", []), ("222", "BB", [("Q3", "unclear mark")]), ("333", "ABCD", []),
                               ("444", "", [])):
        answers = {q: "A" for q in range(5, 101)}
        answers.update({q + 1: a for q, a in enumerate(first)})
        answers.update({q: answers.get(q, "") for q in range(1, 5)})
        s.add_page(exam, "b", f"{roll}.png", 1, PageResult(roll, "A", answers, flags))
    s.add_page(exam, "b", "bad.png", 1, None, "unreadable: registration mark not found")
    return t, s.pages(exam), key


def test_grade_ranks_ties_bonus_and_dropped(tmp_path):
    t, pages, key = exam_with_pages(tmp_path)
    graded = grade(t, pages, key, 4, -1, 0)
    assert [(g.page.result.roll_number, g.score, g.rank) for g in graded] == [
        ("111", 396, 1), ("333", 396, 1), ("222", 391, 3), ("444", 388, 4)]
    by_roll = {g.page.result.roll_number: g for g in graded}
    # 111: Q1 right, Q2 right, Q3 bonus, Q4 dropped, 96 right -> 99 right
    assert (by_roll["111"].right, by_roll["111"].wrong, by_roll["111"].blank, by_roll["111"].score) == (99, 0, 0, 396)
    # 222: Q1 wrong (B), Q2 right, Q3 bonus even though blank, Q4 dropped
    assert (by_roll["222"].right, by_roll["222"].wrong, by_roll["222"].score) == (98, 1, 391)
    # 444: Q1, Q2 blank, Q3 bonus
    assert (by_roll["444"].blank, by_roll["444"].score) == (2, 388)
    assert by_roll["222"].to_check and not by_roll["111"].to_check
    assert [g.rank for g in graded] == [1, 1, 3, 4] and len(graded) == 4  # the unreadable page is left out
    assert graded[0].percentile == 100


def test_merit_list_and_scorecards(tmp_path):
    t, pages, key = exam_with_pages(tmp_path)
    graded = grade(t, pages, key, 4, -1, 0)
    write_excel(tmp_path / "merit.xlsx", "Mock 1", t, graded)
    wb = load_workbook(tmp_path / "merit.xlsx")
    rows = list(wb["Merit list"].iter_rows(min_row=3, values_only=True))
    assert [(r[0], r[1], r[3]) for r in rows] == [(g.rank, g.page.result.roll_number, g.score) for g in graded]
    answers = wb["Answers"]
    assert answers["A2"].value == graded[0].page.result.roll_number and answers.max_column == 102
    write_scorecards(tmp_path / "cards.pdf", "Mock 1", t, graded)
    pdf = pypdfium2.PdfDocument(tmp_path / "cards.pdf")
    assert len(pdf) == 4
    text = pdf[0].get_textpage().get_text_range()
    assert "Roll number 111" in text and "Rank 1 of 4" in text
