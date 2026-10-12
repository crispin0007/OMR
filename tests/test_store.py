import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from omr_core.reader import PageResult
from omr_core.store import Store

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
    assert s.exams()[0][1:] == ("Mock 1", s.exams()[0][2], 2)
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
from omr_core.store import Store
Store({str(db)!r}).add_page({exam}, "b", "f.png", 1, PageResult("9", "A", {{1: "C"}}, []))
os._exit(1)
"""
    subprocess.run([sys.executable, "-c", code])
    assert [p.result.roll_number for p in Store(db).pages(exam)] == ["9"]
