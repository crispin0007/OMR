"""Exams and the pages read for them, in one SQLite file (FR-015).

Every page is committed as soon as it is read, so a crash or power cut loses
nothing already read. The template is copied into the exam, so moving or
editing the template file later doesn't change an exam's results.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .grading import Section, check_sections, sections_from_json, sections_to_json
from .reader import PageResult
from .students import Student
from .template import Template, parse

SCHEMA = """
CREATE TABLE IF NOT EXISTS exam (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    template TEXT NOT NULL,          -- template JSON
    answer_key TEXT NOT NULL DEFAULT '',
    correct REAL NOT NULL DEFAULT 1,
    wrong REAL NOT NULL DEFAULT 0,
    blank REAL NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    sections TEXT NOT NULL DEFAULT '[]',  -- JSON [Section, ...]
    details TEXT NOT NULL DEFAULT '{}'    -- JSON {"class", "date", "time", "minutes"}, from New exam
);
CREATE TABLE IF NOT EXISTS page (
    id INTEGER PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exam(id) ON DELETE CASCADE,
    batch TEXT NOT NULL,
    file TEXT NOT NULL,
    page_no INTEGER NOT NULL,
    read_at TEXT NOT NULL,
    roll_number TEXT,                -- NULL when the page couldn't be read
    set_code TEXT,
    answers TEXT,                    -- JSON {question: letters}
    flags TEXT,                      -- JSON [[where, why], ...]
    problem TEXT NOT NULL DEFAULT '',
    image BLOB                       -- aligned page as PNG, for review
);
CREATE INDEX IF NOT EXISTS page_exam ON page(exam_id);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    user TEXT NOT NULL,
    item TEXT NOT NULL,              -- "Q12", "roll number digit 3", "set code"
    before TEXT NOT NULL,
    after TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS student (
    exam_id INTEGER NOT NULL REFERENCES exam(id) ON DELETE CASCADE,
    roll_number TEXT NOT NULL,
    name TEXT NOT NULL,
    class_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (exam_id, roll_number)
);
"""


@dataclass
class Exam:
    id: int
    name: str
    template: Template
    template_json: str
    answer_key: str
    correct: float
    wrong: float
    blank: float
    created: str
    sections: list[Section]
    details: dict


@dataclass
class StoredPage:
    id: int
    batch: str
    file: str
    page: int
    read_at: str
    result: PageResult | None  # None when the page couldn't be read; `aligned` is loaded with `image()`
    problem: str


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        columns = [r[1] for r in self.db.execute("PRAGMA table_info(exam)")]
        for column, default in (("sections", "[]"), ("details", "{}")):  # a database from before them
            if column not in columns:
                with self.db:
                    self.db.execute(f"ALTER TABLE exam ADD COLUMN {column} TEXT NOT NULL DEFAULT '{default}'")

    def close(self):
        self.db.close()

    def create_exam(self, name: str, template_json: str, details: dict | None = None) -> int:
        name = name.strip()
        if not name:
            raise ValueError("the exam needs a name")
        d = json.loads(template_json)
        t = parse(d)  # refuse a template the reader can't use
        # A sheet made in the app carries its sections and marks; the exam starts with them.
        sections = sections_from_json(d.get("sections", []))
        check_sections(sections, sorted(g.first + r for g in t.grids if g.kind == "questions" for r in range(g.rows)))
        with self.db:
            cur = self.db.execute("INSERT INTO exam (name, template, created, sections, details) "
                                  "VALUES (?, ?, ?, ?, ?)",
                                  (name, template_json, datetime.now().isoformat(timespec="seconds"),
                                   json.dumps(sections_to_json(sections)), json.dumps(details or {})))
        return cur.lastrowid

    def exams(self) -> list[tuple[int, str, str, int, int]]:
        """(id, name, created, pages, students) for every exam, newest first."""
        return self.db.execute(
            "SELECT e.id, e.name, e.created, (SELECT COUNT(*) FROM page p WHERE p.exam_id = e.id), "
            "(SELECT COUNT(*) FROM student s WHERE s.exam_id = e.id) FROM exam e ORDER BY e.id DESC").fetchall()

    def exam(self, exam_id: int) -> Exam:
        row = self.db.execute("SELECT id, name, template, answer_key, correct, wrong, blank, created, sections, "
                              "details FROM exam WHERE id = ?", (exam_id,)).fetchone()
        if row is None:
            raise KeyError(exam_id)
        return Exam(row[0], row[1], parse(json.loads(row[2])), *row[2:8], sections_from_json(json.loads(row[8])),
                    json.loads(row[9]))

    def save_scheme(self, exam_id: int, answer_key: str, correct: float, wrong: float, blank: float):
        with self.db:
            self.db.execute("UPDATE exam SET answer_key = ?, correct = ?, wrong = ?, blank = ? WHERE id = ?",
                            (answer_key, correct, wrong, blank, exam_id))

    def save_sections(self, exam_id: int, sections: list[Section]):
        t = self.exam(exam_id).template
        check_sections(sections, sorted(g.first + r for g in t.grids if g.kind == "questions" for r in range(g.rows)))
        with self.db:
            self.db.execute("UPDATE exam SET sections = ? WHERE id = ?",
                            (json.dumps(sections_to_json(sections)), exam_id))

    def rename_exam(self, exam_id: int, name: str):
        name = name.strip()
        if not name:
            raise ValueError("the exam needs a name")
        with self.db:
            self.db.execute("UPDATE exam SET name = ? WHERE id = ?", (name, exam_id))

    def delete_exam(self, exam_id: int):
        with self.db:
            self.db.execute("DELETE FROM exam WHERE id = ?", (exam_id,))

    def add_page(self, exam_id: int, batch: str, file: str, page_no: int, result: PageResult | None,
                 problem: str = "") -> StoredPage:
        """Save one page and commit at once."""
        read_at = datetime.now().isoformat(timespec="seconds")
        image = None
        if result is not None and result.aligned is not None:
            ok, png = cv2.imencode(".png", result.aligned)
            image = png.tobytes() if ok else None
        values = (None,) * 4 if result is None else (
            result.roll_number, result.set_code, json.dumps(result.answers), json.dumps(result.flags))
        with self.db:
            cur = self.db.execute(
                "INSERT INTO page (exam_id, batch, file, page_no, read_at, roll_number, set_code, answers, flags, "
                "problem, image) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (exam_id, batch, file, page_no, read_at, *values, problem, image))
        return StoredPage(cur.lastrowid, batch, file, page_no, read_at, result, problem)

    def pages(self, exam_id: int) -> list[StoredPage]:
        """Every page of an exam in the order read, without images."""
        return self._pages("exam_id = ?", exam_id)

    def page(self, page_id: int) -> StoredPage:
        return self._pages("id = ?", page_id)[0]

    def _pages(self, where: str, arg: int) -> list[StoredPage]:
        rows = self.db.execute(
            "SELECT id, batch, file, page_no, read_at, roll_number, set_code, answers, flags, problem FROM page "
            f"WHERE {where} ORDER BY id", (arg,)).fetchall()
        out = []
        for id_, batch, file, page_no, read_at, roll, set_code, answers, flags, problem in rows:
            result = None if roll is None else PageResult(
                roll, set_code, {int(q): a for q, a in json.loads(answers).items()},
                [tuple(f) for f in json.loads(flags)])
            out.append(StoredPage(id_, batch, file, page_no, read_at, result, problem))
        return out

    def correct(self, page_id: int, item: str, value: str, user: str) -> StoredPage:
        """Set one answer, roll number digit or set code by hand, clear its flag, and log the change (FR-013).

        `item` is a flag's "where": "Q12", "roll number digit 3" or "set code". Keeping a reading as it is
        is a correction too: it clears the flag and is logged.
        """
        row = self.db.execute("SELECT p.exam_id, p.roll_number, p.set_code, p.answers, p.flags, e.template "
                              "FROM page p JOIN exam e ON e.id = p.exam_id WHERE p.id = ?", (page_id,)).fetchone()
        if row is None:
            raise KeyError(page_id)
        _, roll, set_code, answers, flags, template = row
        if roll is None:
            raise ValueError("this page couldn't be read; scan it again")
        typed = value.strip()  # a barcode roll number keeps its case
        t, answers, value = parse(json.loads(template)), json.loads(answers), value.upper()
        if item.startswith("Q") and item[1:].isdigit():
            q = int(item[1:])
            grid = next((g for g in t.grids if g.kind == "questions" and g.first <= q < g.first + g.rows), None)
            if grid is None:
                raise ValueError(f"the sheet has no question {q}")
            if any(c not in grid.options for c in value) or len(set(value)) != len(value):
                raise ValueError(f"{value!r} isn't an answer to {item} (options {grid.options})")
            if len(value) > 1 and not grid.multi:
                raise ValueError(f"{item} takes one answer")
            value = "".join(sorted(value))
            before, answers[str(q)] = answers[str(q)], value
        elif item.startswith("roll number digit "):
            n = int(item.rsplit(" ", 1)[1]) - 1
            if not 0 <= n < len(roll) or len(value) != 1 or value not in "0123456789":
                raise ValueError(f"{value!r} isn't a digit for {item}")
            before, roll = roll[n], roll[:n] + value + roll[n + 1:]
        elif item == "roll number":
            grid = next((g for g in t.grids if g.kind == "roll_number"), None)
            if grid and (len(value) != len(roll) or not value.isdigit()):
                raise ValueError(f"the roll number needs {len(roll)} digits")
            if not grid and (not typed or "?" in typed or any(c.isspace() for c in typed)):
                raise ValueError("type the roll number as printed under the barcode")
            before, roll = roll, typed if not grid else value
        elif item == "set code":
            options = next((g.options for g in t.grids if g.kind == "set_code"), "")
            if len(value) != 1 or value not in options:
                raise ValueError(f"{value!r} isn't a set code ({options})")
            before, set_code = set_code, value
        else:
            raise ValueError(f"can't correct {item!r}")
        flags = [f for f in json.loads(flags) if f[0] != item]
        with self.db:
            self.db.execute("UPDATE page SET roll_number = ?, set_code = ?, answers = ?, flags = ? WHERE id = ?",
                            (roll, set_code, json.dumps(answers), json.dumps(flags), page_id))
            self.db.execute("INSERT INTO audit (page_id, at, user, item, before, after) VALUES (?, ?, ?, ?, ?, ?)",
                            (page_id, datetime.now().isoformat(timespec="seconds"), user, item, before, value))
        return self.page(page_id)

    def audit(self, exam_id: int) -> list[tuple[str, str, str, int, str, str, str]]:
        """(at, user, file, page, item, before, after) for every change in an exam, oldest first."""
        return self.db.execute(
            "SELECT a.at, a.user, p.file, p.page_no, a.item, a.before, a.after FROM audit a "
            "JOIN page p ON p.id = a.page_id WHERE p.exam_id = ? ORDER BY a.id", (exam_id,)).fetchall()

    def set_students(self, exam_id: int, students: list[Student]):
        """Replace the exam's student list."""
        with self.db:
            self.db.execute("DELETE FROM student WHERE exam_id = ?", (exam_id,))
            self.db.executemany("INSERT INTO student (exam_id, roll_number, name, class_name) VALUES (?, ?, ?, ?)",
                                [(exam_id, s.roll_number, s.name, s.class_name) for s in students])

    def students(self, exam_id: int) -> dict[str, Student]:
        rows = self.db.execute("SELECT roll_number, name, class_name FROM student WHERE exam_id = ?", (exam_id,))
        return {r[0]: Student(*r) for r in rows}

    def image(self, page_id: int) -> np.ndarray | None:
        row = self.db.execute("SELECT image FROM page WHERE id = ?", (page_id,)).fetchone()
        if not row or row[0] is None:
            return None
        return cv2.imdecode(np.frombuffer(row[0], np.uint8), cv2.IMREAD_GRAYSCALE)


def to_review(pages: list[StoredPage], students: dict[str, Student] | None = None) -> list[tuple[int, str, str]]:
    """(index in pages, item, why) for everything a person must check before results go out.

    The reader's flags, pages that couldn't be read, roll numbers that more than one page has, and,
    when the exam has a student list, roll numbers that aren't on it.
    """
    rolls: dict[str, list[int]] = {}
    for i, p in enumerate(pages):
        if p.result and "?" not in p.result.roll_number:
            rolls.setdefault(p.result.roll_number, []).append(i)
    out = []
    for i, p in enumerate(pages):
        if p.result is None:
            out.append((i, "page", p.problem))
            continue
        out.extend((i, where, why) for where, why in p.result.flags)
        same = [j for j in rolls.get(p.result.roll_number, []) if j != i]
        if same:
            others = ", ".join(f"{Path(pages[j].file).name} page {pages[j].page}" for j in same)
            out.append((i, "roll number", f"same roll number as {others}"))
        elif students and "?" not in p.result.roll_number and p.result.roll_number not in students:
            out.append((i, "roll number", "not on the student list"))
    return out
