"""A test series: several exams taken by the same students, with a rank on their combined score.

Each exam is graded as on its own Results tab. A student who has no graded sheet in an exam scores nothing
for it, so the series rank rewards sitting every test; the number of tests taken is shown beside it.
"""

from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .export import grade, questions
from .grading import full_marks, marks_for, rank
from .store import Store


@dataclass
class SeriesRow:
    roll_number: str
    name: str
    class_name: str
    scores: list[float | None]  # per exam, oldest first; None when the student has no graded sheet in it
    percents: list[float | None]
    total: float = 0.0
    average: float = 0.0  # mean percentage over the tests taken
    taken: int = 0
    rank: int = 0


def series_results(store: Store, series: str) -> tuple[list[str], list[SeriesRow], list[str]]:
    """Exam names oldest first, one row per student best first, and the exams that couldn't be graded and why."""
    exams = [store.exam(i) for i in store.series_exams(series)]
    rows: dict[str, SeriesRow] = {}
    problems = []
    for n, e in enumerate(exams):
        students = store.students(e.id)
        try:
            graded = grade(e.template, store.pages(e.id), e.answer_key, e.correct, e.wrong, e.blank, students,
                           e.sections)
        except ValueError as err:
            problems.append(f"{e.name}: {err}")
            continue
        if not graded:
            problems.append(f"{e.name}: no results yet (no answer key, or no sheets read)")
        marks = marks_for(questions(e.template), e.correct, e.wrong, e.blank, e.sections)
        for g in graded:  # best first, so a roll number read twice keeps its better sheet
            roll = g.page.result.roll_number
            if "?" in roll:
                continue  # an unread roll number belongs to nobody yet; Review fixes it
            row = rows.setdefault(roll, SeriesRow(roll, "", "", [None] * len(exams), [None] * len(exams)))
            if row.scores[n] is not None:
                continue
            out_of = full_marks(g.key, marks)
            row.scores[n] = g.score
            row.percents[n] = round(100 * g.score / out_of, 1) if out_of else None
        for s in students.values():  # names come from the latest list; listed students without a sheet count too
            row = rows.setdefault(s.roll_number, SeriesRow(s.roll_number, "", "", [None] * len(exams),
                                                           [None] * len(exams)))
            row.name, row.class_name = s.name, s.class_name
    out = list(rows.values())
    for row in out:
        taken = [p for p in row.percents if p is not None]
        row.total = sum(s for s in row.scores if s is not None)
        row.taken = sum(s is not None for s in row.scores)
        row.average = round(sum(taken) / len(taken), 1) if taken else 0.0
    out.sort(key=lambda r: (-r.total, r.roll_number))
    for row, (r, _) in zip(out, rank([r.total for r in out])):
        row.rank = r
    return [e.name for e in exams], out, problems


def write_series_excel(path: str | Path, series: str, exams: list[str], rows: list[SeriesRow]):
    """The series merit list: rank, student, each test's score, total, tests taken and average percentage."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Series merit list"
    ws.append([series])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Rank", "Roll number", "Name", "Class", *exams, "Total", "Tests taken", "Average %"])
    for r in rows:
        ws.append([r.rank, r.roll_number, r.name, r.class_name, *("absent" if s is None else s for s in r.scores),
                   r.total, r.taken, r.average])
    for cell in ws[2]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A3"
    for column in ws.columns:
        width = max(len(str(c.value or "")) for c in column[1:]) + 2
        ws.column_dimensions[column[0].column_letter].width = min(max(width, 6), 40)
    wb.save(path)
