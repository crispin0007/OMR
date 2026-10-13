from pathlib import Path

import pytest
from openpyxl import Workbook

from omr_core.export import grade
from omr_core.reader import PageResult
from omr_core.store import Store, to_review
from omr_core.students import Student, read_students

TEMPLATE = (Path(__file__).parent.parent / "templates" / "test-100.json").read_text(encoding="utf-8")


def workbook(tmp_path, rows) -> Path:
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    path = tmp_path / "students.xlsx"
    wb.save(path)
    return path


def test_reads_students_and_reports_bad_rows(tmp_path):
    path = workbook(tmp_path, [
        ["Class 10 list"], [],
        ["S.N.", "Roll No.", "Student Name", "Section"],
        [1, 12, "Asha Rai", "A"],           # Excel dropped the leading zeros
        [2, "00345", "Bikash Thapa", "B"],
        [3, None, "No Roll", "A"],
        [4, "12a45", "Bad Roll", "A"],
        [5, 123456, "Too Long", "A"],
        [6, 678, None, "A"],
        [7, "00012", "Same Roll", "B"],
        [None, None, None, None],
    ])
    students, problems = read_students(path, 5)
    assert students == [Student("00012", "Asha Rai", "A"), Student("00345", "Bikash Thapa", "B")]
    assert problems == ["row 6: no roll number", "row 7: roll number '12a45' isn't 5 digits",
                        "row 8: roll number '123456' isn't 5 digits", "row 9: no name for roll number 00678",
                        "row 10: roll number 00012 is also on row 4"]


def test_refuses_files_without_the_columns(tmp_path):
    with pytest.raises(ValueError):
        read_students(workbook(tmp_path, [["Name", "Class"], ["Asha", "A"]]), 5)
    (tmp_path / "not.xlsx").write_bytes(b"not a workbook")
    with pytest.raises(ValueError):
        read_students(tmp_path / "not.xlsx", 5)


def test_names_reach_grading_and_unknown_rolls_are_flagged(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    s.set_students(exam, [Student("11111", "Asha Rai", "A"), Student("22222", "Old", "")])
    s.set_students(exam, [Student("11111", "Asha Rai", "A")])  # an import replaces the list
    assert list(s.students(exam)) == ["11111"] and s.exams()[0][4] == 1
    answers = {q: "A" for q in range(1, 101)}
    s.add_page(exam, "b", "a.png", 1, PageResult("11111", "A", answers, []))
    s.add_page(exam, "b", "a.png", 2, PageResult("99999", "A", answers, []))
    pages, students = s.pages(exam), s.students(exam)
    assert to_review(pages, students) == [(1, "roll number", "not on the student list")]
    assert to_review(pages) == []  # no list, nothing to compare with
    graded = grade(s.exam(exam).template, pages, "A" * 100, 1, 0, 0, students)
    assert [(g.student.name if g.student else None, g.to_check) for g in graded] == [("Asha Rai", False),
                                                                                       (None, True)]


def test_barcode_roll_numbers_are_text(tmp_path):
    path = workbook(tmp_path, [["Roll", "Name"], ["S-0042", "Asha"], [42, "Bina"], ["S 7", "Chet"]])
    students, problems = read_students(path, None)
    assert [s.roll_number for s in students] == ["S-0042", "42"]
    assert problems == ["row 4: roll number 'S 7' has spaces"]


def test_absent_students_have_no_sheet_read():
    from omr_core.students import absent
    students = {r: Student(r, n) for r, n in (("003", "C"), ("001", "A"), ("002", "B"))}
    assert [s.roll_number for s in absent(students, {"002", "999"})] == ["001", "003"]
    assert absent({}, {"001"}) == []
