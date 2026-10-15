import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from omr_core.grading import Section
from omr_core.reader import PageResult
from omr_core.sheet import SheetSection, SheetSpec, layout
from omr_core.store import Store, to_review
from omr_core.students import Student

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
    assert np.abs(s.image(page.id).astype(int) - aligned).mean() < 10  # saved as JPEG
    assert second.result is None and second.problem.startswith("unreadable")
    s.delete_exam(exam)
    assert s.exams() == [] and s.pages(exam) == []


def test_sections_are_saved_and_checked(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    assert s.exam(exam).sections == []
    s.save_sections(exam, [Section("Physics", 1, 50, 4, -1), Section("Maths", 51, 100, 3, -1, 0)])
    assert [x.name for x in Store(tmp_path / "omr.db").exam(exam).sections] == ["Physics", "Maths"]
    with pytest.raises(ValueError):
        s.save_sections(exam, [Section("Physics", 1, 120, 4, -1)])  # the sheet has 100 questions


def test_opens_a_database_from_before_sections(tmp_path):
    db = tmp_path / "omr.db"
    old = sqlite3.connect(db)
    old.execute("CREATE TABLE exam (id INTEGER PRIMARY KEY, name TEXT NOT NULL, template TEXT NOT NULL, "
                "answer_key TEXT NOT NULL DEFAULT '', correct REAL NOT NULL DEFAULT 1, wrong REAL NOT NULL DEFAULT 0, "
                "blank REAL NOT NULL DEFAULT 0, created TEXT NOT NULL)")
    old.execute("INSERT INTO exam (name, template, answer_key, created) VALUES ('Old', ?, 'ABCD', '2026-01-01')",
                (TEMPLATE,))
    old.commit()
    old.close()
    e = Store(db).exam(1)
    assert (e.name, e.answer_key, e.sections, e.details) == ("Old", "ABCD", [], {})


def test_exam_details_are_kept(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE, {"class": "10A", "date": "2026-10-20", "time": "10:00", "minutes": 90})
    assert Store(tmp_path / "omr.db").exam(exam).details["class"] == "10A"


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
from omr_core.grading import Section
from omr_core.reader import PageResult
from omr_core.sheet import SheetSection, SheetSpec, layout
from omr_core.store import Store, to_review
from omr_core.students import Student
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


def test_two_marks_follow_the_exams_rule_instead_of_review(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    flags = [("Q1", "unclear mark"), ("Q2", "unclear mark"), ("Q3", "multiple marks"), ("Q4", "unclear mark"),
             ("roll number digit 1", "multiple marks")]
    page = s.add_page(exam, "b", "scan.pdf", 1,
                      PageResult("?23", "A", {1: "B", 2: "", 3: "AC", 4: "AC"}, flags))
    e = s.exam(exam)
    assert (e.multiple, e.faint, e.doubled_wrong) == ("invalid", "review", False)  # a new exam's rule
    got = s.page(page.id).result
    assert got.ruled == [("Q3", "invalid: two bubbles filled")] and ("Q3", "multiple marks") not in got.flags

    s.set_double_marks(exam, wrong=True, multiple="invalid", faint="invalid")
    got = s.page(page.id).result
    # Q2, a faint mark alone, and the roll number still go to Review
    assert got.answers == {1: "!", 2: "", 3: "AC", 4: "!"}
    assert got.flags == [("Q2", "unclear mark"), ("roll number digit 1", "multiple marks")]
    assert [w for w, _ in got.ruled] == ["Q1", "Q3", "Q4"] and s.exam(exam).doubled_wrong

    s.set_double_marks(exam, wrong=False, multiple="review", faint="filled")
    got = s.page(page.id).result
    assert got.answers[1] == "B" and got.ruled == [("Q1", "B: a faint second mark left out")]
    assert got.flags == [("Q2", "unclear mark"), ("Q3", "multiple marks"), ("Q4", "multiple marks"),
                         ("roll number digit 1", "multiple marks")]

    s.set_double_marks(exam, wrong=False, multiple="review", faint="review")  # all back to Review, as read
    assert s.page(page.id).result.flags == flags and s.page(page.id).result.answers[1] == "B"
    with pytest.raises(ValueError):
        s.set_double_marks(exam, wrong=False, multiple="darkest", faint="review")
    assert s.correct(page.id, "Q3", "!", "asha").result.answers[3] == "!"
    assert s.audit(exam)[0][4:] == ("Q3", "AC", "!")


def test_typing_the_whole_roll_number_settles_its_unclear_digits(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    flags = [("roll number digit 2", "unclear mark"), ("roll number digit 3", "blank"), ("Q1", "unclear mark")]
    page = s.add_page(exam, "b", "scan.pdf", 1, PageResult("1??", "A", {1: "B"}, flags))
    fixed = s.correct(page.id, "roll number", "172", "asha")
    assert fixed.result.roll_number == "172" and fixed.result.flags == [("Q1", "unclear mark")]


@pytest.mark.parametrize("item, value", [("Q2", "E"), ("Q2", "AB"), ("Q999", "A"), ("roll number digit 9", "1"),
                                         ("roll number digit 1", "x"), ("roll number", "12"), ("set code", "Z"),
                                         ("name", "A"), ("set code", "!")])
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


def test_many_pages_with_one_roll_number_list_a_few_and_count_the_rest(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    for n in range(1, 7):
        s.add_page(exam, "b", "a.pdf", n, PageResult("111", "A", {1: "B"}, []))
    assert to_review(s.pages(exam))[0] == (0, "roll number", "same roll number as a.pdf page 2, a.pdf page 3, "
                                                             "a.pdf page 4 and 2 more")


def test_pages_can_be_deleted_or_moved_to_an_exam_on_the_same_sheet(tmp_path):
    s = Store(tmp_path / "omr.db")
    first, second = s.create_exam("First", TEMPLATE), s.create_exam("Second", TEMPLATE)
    a = s.add_page(first, "b", "a.pdf", 1, PageResult("111", "A", {1: "B"}, []))
    b = s.add_page(first, "b", "a.pdf", 2, PageResult("222", "A", {1: "C"}, []))
    s.correct(a.id, "Q1", "D", "asha")
    s.move_pages([a.id], second)
    assert [p.result.answers[1] for p in s.pages(second)] == ["D"]  # moves as corrected
    s.delete_pages([b.id])
    assert s.pages(first) == []
    other = json.loads(TEMPLATE)
    other["grids"][0]["origin_mm"] = [o + 5 for o in other["grids"][0]["origin_mm"]]
    third = s.create_exam("Other sheet", json.dumps(other))
    with pytest.raises(ValueError, match="different sheet"):
        s.move_pages([a.id], third)
    assert s.same_sheet(first, second) and not s.same_sheet(first, third)


def test_changing_the_sheet_replaces_every_reading_at_once(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    s.save_sections(exam, [Section("Physics", 1, 100, 4, -1)])
    scan = np.full((40, 30, 3), 200, np.uint8)
    first = s.add_page(exam, "b", "a.pdf", 1, None, "unreadable: another layout", scan)
    second = s.add_page(exam, "b", "a.pdf", 2, PageResult("1", "A", {1: "A"}, [], np.zeros((4, 4), np.uint8)))
    assert np.array_equal(s.image(first.id, as_saved=True), scan)  # kept to read again
    s.correct(second.id, "Q1", "B", "teacher")

    other = json.loads(TEMPLATE)
    other["name"] = "Other"
    with pytest.raises(ValueError, match="every page"):
        s.change_sheet(exam, json.dumps(other), {first.id: (None, "unreadable")})
    read = PageResult("7", "B", {1: "C"}, [("Q1", "unclear mark")], np.ones((4, 4), np.uint8))
    s.change_sheet(exam, json.dumps(other), {first.id: (read, ""), second.id: (None, "unreadable: x")})
    e = s.exam(exam)
    assert e.template.name == "Other" and [x.name for x in e.sections] == ["Physics"]
    a, b = s.pages(exam)
    assert (a.result.roll_number, a.result.answers, a.result.flags, a.problem) == (
        "7", {1: "C"}, [("Q1", "unclear mark")], "")
    assert b.result is None and b.problem == "unreadable: x"
    assert np.array_equal(s.image(a.id), read.aligned) and np.array_equal(s.image(b.id), np.zeros((4, 4)))
    assert len(s.audit(exam)) == 1  # the correction stays in the log

    # Physics 1 to 100 doesn't fit a 30-question sheet: the exam takes that sheet's own sections.
    weekly = layout(SheetSpec("Weekly", 30, sections=[SheetSection("Maths", 30)]))
    s.change_sheet(exam, json.dumps(weekly), {a.id: (None, "unreadable: x"), b.id: (None, "unreadable: x")})
    assert [(x.name, x.first, x.last) for x in s.exam(exam).sections] == [("Maths", 1, 30)]


def test_backup_restores_on_another_pc_without_replacing_anything(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    s.save_scheme(exam, "ABCD", 4, -1, 0)
    page = s.add_page(exam, "b", "a.pdf", 1, PageResult("12", "A", {1: "A"}, [("Q1", "unclear mark")],
                                                         np.zeros((4, 4), np.uint8)))
    s.correct(page.id, "Q1", "B", "teacher")
    s.set_students(exam, [Student("12", "Asha", "10A")])
    s.add_page(exam, "b", "a.pdf", 2, PageResult("13", "A", {1: "A"}, [], serial="0007"))
    s.save_template("Weekly NEET", "{}")
    secret, pc = s.results_secret, s.pc_id()
    s.backup(tmp_path / "backup.db")
    s.backup(tmp_path / "backup.db")  # again, over the last one

    other = Store(tmp_path / "other" / "omr.db")  # the new PC, with an exam of its own
    other.create_exam("Weekly", TEMPLATE)
    other.save_template("Weekly NEET", '{"kept": 1}')
    assert other.restore(tmp_path / "backup.db") == (["Mock"], [])
    assert other.restore(tmp_path / "backup.db") == ([], ["Mock"])  # nothing doubled
    (new_id, *_), = [e for e in other.exams() if e[1] == "Mock"]
    e = other.exam(new_id)
    assert (e.answer_key, e.correct, e.wrong) == ("ABCD", 4, -1) and len(other.exams()) == 2
    p, numbered = other.pages(new_id)
    assert (p.result.serial, numbered.result.serial) == ("", "0007")
    assert p.result.answers == {1: "B"} and p.result.flags == [] and np.array_equal(other.image(p.id), np.zeros((4, 4)))
    assert [a[4:] for a in other.audit(new_id)] == [("Q1", "A", "B")]
    assert other.students(new_id)["12"].name == "Asha"
    assert other.templates() == {"Weekly NEET": '{"kept": 1}'}  # a template here is never replaced
    assert other.results_secret == secret  # students keep their results codes on the new PC
    assert other.pc_id() != pc  # but each PC sends its scans to a main PC under its own id

    (tmp_path / "notes.txt").write_text("not a backup")
    with pytest.raises(sqlite3.DatabaseError):
        other.restore(tmp_path / "notes.txt")
    assert len(other.exams()) == 2


def test_a_numeric_answer_is_corrected_with_its_digits(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("JEE", json.dumps(layout(SheetSpec("JEE", 3, sections=[
        SheetSection("MCQ", 2), SheetSection("Numeric", 1, digits=3)]))))
    page = s.add_page(exam, "b", "scan.pdf", 1, PageResult("12345", "A", {1: "A", 2: "", 3: "4?2"},
                                                           [("Q3", "gap between digits")]))
    for bad in ("4A", "1234", "B", "!"):
        with pytest.raises(ValueError, match="up to 3 digits"):
            s.correct(page.id, "Q3", bad, "asha")
    fixed = s.correct(page.id, "Q3", "042", "asha")
    assert fixed.result.answers[3] == "42" and fixed.result.flags == []
    assert s.audit(exam)[0][4:] == ("Q3", "4?2", "42")


def test_an_exam_in_a_test_series_starts_with_its_student_list(tmp_path):
    s = Store(tmp_path / "omr.db")
    first = s.create_exam("Mock 1", TEMPLATE, {"series": "JEE 2027"})
    s.set_students(first, [Student("12345", "Asha", "12 A")])
    other = s.create_exam("Quiz", TEMPLATE)
    second = s.create_exam("Mock 2", TEMPLATE, {"series": "JEE 2027"})
    assert s.students(second) == {"12345": Student("12345", "Asha", "12 A")} and s.students(other) == {}
    s.set_series(other, " NEET 2027 ")
    assert s.series_names() == ["JEE 2027", "NEET 2027"] and s.series_exams("JEE 2027") == [first, second]
    s.set_series(other, "")
    assert s.series_names() == ["JEE 2027"] and s.series_exams("") == [] and s.exam(other).details == {"multiple": "invalid", "series": ""}


def test_templates_are_saved_renamed_and_deleted(tmp_path):
    s = Store(tmp_path / "omr.db")
    s.save_template(" Mock ", "{}")
    s.save_template("Mock", '{"a": 1}')  # saving again replaces it
    s.save_template("Class test", "{}")
    assert s.templates() == {"Class test": "{}", "Mock": '{"a": 1}'}
    s.save_template("Weekly", '{"a": 1}', replacing="Mock")
    with pytest.raises(ValueError):
        s.save_template("Class test", "{}", replacing="Weekly")  # a rename never overwrites another template
    with pytest.raises(ValueError):
        s.save_template(" ", "{}")
    s.delete_template("Class test")
    assert s.templates() == {"Weekly": '{"a": 1}'}


def test_sheet_numbers_are_kept_and_a_database_from_before_them_opens(tmp_path):
    from omr_core.store import SCHEMA
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock", TEMPLATE)
    s.add_page(exam, "b", "a.pdf", 1, PageResult("12", "A", {1: "A"}, [], serial="A-0001"))
    s.add_page(exam, "b", "a.pdf", 2, None, "unreadable: no corner marks")
    assert [p.result and p.result.serial for p in Store(tmp_path / "omr.db").pages(exam)] == ["A-0001", None]

    old = sqlite3.connect(tmp_path / "old.db")
    before = SCHEMA[:SCHEMA.index("image BLOB,")] + "image BLOB);" + SCHEMA[SCHEMA.index("CREATE INDEX"):]
    old.executescript(before)
    old.execute("INSERT INTO exam (name, template, created) VALUES ('Old', ?, '2026-01-01')", (TEMPLATE,))
    old.execute("INSERT INTO page (exam_id, batch, file, page_no, read_at, roll_number, set_code, answers, flags) "
                "VALUES (1, 'b', 'a.pdf', 1, '2026-01-01', '12', 'A', '{\"1\": \"A\"}', '[]')")
    old.commit()
    old.close()
    assert Store(tmp_path / "old.db").pages(1)[0].result.serial == ""


def test_repeated_missing_and_unreadable_sheet_numbers_are_named():
    from omr_core.store import StoredPage, sheet_number_problems

    def pages(*serials):
        return [StoredPage(k, "b", "a.pdf", k, "", None if n is None else PageResult("1", serial=n), "")
                for k, n in enumerate(serials)]
    assert sheet_number_problems(pages("0001", "0002", "0003", None)) == ""
    assert sheet_number_problems(pages("", "")) == ""  # a sheet without numbers
    assert sheet_number_problems(pages("A-0001", "A-0004", "A-0004", "?", "B-0010", "B-0012")) == (
        "Sheet number A-0004 on more than one page. Sheet numbers A-0002, A-0003, B-0011 not scanned. "
        "1 page with a sheet number that can't be read.")
    assert "and 2 more not scanned" in sheet_number_problems(pages("0001", "0012"))


def test_changes_to_the_key_are_logged_and_restored_with_a_backup(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock 1", TEMPLATE)
    s.save_scheme(exam, "ABCD", 4, -1, 0)
    s.save_scheme(exam, "A, *, C, D", 4, -1, 0, [("", 2, "B", "*")], "teacher")
    s.save_scheme(exam, "A, *, C, -", 4, -1, 0, [("", 4, "D", "-")], "teacher")
    log = s.key_log(exam)
    assert [r[1:] for r in log] == [("teacher", "", 4, "D", "-"), ("teacher", "", 2, "B", "*")]  # newest first
    s.backup(tmp_path / "b.db")
    other = Store(tmp_path / "other.db")
    other.restore(tmp_path / "b.db")
    assert [r[1:] for r in other.key_log(other.exams()[0][0])] == [r[1:] for r in log]


def test_pages_are_saved_as_jpeg_and_an_old_database_is_made_smaller(tmp_path):
    from omr_core.store import _png
    rng = np.random.default_rng(1)
    aligned = rng.integers(180, 256, (600, 400), np.uint8)  # a noisy grey page
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock 1", TEMPLATE)
    new = s.add_page(exam, "b", "new.png", 1, PageResult("1", "A", {1: "B"}, [], aligned))
    assert s.image(new.id).shape == aligned.shape and s.png_pages() == 0
    assert np.abs(s.image(new.id).astype(int) - aligned).mean() < 20
    old = [s.add_page(exam, "b", f"{i}.png", 1, PageResult(str(i), "A", {1: "B"}, [], None)).id for i in range(6)]
    with s.db:  # pages saved by an older version, as PNG
        s.db.executemany("UPDATE page SET image = ? WHERE id = ?", [(_png(aligned), i) for i in old])
    scan = rng.integers(0, 256, (300, 200, 3), np.uint8)
    unread = s.add_page(exam, "b", "bad.png", 1, None, "unreadable: registration mark not found", scan)
    assert s.png_pages() == 6
    seen = []
    before, after = s.shrink_images(lambda done, total: seen.append((done, total)))
    assert after < before / 2 and seen[-1] == (6, 6) and s.png_pages() == 0
    assert s.image(old[0]).shape == aligned.shape
    assert np.array_equal(s.image(unread.id, as_saved=True), scan)  # kept as it was, colour and all
    assert [p.result.roll_number for p in s.pages(exam) if p.result] == ["1", "0", "1", "2", "3", "4", "5"]


def test_institutes_have_a_default_and_each_exam_can_pick_one_and_they_travel_in_a_backup(tmp_path):
    import cv2

    from omr_core.branding import Institute, prepare_logo
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock 1", TEMPLATE)
    assert s.institute_for(exam) is None
    logo = np.full((300, 500, 3), 255, np.uint8)
    cv2.circle(logo, (250, 150), 100, (40, 90, 200), -1)
    png = prepare_logo(cv2.imencode(".png", logo)[1].tobytes())
    first = s.save_institute(Institute(" Sunrise Academy ", address="Lalitpur", email="office@sunrise.example",
                                       logo=png))
    second = s.save_institute(Institute("Evening Campus"))
    assert [(i.name, d) for _, i, d in s.institutes()] == [("Evening Campus", False), ("Sunrise Academy", True)]
    assert s.institute_for(exam).name == "Sunrise Academy" and s.institute_for(exam).logo == png
    s.set_exam_institute(exam, second)
    assert s.institute_for(exam).name == "Evening Campus"
    with pytest.raises(ValueError, match="email"):
        s.save_institute(Institute("X", email="not an address"))
    s.save_institute(Institute("Sunrise Academy", motto="Learn and grow", logo=png), first)
    s.backup(tmp_path / "b.db")

    other = Store(tmp_path / "other.db")
    other.save_institute(Institute("Evening Campus"))  # already there: not added twice
    other.restore(tmp_path / "b.db")
    moved = other.exams()[0][0]
    assert other.institute_for(moved).name == "Evening Campus"
    assert sorted(i.name for _, i, _ in other.institutes()) == ["Evening Campus", "Sunrise Academy"]
    s.delete_institute(first)  # the default goes: the other one takes its place
    assert [(i.name, d) for _, i, d in s.institutes()] == [("Evening Campus", True)]


def test_a_deleted_exam_waits_in_the_trash_then_is_purged(tmp_path):
    from datetime import datetime, timedelta
    s = Store(tmp_path / "omr.db")
    kept = s.create_exam("Mock 1", TEMPLATE, {"series": "CEE"})
    gone = s.create_exam("Mock 2", TEMPLATE, {"series": "CEE"})
    s.add_page(gone, "b", "scan.png", 1, PageResult("123", "A", {1: "B"}, [], None))
    day = datetime(2026, 10, 1, 9)
    s.move_to_trash(gone, now=day)
    assert [e[0] for e in s.exams()] == [kept] and [t[:2] for t in s.trash()] == [(gone, "Mock 2")]
    assert s.series_exams("CEE") == [kept] and len(s.pages(gone)) == 1  # out of the series, sheets kept

    s.set_archived(kept, True)
    assert s.exams() == [] and [e[0] for e in s.exams("archived")] == [kept] and s.exam(kept).archived
    assert s.series_exams("CEE") == [kept]  # an archived exam still counts in its series

    backup = tmp_path / "backup.db"
    s.backup(backup)
    other = Store(tmp_path / "other.db")
    other.restore(backup)
    assert [e[1] for e in other.exams("archived")] == ["Mock 1"] and [t[1] for t in other.trash()] == ["Mock 2"]

    assert s.purge_trash(now=day + timedelta(days=29)) == []
    s.put_back(gone)
    assert s.trash() == [] and {e[0] for e in s.exams()} == {gone}
    s.move_to_trash(gone, now=day)
    assert s.purge_trash(now=day + timedelta(days=30)) == ["Mock 2"]
    assert s.trash() == [] and s.pages(gone) == []


def test_programs_and_categories_hold_exams_and_give_them_an_institute(tmp_path):
    from omr_core.branding import Institute
    s = Store(tmp_path / "omr.db")
    ioe = s.save_folder("IOE", colour="#1565c0")
    mocks = s.save_folder("Full mocks", ioe)
    medical = s.save_folder("Medical")
    with pytest.raises(ValueError, match="already a program"):
        s.save_folder("ioe")
    with pytest.raises(ValueError, match="a category goes in a program"):
        s.save_folder("Deeper", mocks)
    with pytest.raises(ValueError, match="can't go inside another program"):
        s.save_folder("IOE", medical, folder_id=ioe)
    s.save_folder("Full mocks", medical)  # the same name in another program is fine

    first = s.save_institute(Institute("First Academy"))
    branch = s.save_institute(Institute("Branch School"))
    s.save_folder("IOE", None, "#1565c0", branch, folder_id=ioe)
    one, two, loose = (s.create_exam(n, TEMPLATE) for n in ("Mock 1", "Mock 2", "Loose"))
    s.set_exam_folder(one, mocks)
    s.set_exam_folder(two, ioe)
    assert s.institute_for(one).name == "Branch School" and s.institute_for(loose).name == "First Academy"
    s.set_exam_institute(one, first)
    assert s.institute_for(one).name == "First Academy"  # the exam's own choice wins

    backup = tmp_path / "backup.db"
    s.backup(backup)
    other = Store(tmp_path / "other.db")
    other.save_folder("IOE")
    other.restore(backup)
    names = {f.id: f.name for f in other.folders()}
    assert sorted(names.values()) == ["Full mocks", "Full mocks", "IOE", "Medical"]  # IOE wasn't added twice
    moved = {other.exam(i).name: names.get(f) for i, f in other.exam_folders().items()}
    assert moved == {"Mock 1": "Full mocks", "Mock 2": "IOE", "Loose": None}

    s.delete_folder(mocks)
    assert s.exam_folders()[one] == ioe  # a category's exams go to its program
    s.delete_folder(ioe)
    assert s.exam_folders()[one] is None and s.exam_folders()[two] is None
    assert [f.name for f in s.folders()] == ["Full mocks", "Medical"] and len(s.exams()) == 3


def test_a_duplicated_exam_keeps_its_sheet_and_marks_but_nothing_read(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock 1", TEMPLATE, {"class": "12", "date": "2026-10-01", "series": "Weekly"})
    s.save_scheme(exam, "A: ABCD", 4, -1, 0)
    s.set_written_out_of(exam, 20)
    s.set_students(exam, [Student("1", "Asha Rai")])
    s.add_page(exam, "b", "scan.pdf", 1, PageResult("1", "A", {1: "B"}, []))
    with pytest.raises(ValueError):
        s.duplicate_exam(exam, " ")
    copy = s.exam(s.duplicate_exam(exam, " Mock 2 "))
    assert copy.name == "Mock 2" and copy.answer_key == "" and (copy.correct, copy.wrong) == (4, -1)
    assert copy.written_out_of == 20 and copy.details == {"multiple": "invalid", "class": "12", "series": "Weekly"}
    assert s.pages(copy.id) == [] and s.students(copy.id) == {}
    assert s.exam(exam).answer_key == "A: ABCD" and len(s.pages(exam)) == 1


def test_exam_lists_link_to_directory_students(tmp_path):
    db = tmp_path / "omr.db"
    s = Store(db)
    s.save_student(Student("12", "Asha Rai"))
    s.save_student(Student("13", "Bina KC", phone="9800000001"))
    s.save_student(Student("14", "Bina KC", phone="9800000002"))
    s.save_student(Student("15", "Chet Lama"))
    exam = s.create_exam("Mock", TEMPLATE)
    students, added, unclear = s.link_students([
        Student("101", " asha  rai "), Student("102", "Bina KC", phone="9800000002"), Student("103", "Bina KC"),
        Student("104", "Dev Shah"), Student("105", "Eva", student_id="REG-9"), Student("106", "Chet", student_id="15")])
    assert [x.student_id for x in students] == ["12", "14", "", "S0001", "REG-9", "15"]
    assert added == 2 and [x.roll_number for x in unclear] == ["103"]
    assert {d.roll_number: d.name for d in s.directory()}["S0001"] == "Dev Shah" and s.new_id() == "S0002"
    s.set_students(exam, students)
    s.link_student(exam, "103", "13")
    with pytest.raises(ValueError, match="no student in the directory"):
        s.link_student(exam, "103", "99")
    s.save_student(Student("ASHA-1", "Asha Rai"), "12")  # a new ID carries her links
    assert s.students(exam)["101"].student_id == "ASHA-1" and s.students(exam)["103"].student_id == "13"
    assert s.exams_listed("ASHA-1") == {exam}
    person = s.person()
    assert person(exam, "101") == "ASHA-1" and person(exam, "0015") == "15"  # off the list: the roll as an ID
    s.rolls_change = True
    assert s.person()(exam, "0015") == f"{exam}:15" and Store(db).rolls_change
    secret = s.results_secret
    assert len(secret) == 32 and Store(db).results_secret == secret  # made once, then kept


def test_lists_from_before_links_are_linked_by_roll_number(tmp_path):
    db = tmp_path / "omr.db"
    s = Store(db)
    exam = s.create_exam("Mock", TEMPLATE)
    s.save_student(Student("12", "Asha Rai"))
    s.close()
    old = sqlite3.connect(db)
    old.execute("ALTER TABLE student DROP COLUMN student_id")
    old.executemany("INSERT INTO student (exam_id, roll_number, name) VALUES (?, ?, ?)",
                    [(exam, "0012", "Asha Rai"), (exam, "77", "Someone")])
    old.commit()
    old.close()
    students = Store(db).students(exam)
    assert students["0012"].student_id == "12" and students["77"].student_id == ""
