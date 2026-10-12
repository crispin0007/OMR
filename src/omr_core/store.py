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

from .reader import PageResult
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
    created TEXT NOT NULL
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

    def close(self):
        self.db.close()

    def create_exam(self, name: str, template_json: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("the exam needs a name")
        parse(json.loads(template_json))  # refuse a template the reader can't use
        with self.db:
            cur = self.db.execute("INSERT INTO exam (name, template, created) VALUES (?, ?, ?)",
                                  (name, template_json, datetime.now().isoformat(timespec="seconds")))
        return cur.lastrowid

    def exams(self) -> list[tuple[int, str, str, int]]:
        """(id, name, created, pages) for every exam, newest first."""
        return self.db.execute(
            "SELECT e.id, e.name, e.created, COUNT(p.id) FROM exam e LEFT JOIN page p ON p.exam_id = e.id "
            "GROUP BY e.id ORDER BY e.id DESC").fetchall()

    def exam(self, exam_id: int) -> Exam:
        row = self.db.execute("SELECT id, name, template, answer_key, correct, wrong, blank, created FROM exam "
                              "WHERE id = ?", (exam_id,)).fetchone()
        if row is None:
            raise KeyError(exam_id)
        return Exam(row[0], row[1], parse(json.loads(row[2])), *row[2:])

    def save_scheme(self, exam_id: int, answer_key: str, correct: float, wrong: float, blank: float):
        with self.db:
            self.db.execute("UPDATE exam SET answer_key = ?, correct = ?, wrong = ?, blank = ? WHERE id = ?",
                            (answer_key, correct, wrong, blank, exam_id))

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
        rows = self.db.execute(
            "SELECT id, batch, file, page_no, read_at, roll_number, set_code, answers, flags, problem FROM page "
            "WHERE exam_id = ? ORDER BY id", (exam_id,)).fetchall()
        out = []
        for id_, batch, file, page_no, read_at, roll, set_code, answers, flags, problem in rows:
            result = None if roll is None else PageResult(
                roll, set_code, {int(q): a for q, a in json.loads(answers).items()},
                [tuple(f) for f in json.loads(flags)])
            out.append(StoredPage(id_, batch, file, page_no, read_at, result, problem))
        return out

    def image(self, page_id: int) -> np.ndarray | None:
        row = self.db.execute("SELECT image FROM page WHERE id = ?", (page_id,)).fetchone()
        if not row or row[0] is None:
            return None
        return cv2.imdecode(np.frombuffer(row[0], np.uint8), cv2.IMREAD_GRAYSCALE)
