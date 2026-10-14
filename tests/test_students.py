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


def test_reads_batch_email_and_phone_and_leaves_out_a_bad_contact(tmp_path):
    path = workbook(tmp_path, [
        ["Roll", "Name", "Batch", "Email", "Mobile"],
        [101, "Asha Rai", "IOE morning", "asha@example.org", 9800000001],
        [102, "Bikash Thapa", "IOE morning", "not an email", "+977 980-000-0002"],
        [103, "Chandra KC", "", "", "12"],
    ])
    students, problems = read_students(path, None)
    assert students == [Student("101", "Asha Rai", "", "IOE morning", "asha@example.org", "9800000001"),
                        Student("102", "Bikash Thapa", "", "IOE morning", "", "+9779800000002"),
                        Student("103", "Chandra KC")]
    assert problems == ["row 3: email 'not an email' doesn't look like an email address; 102 imported without it",
                        "row 4: phone '12' isn't a phone number; 103 imported without it"]


def test_the_directory_keeps_students_once_and_an_exam_takes_a_batch(tmp_path):
    from omr_core.students import for_sheet
    s = Store(tmp_path / "omr.db")
    s.save_student(Student("12", " Asha  Rai ", "11", "CEE", "asha@example.org", "+977 9800000001"))
    with pytest.raises(ValueError, match="already in the directory"):
        s.save_student(Student("12", "Someone"))
    with pytest.raises(ValueError, match="doesn't look like an email"):
        s.save_student(Student("13", "Bikash", email="bikash@"))
    assert s.add_to_directory([Student("12", "Asha Rai", "", "", "", "9811111111"), Student("123456", "Too Long",
                                                                                            batch="CEE")]) == (1, 1)
    assert s.directory() == [Student("12", "Asha Rai", "11", "CEE", "asha@example.org", "9811111111"),
                             Student("123456", "Too Long", batch="CEE")]  # an empty cell kept what was there
    assert s.batches() == ["CEE"]
    s.save_student(Student("14", "Asha Rai", batch="IOE"), replacing="12")
    assert [x.roll_number for x in s.directory()] == ["14", "123456"]

    fit, problems = for_sheet(s.directory(), 5)
    assert [x.roll_number for x in fit] == ["00014"] and problems == ["123456 Too Long: not a roll number of 5 digits"]
    exam = s.create_exam("Mock", TEMPLATE)
    s.set_students(exam, fit)
    assert s.students(exam)["00014"].batch == "IOE"
    s.remove_students(["14"])
    assert [x.roll_number for x in s.directory()] == ["123456"] and "00014" in s.students(exam)


def test_a_students_history_and_attendance_match_their_roll_number(tmp_path):
    from omr_core.grading import Section
    from omr_core.progress import attendance, history, section_averages
    s = Store(tmp_path / "omr.db")
    one, two, three = (s.create_exam(n, TEMPLATE, {"date": f"2026-10-0{k}"}) for k, n in
                       enumerate(("Mock 1", "Mock 2", "Mock 3"), 1))
    for exam, right in ((one, 40), (two, 70)):
        s.save_scheme(exam, "A" * 100, 1, 0, 0)
        s.save_sections(exam, [Section("Physics", 1, 50, 1, 0, 0), Section("Chemistry", 51, 100, 1, 0, 0)])
        for roll, r in (("00012", right), ("00034", 50)):
            s.add_page(exam, "b", "x.png", 1, PageResult(roll, "A", {q: "A" if q <= r else "B" for q in range(1, 101)},
                                                         []))
    s.add_page(three, "b", "x.png", 1, PageResult("00034", "A", {}, []))  # no key yet: left out
    s.move_to_trash(s.create_exam("Gone", TEMPLATE))

    entries = history(s, "12")  # the directory's 12 is the sheet's 00012
    assert [(e.exam, e.date, e.score, e.percent, e.rank, e.of) for e in entries] == [
        ("Mock 1", "2026-10-01", 40, 40.0, 2, 2), ("Mock 2", "2026-10-02", 70, 70.0, 1, 2)]
    assert entries[1].sections == {"Physics": 100.0, "Chemistry": 40.0}
    assert section_averages(entries) == [("Chemistry", 20.0, 2), ("Physics", 90.0, 2)]
    assert attendance(s, ["12", "34", "56"], [one, three]) == {"12": [True, False], "34": [True, True],
                                                               "56": [False, False]}
    assert s.exams_taken() == {"12": 2, "34": 3}
