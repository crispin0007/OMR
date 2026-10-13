from pathlib import Path

from openpyxl import load_workbook

from omr_core.reader import PageResult
from omr_core.series import series_results, write_series_excel
from omr_core.store import Store
from omr_core.students import Student

TEMPLATE = (Path(__file__).parent.parent / "templates" / "test-100.json").read_text(encoding="utf-8")


def sheet(roll: str, right: int) -> PageResult:
    """A sheet with the first `right` questions right (A) and the rest wrong (B)."""
    return PageResult(roll, "A", {q: "A" if q <= right else "B" for q in range(1, 101)}, [])


def test_series_ranks_students_on_their_combined_score(tmp_path):
    s = Store(tmp_path / "omr.db")
    one = s.create_exam("Mock 1", TEMPLATE, {"series": "JEE"})
    s.set_students(one, [Student("111", "Asha", "12"), Student("222", "Bina", "12"), Student("333", "Chet", "11")])
    two = s.create_exam("Mock 2", TEMPLATE, {"series": "JEE"})
    s.create_exam("Elsewhere", TEMPLATE, {"series": "NEET"})
    for exam, results in ((one, [("111", 60), ("222", 80), ("333", 50)]), (two, [("111", 90), ("222", 40),
                                                                                 ("111", 10), ("9?9", 100)])):
        s.save_scheme(exam, "A" * 100, 1, 0, 0)
        for roll, right in results:
            s.add_page(exam, "b", f"{roll}.png", 1, sheet(roll, right))
    exams, rows, problems = series_results(s, "JEE")
    assert exams == ["Mock 1", "Mock 2"] and problems == []
    # 111 read twice in Mock 2 keeps the better sheet; 9?9 belongs to nobody until Review fixes it;
    # 333 missed Mock 2 and scores nothing for it
    assert [(r.rank, r.roll_number, r.name, r.scores, r.total, r.taken, r.average) for r in rows] == [
        (1, "111", "Asha", [60, 90], 150, 2, 75.0), (2, "222", "Bina", [80, 40], 120, 2, 60.0),
        (3, "333", "Chet", [50, None], 50, 1, 50.0)]

    write_series_excel(tmp_path / "series.xlsx", "JEE", exams, rows)
    ws = load_workbook(tmp_path / "series.xlsx")["Series merit list"]
    assert [c.value for c in ws[2]] == ["Rank", "Roll number", "Name", "Class", "Mock 1", "Mock 2", "Total",
                                        "Tests taken", "Average %"]
    assert [c.value for c in ws[5]] == [3, "333", "Chet", "11", 50, "absent", 50, 1, 50]


def test_an_exam_without_a_key_is_named_not_counted(tmp_path):
    s = Store(tmp_path / "omr.db")
    exam = s.create_exam("Mock 1", TEMPLATE, {"series": "JEE"})
    s.add_page(exam, "b", "1.png", 1, sheet("111", 10))
    assert series_results(s, "JEE")[2] == ["Mock 1: no results yet (no answer key, or no sheets read)"]
    s.save_scheme(exam, "AE", 1, 0, 0)
    assert "Mock 1: line 1: E is not an option" in series_results(s, "JEE")[2][0]
