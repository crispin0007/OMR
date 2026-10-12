import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from omr_core.reader import PageResult
from omr_core.store import Store, to_review

TEMPLATE = (Path(__file__).parent.parent / "templates" / "test-100.json").read_text(encoding="utf-8")


def test_exam_scheme_and_pages_survive_reopening(tmp_path):
    db = tmp_path / "omr.db"
    s = Store(db)
    exam = s.create_exam(" Mock 1 ", TEMPLATE)
    s.save_scheme(exam, "A: ABCD", 4, -1, 0)
    aligned = np.full((40, 30), 255, np.uint8)
    aligned[10:20, 5:15] = 0
    page = s.add_page(exam, "batch 1", "scan.pdf", 2, PageResult("123", "A", {1: "B", 2: ""}, [("Q2", "unclear mark")],
                                                                aligned))
    s.add_page(exam, "batch 1", "scan.pdf", 3, None, "unreadable: registration mark not found")
    s.close()

    s = Store(db)
    assert s.exams()[0][1:] == ("Mock 1", s.exams()[0][2], 2, 0)
    e = s.exam(exam)
    assert (e.answer_key, e.correct, e.wrong, e.template.name) == ("A: ABCD", 4, -1, json.loads(TEMPLATE)["name"])
    first, second = s.pages(exam)
    assert first.result.answers == {1: "B", 2: ""} and first.result.flags == [("Q2", "unclear mark")]
    assert (first.file, first.page, first.batch) == ("scan.pdf", 2, "batch 1")
    assert np.array_equal(s.image(page.id), aligned)
    assert second.result is None and second.problem.startswith("unreadable")
    s.delete_exam(exam)
    assert s.exams() == [] and s.pages(exam) == []


def test_refuses_bad_exams(tmp_path):
    s = Store(tmp_path / "omr.db")
    with pytest.raises(ValueError):
        s.create_exam("  ", TEMPLATE)
    with pytest.raises(ValueError):
        s.create_exam("Mock", json.dumps({"version": 1}))
    with pytest.raises(KeyError):
        s.exam(99)


def test_a_page_is_kept_when_the_app_dies_right_after_reading_it(tmp_path):
    db = tmp_path / "omr.db"
    exam = Store(db).create_exam("Mock", TEMPLATE)
    # Save one page, then end the process without closing anything.
    code = f"""
import os
from omr_core.reader import PageResult
from omr_core.store import Store, to_review
Store({str(db)!r}).add_page({exam}, "b", "f.png", 1, PageResult("9", "A", {{1: "C"}}, []))
os._exit(1)
"""
    subprocess.run([sys.executable, "-c", code])
    assert [p.result.roll_number for p in Store(db).pages(exam)] == ["9"]


def test_corrections_update_the_page_clear_the_flag_and_are_logged(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    flags = [("Q2", "multiple marks"), ("roll number digit 2", "blank"), ("set code", "unclear mark")]
    page = s.add_page(exam, "b", "scan.pdf", 1, PageResult("1?3", "?", {1: "B", 2: "AC"}, flags))
    s.correct(page.id, "Q2", "c", "asha")
    s.correct(page.id, "roll number digit 2", "7", "asha")
    fixed = s.correct(page.id, "set code", "B", "asha")
    assert fixed.result.answers[2] == "C" and fixed.result.roll_number == "173" and fixed.result.set_code == "B"
    assert fixed.result.flags == []
    assert [row[1:] for row in s.audit(exam)] == [
        ("asha", "scan.pdf", 1, "Q2", "AC", "C"), ("asha", "scan.pdf", 1, "roll number digit 2", "?", "7"),
        ("asha", "scan.pdf", 1, "set code", "?", "B")]
    s.correct(page.id, "Q1", "", "asha")  # blank is an answer too
    assert s.page(page.id).result.answers[1] == ""


@pytest.mark.parametrize("item, value", [("Q2", "E"), ("Q2", "AB"), ("Q999", "A"), ("roll number digit 9", "1"),
                                         ("roll number digit 1", "x"), ("roll number", "12"), ("set code", "Z"),
                                         ("name", "A")])
def test_refuses_bad_corrections(tmp_path, item, value):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    page = s.add_page(exam, "b", "scan.pdf", 1, PageResult("123", "A", {1: "B", 2: "C"}, []))
    with pytest.raises(ValueError):
        s.correct(page.id, item, value, "asha")
    assert s.audit(exam) == []


def test_unreadable_pages_cant_be_corrected(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    page = s.add_page(exam, "b", "scan.pdf", 1, None, "unreadable: registration mark not found")
    with pytest.raises(ValueError):
        s.correct(page.id, "Q1", "A", "asha")


def test_review_lists_flags_unreadable_pages_and_duplicate_rolls(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    s.add_page(exam, "b", "a.pdf", 1, PageResult("111", "A", {1: "B"}, [("Q1", "unclear mark")]))
    s.add_page(exam, "b", "a.pdf", 2, PageResult("111", "A", {1: "B"}, []))
    s.add_page(exam, "b", "a.pdf", 3, PageResult("222", "A", {1: "B"}, []))
    s.add_page(exam, "b", "a.pdf", 4, None, "unreadable: registration mark not found")
    assert to_review(s.pages(exam)) == [
        (0, "Q1", "unclear mark"), (0, "roll number", "same roll number as a.pdf page 2"),
        (1, "roll number", "same roll number as a.pdf page 1"), (3, "page", "unreadable: registration mark not found")]
    second = s.pages(exam)[1]
    s.correct(second.id, "roll number", "333", "asha")
    assert to_review(s.pages(exam)) == [(0, "Q1", "unclear mark"), (3, "page", "unreadable: registration mark not found")]
