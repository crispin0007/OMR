"""One student over every exam: score, rank and sections in each, how they are moving, and who sat which test.

Sheets are matched to a student by their Student ID: an exam's list says which student sat under each roll number,
and a roll number not on it is the directory student with that ID. Leading zeros a sheet's roll number grid keeps
and Excel drops don't count, so "00123" read from a sheet is the directory's "123".
"""

from dataclasses import dataclass, field

from .export import grade, questions
from .grading import DROPPED, full_marks, marks_for
from .store import Store
from .students import same_roll


@dataclass
class Entry:
    exam_id: int
    exam: str
    date: str  # the exam's date from New exam, else the day it was made
    score: float
    out_of: float
    percent: float
    rank: int
    of: int
    percentile: float
    sections: dict[str, float] = field(default_factory=dict)  # percentage per section
    topics: dict[str, tuple[int, int]] = field(default_factory=dict)  # (right, counted) per topic


def history(store: Store, student_id: str, exam_ids: list[int] | None = None) -> list[Entry]:
    """The student's result in each exam (not in the Trash) with a graded sheet for them, under whatever roll
    number, oldest first; their best sheet when one was read twice. `exam_ids` limits it to those exams."""
    want, person = same_roll(student_id), store.person()
    sat = {e for e, r in store.rolls_read() if person(e, r) == want}
    kept = [i for i, *_ in reversed(store.exams("kept")) if i in sat and (exam_ids is None or i in exam_ids)]
    out = []
    for i in kept:
        e = store.exam(i)
        try:
            graded = grade(e.template, store.pages(i), e.answer_key, e.correct, e.wrong, e.blank, store.students(i),
                           e.sections, topics=store.topics(i), doubled_wrong=e.doubled_wrong)
        except ValueError:
            continue  # no usable key yet: the exam's own Answer key tab says why
        g = next((g for g in graded if person(i, g.page.result.roll_number) == want), None)
        if g is None:
            continue
        qs = questions(e.template)
        marks = marks_for(qs, e.correct, e.wrong, e.blank, e.sections, doubled_wrong=e.doubled_wrong)
        out_of = full_marks(g.key, marks)
        sections = {}
        for sec in e.sections:
            most = sum(marks[n][0] for n, q in enumerate(qs) if sec.first <= q <= sec.last and g.key[n] != DROPPED)
            if most:
                sections[sec.name] = round(100 * g.sections.get(sec.name, 0.0) / most, 1)
        out.append(Entry(i, e.name, e.details.get("date") or e.created[:10], g.score, out_of,
                         round(100 * g.score / out_of, 1) if out_of else 0.0, g.rank, len(graded), g.percentile,
                         sections, g.topics))
    return out


def section_averages(entries: list[Entry]) -> list[tuple[str, float, int]]:
    """(section, average percentage, tests) over the student's exams, weakest first."""
    seen: dict[str, list[float]] = {}
    for entry in entries:
        for name, p in entry.sections.items():
            seen.setdefault(name, []).append(p)
    return sorted(((name, round(sum(p) / len(p), 1), len(p)) for name, p in seen.items()), key=lambda s: s[1])


def topic_averages(entries: list[Entry]) -> list[tuple[str, float, int, int]]:
    """(topic, % right, questions, exams) over the student's exams, weakest first. A topic is the same topic in
    every exam that names it alike, so "Kinematics" in three mocks counts as one."""
    seen: dict[str, list[int]] = {}
    for entry in entries:
        for name, (right, counted) in entry.topics.items():
            if counted:
                got = seen.setdefault(name, [0, 0, 0])
                got[0] += right
                got[1] += counted
                got[2] += 1
    return sorted(((name, round(100 * r / n, 1), n, k) for name, (r, n, k) in seen.items()), key=lambda t: t[1])


def attendance(store: Store, students: list[str], exam_ids: list[int]) -> dict[str, list[bool]]:
    """Whether a sheet was read for each student (by Student ID) in each exam, in the order given."""
    read: dict[int, set[str]] = {i: set() for i in exam_ids}
    person = store.person()
    for e, r in store.rolls_read():
        if e in read:
            read[e].add(person(e, r))
    return {sid: [same_roll(sid) in read[i] for i in exam_ids] for sid in students}
