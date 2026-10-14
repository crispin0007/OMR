"""Exams and the pages read for them, in one SQLite file (FR-015).

Every page is committed as soon as it is read, so a crash or power cut loses
nothing already read. The template is copied into the exam, so moving or
editing the template file later doesn't change an exam's results.
"""

import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import astuple, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from .branding import Institute, check, from_json, to_json
from .grading import Section, check_sections, sections_from_json, sections_to_json
from .reader import PageResult
from .students import Student, check_email, check_phone, link, same_roll
from .template import Template, parse

JPEG_QUALITY = 60
STUDENT = "roll_number, name, class_name, batch, email, phone"  # a Student's columns, in its order
LISTED = STUDENT + ", student_id"  # and on an exam's list, the directory student it is
TRASH_DAYS = 30  # an exam in the Trash is deleted for good after this many days
PNG_MAGIC = b"\x89PNG"

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
    details TEXT NOT NULL DEFAULT '{}',   -- JSON {"class", "date", "time", "minutes", "series"} from New exam,
                                          -- "topics", "institute" (an institute id)
    written_out_of REAL NOT NULL DEFAULT 0, -- marks of the written part, typed in; 0 for none
    archived INTEGER NOT NULL DEFAULT 0,    -- finished and put away: off the exam list, kept everywhere else
    deleted_at TEXT,                        -- when it was moved to the Trash; NULL when it isn't there
    folder_id INTEGER                       -- its program or category; NULL for none
);
CREATE TABLE IF NOT EXISTS folder (      -- a program (IOE, Medical, CMAT), or a category inside one
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES folder(id) ON DELETE CASCADE,  -- the program of a category; NULL for a program
    colour TEXT NOT NULL DEFAULT '',
    institute_id INTEGER                    -- the institute its exams print, unless an exam picks its own
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
    image BLOB,                      -- aligned page as grey JPEG (PNG before 0.2), or an unreadable scan as PNG
    serial TEXT NOT NULL DEFAULT '', -- the sheet number printed on the sheet, '?' if unreadable
    name_read TEXT NOT NULL DEFAULT '[]'  -- JSON: the odds of each letter in the name boxes, word by word
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
CREATE TABLE IF NOT EXISTS key_log (   -- changes to answers already in the key, e.g. a question made a bonus
    id INTEGER PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exam(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    user TEXT NOT NULL,
    set_code TEXT NOT NULL,          -- '' for the key of every set
    question INTEGER NOT NULL,
    before TEXT NOT NULL,            -- answers as in the key: "B", "*", "-", "A/C"
    after TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS written (
    exam_id INTEGER NOT NULL REFERENCES exam(id) ON DELETE CASCADE,
    roll_number TEXT NOT NULL,
    marks REAL NOT NULL,
    PRIMARY KEY (exam_id, roll_number)
);
CREATE TABLE IF NOT EXISTS student (
    exam_id INTEGER NOT NULL REFERENCES exam(id) ON DELETE CASCADE,
    roll_number TEXT NOT NULL,
    name TEXT NOT NULL,
    class_name TEXT NOT NULL DEFAULT '',
    batch TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    student_id TEXT NOT NULL DEFAULT '',   -- the directory student sitting under this roll number; '' for none
    PRIMARY KEY (exam_id, roll_number)
);
CREATE TABLE IF NOT EXISTS directory (   -- the institute's students, kept once for every exam
    roll_number TEXT PRIMARY KEY,            -- the Student ID, kept for good; roll numbers are per exam
    name TEXT NOT NULL,
    class_name TEXT NOT NULL DEFAULT '',
    batch TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS institute (
    id INTEGER PRIMARY KEY,
    body TEXT NOT NULL,              -- JSON of an Institute but its logo
    logo BLOB NOT NULL DEFAULT x'',  -- PNG
    is_default INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS send_log (    -- each result emailed or texted to a student, or tried
    id INTEGER PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exam(id) ON DELETE CASCADE,
    roll_number TEXT NOT NULL,
    channel TEXT NOT NULL,                  -- "email" or "sms"
    address TEXT NOT NULL,
    at TEXT NOT NULL,
    status TEXT NOT NULL,                   -- "sent" or "failed"
    detail TEXT NOT NULL DEFAULT ''         -- why it failed
);
CREATE TABLE IF NOT EXISTS series (      -- how a test series adds up; its exams carry its name in details
    name TEXT PRIMARY KEY,
    best_of INTEGER NOT NULL DEFAULT 0      -- count only each student's best N tests; 0 counts them all
);
CREATE TABLE IF NOT EXISTS setting (     -- the institute's own choices that the reading and results depend on
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exam_template (
    name TEXT PRIMARY KEY,
    body TEXT NOT NULL               -- JSON of a ready-made layout the user saved under their own name
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
    written_out_of: float = 0
    archived: bool = False


@dataclass
class Folder:
    id: int
    name: str
    parent: int | None  # the program a category is in; None for a program
    colour: str = ""
    institute: int | None = None


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
        for column, kind in (("sections", "TEXT NOT NULL DEFAULT '[]'"), ("details", "TEXT NOT NULL DEFAULT '{}'"),
                             ("written_out_of", "REAL NOT NULL DEFAULT 0"), ("archived", "INTEGER NOT NULL DEFAULT 0"),
                             ("deleted_at", "TEXT"), ("folder_id", "INTEGER")):  # a database from before them
            if column not in columns:
                with self.db:
                    self.db.execute(f"ALTER TABLE exam ADD COLUMN {column} {kind}")
        if "serial" not in [r[1] for r in self.db.execute("PRAGMA table_info(page)")]:
            with self.db:
                self.db.execute("ALTER TABLE page ADD COLUMN serial TEXT NOT NULL DEFAULT ''")
        if "name_read" not in [r[1] for r in self.db.execute("PRAGMA table_info(page)")]:
            with self.db:
                self.db.execute("ALTER TABLE page ADD COLUMN name_read TEXT NOT NULL DEFAULT '[]'")
        if "batch" not in [r[1] for r in self.db.execute("PRAGMA table_info(student)")]:
            with self.db:
                for column in ("batch", "email", "phone"):
                    self.db.execute(f"ALTER TABLE student ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        if "student_id" not in [r[1] for r in self.db.execute("PRAGMA table_info(student)")]:
            # Lists from before were matched to the directory by roll number: keep those students linked.
            ids = {same_roll(r): r for (r,) in self.db.execute("SELECT roll_number FROM directory")}
            with self.db:
                self.db.execute("ALTER TABLE student ADD COLUMN student_id TEXT NOT NULL DEFAULT ''")
                self.db.executemany("UPDATE student SET student_id = ? WHERE exam_id = ? AND roll_number = ?",
                                    [(ids[same_roll(r)], e, r) for e, r in
                                     self.db.execute("SELECT exam_id, roll_number FROM student").fetchall()
                                     if same_roll(r) in ids])

    def close(self):
        self.db.close()

    def create_exam(self, name: str, template_json: str, details: dict | None = None) -> int:
        """A new exam. One in a test series (details["series"]) starts with the student list of the latest exam
        of that series that has one, so the list is imported once for the whole series."""
        name = name.strip()
        if not name:
            raise ValueError("the exam needs a name")
        d = json.loads(template_json)
        t = parse(d)  # refuse a template the reader can't use
        # A sheet made in the app carries its sections and marks; the exam starts with them.
        sections = sections_from_json(d.get("sections", []))
        check_sections(sections, t.questions())
        with self.db:
            cur = self.db.execute("INSERT INTO exam (name, template, created, sections, details) "
                                  "VALUES (?, ?, ?, ?, ?)",
                                  (name, template_json, datetime.now().isoformat(timespec="seconds"),
                                   json.dumps(sections_to_json(sections)), json.dumps(details or {})))
        exam_id = cur.lastrowid
        earlier = [e for e in self.series_exams((details or {}).get("series", "")) if e != exam_id]
        listed = next((s for e in reversed(earlier) if (s := self.students(e))), None)
        if listed:
            self.set_students(exam_id, list(listed.values()))
        return exam_id

    def series_names(self) -> list[str]:
        """Every test series an exam belongs to, by name."""
        return sorted({n for (n,) in self.db.execute("SELECT json_extract(details, '$.series') FROM exam "
                                                     "WHERE deleted_at IS NULL") if n})

    def series_exams(self, series: str) -> list[int]:
        """The exams of a test series, oldest first; none for the empty name."""
        if not series.strip():
            return []
        return [i for (i,) in self.db.execute("SELECT id FROM exam WHERE json_extract(details, '$.series') = ? "
                                              "AND deleted_at IS NULL ORDER BY created, id", (series.strip(),))]

    def series_settings(self, series: str) -> dict:
        """{"best_of": N or 0 for every test, "weights": {exam id as text: weight}} for a series; each exam's
        weight is kept with the exam (details["weight"], 1 when not set), so it travels in backups."""
        row = self.db.execute("SELECT best_of FROM series WHERE name = ?", (series.strip(),)).fetchone()
        weights = {str(i): float(self.exam(i).details.get("weight", 1)) for i in self.series_exams(series)}
        return {"best_of": row[0] if row else 0, "weights": weights}

    def save_series_settings(self, series: str, best_of: int, weights: dict[int, float]):
        """Count each student's best `best_of` tests (0 for all), with these weights per exam id. Raises
        ValueError for a negative number or a weight outside 0 to 10."""
        if best_of < 0 or any(not 0 <= w <= 10 for w in weights.values()):
            raise ValueError("best of can't be negative, and a weight goes from 0 to 10")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO series (name, best_of) VALUES (?, ?)", (series.strip(), best_of))
            for exam_id, w in weights.items():
                self.db.execute("UPDATE exam SET details = json_set(details, '$.weight', ?) WHERE id = ?",
                                (w, exam_id))

    def set_messages(self, exam_id: int, messages: dict):
        """The exam's own email subject and body and SMS text, and what to attach (details["messages"])."""
        with self.db:
            self.db.execute("UPDATE exam SET details = json_set(details, '$.messages', json(?)) WHERE id = ?",
                            (json.dumps(messages), exam_id))

    def set_series(self, exam_id: int, series: str):
        """Put an exam in a test series by name, or take it out with ""."""
        with self.db:
            self.db.execute("UPDATE exam SET details = json_set(details, '$.series', ?) WHERE id = ?",
                            (series.strip(), exam_id))

    def exams(self, view: str = "active") -> list[tuple[int, str, str, int, int]]:
        """(id, name, created, pages, students), newest first, for the exams in use ("active"), the archived ones
        ("archived"), both ("kept") or those in the Trash ("trash")."""
        where = {"active": "deleted_at IS NULL AND NOT archived", "archived": "deleted_at IS NULL AND archived",
                 "kept": "deleted_at IS NULL", "trash": "deleted_at IS NOT NULL"}[view]
        return self.db.execute(
            "SELECT e.id, e.name, e.created, (SELECT COUNT(*) FROM page p WHERE p.exam_id = e.id), "
            f"(SELECT COUNT(*) FROM student s WHERE s.exam_id = e.id) FROM exam e WHERE {where} "
            "ORDER BY e.id DESC").fetchall()

    def trash(self) -> list[tuple[int, str, str, int]]:
        """(id, name, moved to the Trash at, pages) for the exams in the Trash, most recently deleted first."""
        return self.db.execute("SELECT e.id, e.name, e.deleted_at, (SELECT COUNT(*) FROM page p WHERE p.exam_id = "
                               "e.id) FROM exam e WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC, id DESC"
                               ).fetchall()

    def move_to_trash(self, exam_id: int, now: datetime | None = None):
        """Put an exam in the Trash with everything read for it; `put_back` brings it back until it is purged."""
        with self.db:
            self.db.execute("UPDATE exam SET deleted_at = ? WHERE id = ?",
                            ((now or datetime.now()).isoformat(timespec="seconds"), exam_id))

    def put_back(self, exam_id: int):
        """Take an exam out of the Trash, as it was."""
        with self.db:
            self.db.execute("UPDATE exam SET deleted_at = NULL WHERE id = ?", (exam_id,))

    def set_archived(self, exam_id: int, archived: bool):
        with self.db:
            self.db.execute("UPDATE exam SET archived = ? WHERE id = ?", (int(archived), exam_id))

    def purge_trash(self, days: int = TRASH_DAYS, now: datetime | None = None) -> list[str]:
        """Delete for good the exams in the Trash for `days` days or more; their names."""
        cutoff = ((now or datetime.now()) - timedelta(days=days)).isoformat(timespec="seconds")
        old = self.db.execute("SELECT id, name FROM exam WHERE deleted_at IS NOT NULL AND deleted_at <= ?",
                              (cutoff,)).fetchall()
        for i, _ in old:
            self.delete_exam(i)
        return [name for _, name in old]

    def exam(self, exam_id: int) -> Exam:
        row = self.db.execute("SELECT id, name, template, answer_key, correct, wrong, blank, created, sections, "
                              "details, written_out_of, archived FROM exam WHERE id = ?", (exam_id,)).fetchone()
        if row is None:
            raise KeyError(exam_id)
        return Exam(row[0], row[1], parse(json.loads(row[2])), *row[2:8], sections_from_json(json.loads(row[8])),
                    json.loads(row[9]), row[10], bool(row[11]))

    def save_scheme(self, exam_id: int, answer_key: str, correct: float, wrong: float, blank: float,
                    changes: list[tuple[str, int, str, str]] = (), user: str = ""):
        """Save the key and marks, with `changes` (set code, question, before, after) in the key's log."""
        at = datetime.now().isoformat(timespec="seconds")
        with self.db:
            self.db.execute("UPDATE exam SET answer_key = ?, correct = ?, wrong = ?, blank = ? WHERE id = ?",
                            (answer_key, correct, wrong, blank, exam_id))
            self.db.executemany("INSERT INTO key_log (exam_id, at, user, set_code, question, before, after) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?)", [(exam_id, at, user, *c) for c in changes])

    def key_log(self, exam_id: int) -> list[tuple[str, str, str, int, str, str]]:
        """(at, user, set code, question, before, after) for every logged change to the key, newest first."""
        return self.db.execute("SELECT at, user, set_code, question, before, after FROM key_log WHERE exam_id = ? "
                               "ORDER BY id DESC", (exam_id,)).fetchall()

    def save_sections(self, exam_id: int, sections: list[Section]):
        t = self.exam(exam_id).template
        check_sections(sections, t.questions())
        with self.db:
            self.db.execute("UPDATE exam SET sections = ? WHERE id = ?",
                            (json.dumps(sections_to_json(sections)), exam_id))

    def set_topics(self, exam_id: int, topics: dict[int, str]):
        """Give questions a topic each, for results by topic; questions left out have none."""
        with self.db:
            self.db.execute("UPDATE exam SET details = json_set(details, '$.topics', json(?)) WHERE id = ?",
                            (json.dumps({str(q): t for q, t in sorted(topics.items())}), exam_id))

    def topics(self, exam_id: int) -> dict[int, str]:
        return {int(q): t for q, t in self.exam(exam_id).details.get("topics", {}).items()}

    # -- institutes ----------------------------------------------------------------------------------------

    def institutes(self) -> list[tuple[int, Institute, bool]]:
        """(id, institute, is the default) for every institute, by name."""
        out = [(i, from_json(json.loads(body), logo), bool(d))
               for i, body, logo, d in self.db.execute("SELECT id, body, logo, is_default FROM institute")]
        return sorted(out, key=lambda r: r[1].name.lower())

    def save_institute(self, inst: Institute, institute_id: int | None = None) -> int:
        """Add an institute, or change the one with this id. The first one is the default.
        Raises ValueError for what `branding.check` refuses."""
        inst = check(inst)
        with self.db:
            if institute_id is None:
                first = not self.db.execute("SELECT 1 FROM institute").fetchone()
                return self.db.execute("INSERT INTO institute (body, logo, is_default) VALUES (?, ?, ?)",
                                       (json.dumps(to_json(inst)), inst.logo, first)).lastrowid
            self.db.execute("UPDATE institute SET body = ?, logo = ? WHERE id = ?",
                            (json.dumps(to_json(inst)), inst.logo, institute_id))
            return institute_id

    def delete_institute(self, institute_id: int):
        """Remove an institute; its exams use the default from then on. Another becomes the default if needed."""
        with self.db:
            self.db.execute("DELETE FROM institute WHERE id = ?", (institute_id,))
            if not self.db.execute("SELECT 1 FROM institute WHERE is_default").fetchone():
                self.db.execute("UPDATE institute SET is_default = 1 WHERE id = (SELECT MIN(id) FROM institute)")

    def set_default_institute(self, institute_id: int):
        with self.db:
            self.db.execute("UPDATE institute SET is_default = (id = ?)", (institute_id,))

    def set_exam_institute(self, exam_id: int, institute_id: int | None):
        """The institute an exam prints; None for the default one."""
        with self.db:
            self.db.execute("UPDATE exam SET details = json_set(details, '$.institute', ?) WHERE id = ?",
                            (institute_id, exam_id))

    def institute_for(self, exam_id: int) -> Institute | None:
        """The exam's own institute, else its category's or program's, else the default, else None when there are
        none."""
        rows = {i: (inst, d) for i, inst, d in self.institutes()}
        folders = {f.id: f for f in self.folders()}
        folder = folders.get(self.exam_folders().get(exam_id))
        for chosen in (self.exam(exam_id).details.get("institute"), folder and folder.institute,
                       folder and folder.parent in folders and folders[folder.parent].institute):
            if chosen in rows:
                return rows[chosen][0]
        return next((inst for inst, d in rows.values() if d), None)

    def folders(self) -> list[Folder]:
        """Programs and their categories, by name."""
        return [Folder(*r) for r in self.db.execute("SELECT id, name, parent_id, colour, institute_id FROM folder "
                                                     "ORDER BY name COLLATE NOCASE")]

    def save_folder(self, name: str, parent: int | None = None, colour: str = "", institute: int | None = None,
                    folder_id: int | None = None) -> int:
        """Add a program (no parent) or a category in a program, or change one; its id. Raises ValueError for an
        empty name, a name its program (or the programs) already have, or a category inside a category."""
        name = " ".join(name.split())
        if not name:
            raise ValueError("it needs a name")
        folders = {f.id: f for f in self.folders()}
        if parent is not None and (parent not in folders or folders[parent].parent is not None):
            raise ValueError("a category goes in a program")
        if folder_id is not None and parent is not None and any(f.parent == folder_id for f in folders.values()):
            raise ValueError("a program with categories can't go inside another program")
        if any(f.name.lower() == name.lower() and f.parent == parent and f.id != folder_id for f in folders.values()):
            raise ValueError(f"there is already a {'category' if parent else 'program'} called “{name}”")
        with self.db:
            if folder_id is None:
                return self.db.execute("INSERT INTO folder (name, parent_id, colour, institute_id) VALUES "
                                       "(?, ?, ?, ?)", (name, parent, colour, institute)).lastrowid
            self.db.execute("UPDATE folder SET name = ?, parent_id = ?, colour = ?, institute_id = ? WHERE id = ?",
                            (name, parent, colour, institute, folder_id))
        return folder_id

    def delete_folder(self, folder_id: int):
        """Delete a program with its categories, or one category. Their exams are kept: a category's go to its
        program, a program's to no program."""
        parent = self.db.execute("SELECT parent_id FROM folder WHERE id = ?", (folder_id,)).fetchone()
        if parent is None:
            return
        inside = [folder_id, *(i for (i,) in self.db.execute("SELECT id FROM folder WHERE parent_id = ?",
                                                             (folder_id,)))]
        with self.db:
            self.db.execute(f"UPDATE exam SET folder_id = ? WHERE folder_id IN ({','.join('?' * len(inside))})",
                            (parent[0], *inside))
            self.db.execute("DELETE FROM folder WHERE id = ?", (folder_id,))

    def set_exam_folder(self, exam_id: int, folder_id: int | None):
        with self.db:
            self.db.execute("UPDATE exam SET folder_id = ? WHERE id = ?", (folder_id, exam_id))

    def exam_folders(self) -> dict[int, int | None]:
        """Exam id to its program or category id (None for none)."""
        return dict(self.db.execute("SELECT id, folder_id FROM exam"))

    def rename_exam(self, exam_id: int, name: str):
        name = name.strip()
        if not name:
            raise ValueError("the exam needs a name")
        with self.db:
            self.db.execute("UPDATE exam SET name = ? WHERE id = ?", (name, exam_id))

    def duplicate_exam(self, exam_id: int, name: str) -> int:
        """A copy of an exam under a new name, with its sheet, sections, marks, written part, program and settings,
        but no answer key, sheets read or students. Its date, time and question topics belong to the paper that
        was set, so they are left for the new one to fill in."""
        name = name.strip()
        if not name:
            raise ValueError("the exam needs a name")
        row = self.db.execute("SELECT template, correct, wrong, blank, sections, details, written_out_of, folder_id "
                              "FROM exam WHERE id = ?", (exam_id,)).fetchone()
        if row is None:
            raise KeyError(exam_id)
        details = {k: v for k, v in json.loads(row[5]).items() if k not in ("date", "time", "topics")}
        with self.db:
            cur = self.db.execute("INSERT INTO exam (name, template, correct, wrong, blank, created, sections, "
                                  "details, written_out_of, folder_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                  (name, row[0], *row[1:4], datetime.now().isoformat(timespec="seconds"), row[4],
                                   json.dumps(details), *row[6:]))
        return cur.lastrowid

    def backup(self, path: str | Path):
        """Copy every exam, with its pages, corrections and students, into one file, safely while in use."""
        part = Path(f"{path}.part")
        part.unlink(missing_ok=True)
        dest = sqlite3.connect(part)
        try:
            self.db.backup(dest)
        finally:
            dest.close()
        os.replace(part, path)  # a half-written backup never takes the name of a good one

    def restore(self, path: str | Path) -> tuple[list[str], list[str]]:
        """Add the exams in a backup alongside the ones here: (names restored, names already here and skipped).
        Nothing here is replaced, so restoring twice or on the wrong PC loses nothing. Raises
        sqlite3.DatabaseError for a file that isn't a database."""
        restored, skipped = [], []
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:  # Windows: a refused file may stay open
            copy = Path(d) / "backup.db"
            shutil.copyfile(path, copy)
            Store(copy).close()  # brings a backup from an older version up to this one; the original is untouched
            self.db.execute("ATTACH DATABASE ? AS b", (str(copy),))
            try:
                here = set(self.db.execute("SELECT name, created FROM exam"))
                with self.db:
                    known = {(body, logo): i
                             for i, body, logo in self.db.execute("SELECT id, body, logo FROM institute")}
                    institutes = {}  # backup's id to the id here; an institute already here is not added twice
                    for old, body, logo in self.db.execute("SELECT id, body, logo FROM b.institute").fetchall():
                        institutes[old] = known.get((body, logo)) or self.db.execute(
                            "INSERT INTO institute (body, logo, is_default) VALUES (?, ?, NOT EXISTS "
                            "(SELECT 1 FROM institute))", (body, logo)).lastrowid
                    folders = {}  # backup's id to the id here; a program or category already here is reused
                    for old, name, parent, colour, inst in self.db.execute(
                            "SELECT id, name, parent_id, colour, institute_id FROM b.folder "
                            "ORDER BY parent_id IS NOT NULL, id").fetchall():
                        parent = folders.get(parent)
                        same = self.db.execute("SELECT id FROM folder WHERE name = ? AND parent_id IS ?",
                                               (name, parent)).fetchone()
                        folders[old] = same[0] if same else self.db.execute(
                            "INSERT INTO folder (name, parent_id, colour, institute_id) VALUES (?, ?, ?, ?)",
                            (name, parent, colour, institutes.get(inst))).lastrowid
                    for old, name, created in self.db.execute("SELECT id, name, created FROM b.exam ORDER BY id"
                                                              ).fetchall():
                        if (name, created) in here:
                            skipped.append(name)
                            continue
                        exam = self.db.execute(
                            "INSERT INTO exam (name, template, answer_key, correct, wrong, blank, created, sections, "
                            "details, written_out_of, archived, deleted_at) SELECT name, template, answer_key, "
                            "correct, wrong, blank, created, sections, details, written_out_of, archived, deleted_at "
                            "FROM b.exam WHERE id = ?", (old,)).lastrowid
                        self.db.execute("UPDATE exam SET folder_id = ? WHERE id = ?", (folders.get(
                            self.db.execute("SELECT folder_id FROM b.exam WHERE id = ?", (old,)).fetchone()[0]), exam))
                        chosen = self.db.execute("SELECT json_extract(details, '$.institute') FROM exam WHERE id = ?",
                                                 (exam,)).fetchone()[0]
                        if chosen is not None:
                            self.db.execute("UPDATE exam SET details = json_set(details, '$.institute', ?) "
                                            "WHERE id = ?", (institutes.get(chosen), exam))
                        for (old_page,) in self.db.execute("SELECT id FROM b.page WHERE exam_id = ? ORDER BY id",
                                                           (old,)).fetchall():
                            page = self.db.execute(
                                "INSERT INTO page (exam_id, batch, file, page_no, read_at, roll_number, set_code, "
                                "answers, flags, problem, image, serial, name_read) SELECT ?, batch, file, page_no, "
                                "read_at, roll_number, set_code, answers, flags, problem, image, serial, name_read "
                                "FROM b.page WHERE id = ?",
                                (exam, old_page)).lastrowid
                            self.db.execute("INSERT INTO audit (page_id, at, user, item, before, after) SELECT ?, at, "
                                            "user, item, before, after FROM b.audit WHERE page_id = ? ORDER BY id",
                                            (page, old_page))
                        self.db.execute("INSERT INTO written (exam_id, roll_number, marks) SELECT ?, roll_number, "
                                        "marks FROM b.written WHERE exam_id = ?", (exam, old))
                        self.db.execute("INSERT INTO send_log (exam_id, roll_number, channel, address, at, status, "
                                        "detail) SELECT ?, roll_number, channel, address, at, status, detail FROM "
                                        "b.send_log WHERE exam_id = ? ORDER BY id", (exam, old))
                        self.db.execute("INSERT INTO key_log (exam_id, at, user, set_code, question, before, after) "
                                        "SELECT ?, at, user, set_code, question, before, after FROM b.key_log "
                                        "WHERE exam_id = ? ORDER BY id", (exam, old))
                        self.db.execute(f"INSERT INTO student (exam_id, {LISTED}) SELECT ?, {LISTED} "
                                        "FROM b.student WHERE exam_id = ?", (exam, old))
                        restored.append(name)
                    self.db.execute("INSERT OR IGNORE INTO exam_template SELECT name, body FROM b.exam_template")
                    self.db.execute("INSERT OR IGNORE INTO series SELECT name, best_of FROM b.series")
                    # a student already in the directory here keeps their details
                    self.db.execute(f"INSERT OR IGNORE INTO directory ({STUDENT}) SELECT {STUDENT} FROM b.directory")
            finally:
                self.db.execute("DETACH DATABASE b")
        return restored, skipped

    def templates(self) -> dict[str, str]:
        """Saved exam templates: name to JSON, by name."""
        return dict(self.db.execute("SELECT name, body FROM exam_template ORDER BY name COLLATE NOCASE"))

    def save_template(self, name: str, body: str, replacing: str = ""):
        """Save a template under `name`, taking the place of `replacing` (a rename) when given."""
        name = name.strip()
        if not name:
            raise ValueError("the template needs a name")
        with self.db:
            if replacing and replacing != name:
                if self.db.execute("SELECT 1 FROM exam_template WHERE name = ?", (name,)).fetchone():
                    raise ValueError(f"there is already a template called “{name}”")
                self.db.execute("DELETE FROM exam_template WHERE name = ?", (replacing,))
            self.db.execute("INSERT OR REPLACE INTO exam_template (name, body) VALUES (?, ?)", (name, body))

    def delete_template(self, name: str):
        with self.db:
            self.db.execute("DELETE FROM exam_template WHERE name = ?", (name,))

    def delete_exam(self, exam_id: int):
        """Delete an exam and everything read for it, for good."""
        with self.db:
            self.db.execute("DELETE FROM exam WHERE id = ?", (exam_id,))

    def delete_pages(self, page_ids: list[int]):
        """Remove pages, with their corrections, for scans that don't belong in the exam."""
        with self.db:
            self.db.executemany("DELETE FROM page WHERE id = ?", [(i,) for i in page_ids])

    def same_sheet(self, exam_id: int, other_id: int) -> bool:
        """Whether two exams read the same printed sheet, so a page read for one is right for the other."""
        def geometry(e: int) -> dict:
            d = json.loads(self.db.execute("SELECT template FROM exam WHERE id = ?", (e,)).fetchone()[0])
            return {k: v for k, v in d.items() if k not in ("name", "print", "sections")}
        return geometry(exam_id) == geometry(other_id)

    def move_pages(self, page_ids: list[int], exam_id: int):
        """Move pages, as read and corrected, to another exam on the same sheet. Raises ValueError otherwise."""
        rows = self.db.execute(f"SELECT DISTINCT exam_id FROM page WHERE id IN ({','.join('?' * len(page_ids))})",
                               page_ids).fetchall()
        if any(not self.same_sheet(e, exam_id) for (e,) in rows):
            raise ValueError("that exam uses a different sheet; import the original scans into it instead")
        with self.db:
            self.db.executemany("UPDATE page SET exam_id = ? WHERE id = ?", [(exam_id, i) for i in page_ids])

    def change_sheet(self, exam_id: int, template_json: str, pages: dict[int, tuple[PageResult | None, str]]):
        """Give an exam another sheet together with every one of its pages read again with it, in one go, so no
        page read with the old sheet is graded on the new one. Sections that still fit stay; otherwise the
        exam takes the new sheet's own (or none). Hand corrections give way to the new readings; the change
        log keeps them. Raises ValueError for a template the reader can't use or a page left out."""
        d = json.loads(template_json)
        t = parse(d)
        questions = t.questions()
        ids = {i for (i,) in self.db.execute("SELECT id FROM page WHERE exam_id = ?", (exam_id,))}
        if set(pages) != ids:
            raise ValueError("every page of the exam must be read again with the new sheet")
        sections = self.exam(exam_id).sections
        try:
            check_sections(sections, questions)
        except ValueError:
            sections = sections_from_json(d.get("sections", []))
            check_sections(sections, questions)
        with self.db:
            self.db.execute("UPDATE exam SET template = ?, sections = ? WHERE id = ?",
                            (template_json, json.dumps(sections_to_json(sections)), exam_id))
            for page_id, (result, problem) in pages.items():
                values, image = _row(result)
                # An unreadable page keeps the image it had, to try yet another sheet with.
                self.db.execute("UPDATE page SET roll_number = ?, set_code = ?, answers = ?, flags = ?, serial = ?, "
                                "name_read = ?, problem = ?, image = COALESCE(?, image) WHERE id = ?",
                                (*values, problem, image, page_id))

    def add_page(self, exam_id: int, batch: str, file: str, page_no: int, result: PageResult | None,
                 problem: str = "", scan: np.ndarray | None = None) -> StoredPage:
        """Save one page and commit at once. An unreadable page keeps its `scan`, to read again with another
        sheet when the scanner's pages have no file to go back to."""
        read_at = datetime.now().isoformat(timespec="seconds")
        values, image = _row(result)
        if result is None and scan is not None:
            image = _png(scan)
        with self.db:
            cur = self.db.execute(
                "INSERT INTO page (exam_id, batch, file, page_no, read_at, roll_number, set_code, answers, flags, "
                "serial, name_read, problem, image) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (exam_id, batch, file, page_no, read_at, *values, problem, image))
        return StoredPage(cur.lastrowid, batch, file, page_no, read_at, result, problem)

    def pages(self, exam_id: int) -> list[StoredPage]:
        """Every page of an exam in the order read, without images."""
        return self._pages("exam_id = ?", exam_id)

    def page(self, page_id: int) -> StoredPage:
        return self._pages("id = ?", page_id)[0]

    def _pages(self, where: str, arg: int) -> list[StoredPage]:
        rows = self.db.execute(
            "SELECT id, batch, file, page_no, read_at, roll_number, set_code, answers, flags, problem, serial, name_read "
            "FROM "
            f"page WHERE {where} ORDER BY id", (arg,)).fetchall()
        out = []
        for id_, batch, file, page_no, read_at, roll, set_code, answers, flags, problem, serial, name in rows:
            result = None if roll is None else PageResult(
                roll, set_code, {int(q): a for q, a in json.loads(answers).items()},
                [tuple(f) for f in json.loads(flags)], serial=serial, name=json.loads(name))
            out.append(StoredPage(id_, batch, file, page_no, read_at, result, problem))
        return out

    def correct(self, page_id: int, item: str, value: str, user: str) -> StoredPage:
        """Set one answer, roll number digit or set code by hand, clear its flag, and log the change (FR-013).

        `item` is a flag's "where": "Q12", "roll number digit 3" or "set code"; a numeric question takes its
        digits. Keeping a reading as it is is a correction too: it clears the flag and is logged.
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
            grid = t.grid_for(q)
            if grid is None:
                raise ValueError(f"the sheet has no question {q}")
            if grid.kind == "numeric":
                if value and (not value.isdigit() or len(value.lstrip("0") or "0") > grid.cols):
                    raise ValueError(f"{item} takes a whole number of up to {grid.cols} digits")
                value = str(int(value)) if value else ""
                before, answers[str(q)] = answers[str(q)], value
            elif any(c not in grid.options for c in value) or len(set(value)) != len(value):
                raise ValueError(f"{value!r} isn't an answer to {item} (options {grid.options})")
            elif len(value) > 1 and not grid.multi:
                raise ValueError(f"{item} takes one answer")
            else:
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
        # The whole roll number typed settles its unclear digits too.
        flags = [f for f in json.loads(flags) if f[0] != item and not (item == "roll number" and
                                                                      f[0].startswith("roll number digit "))]
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
            self.db.executemany(f"INSERT INTO student (exam_id, {LISTED}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                [(exam_id, *astuple(s)) for s in students])

    def set_written_out_of(self, exam_id: int, out_of: float):
        """Marks of the exam's written part, 0 for none. Raises ValueError below a mark already typed."""
        top = self.db.execute("SELECT MAX(marks) FROM written WHERE exam_id = ?", (exam_id,)).fetchone()[0]
        if out_of < 0 or (top is not None and out_of < top):
            raise ValueError(f"a student already has {top:g} written marks" if top is not None and out_of >= 0
                             else "the written part can't be out of less than 0")
        with self.db:
            self.db.execute("UPDATE exam SET written_out_of = ? WHERE id = ?", (out_of, exam_id))

    def set_written(self, exam_id: int, roll_number: str, marks: float | None):
        """One student's written marks, or None to clear them. Raises ValueError outside 0 to the part's marks."""
        out_of = self.db.execute("SELECT written_out_of FROM exam WHERE id = ?", (exam_id,)).fetchone()[0]
        with self.db:
            if marks is None:
                self.db.execute("DELETE FROM written WHERE exam_id = ? AND roll_number = ?", (exam_id, roll_number))
                return
            if not 0 <= marks <= out_of:
                raise ValueError(f"written marks are 0 to {out_of:g}")
            self.db.execute("INSERT OR REPLACE INTO written (exam_id, roll_number, marks) VALUES (?, ?, ?)",
                            (exam_id, roll_number, marks))

    def written(self, exam_id: int) -> dict[str, float]:
        return dict(self.db.execute("SELECT roll_number, marks FROM written WHERE exam_id = ?", (exam_id,)))

    def students(self, exam_id: int) -> dict[str, Student]:
        rows = self.db.execute(f"SELECT {LISTED} FROM student WHERE exam_id = ?", (exam_id,))
        return {r[0]: Student(*r) for r in rows}


    def directory(self) -> list[Student]:
        """The institute's students, by Student ID (kept as their roll_number)."""
        return [Student(*r) for r in self.db.execute(f"SELECT {STUDENT} FROM directory ORDER BY "
                                                     "length(roll_number), roll_number")]

    def save_student(self, student: Student, replacing: str = "") -> Student:
        """Add a student to the directory, or change the one with roll number `replacing`; the student as saved.
        Raises ValueError for a missing roll number or name, a roll number already taken, or a bad contact."""
        roll, name = student.roll_number.strip(), " ".join(student.name.split())
        if not roll or any(c.isspace() for c in roll):
            raise ValueError("the Student ID can't be empty or have spaces")
        if not name:
            raise ValueError("the student needs a name")
        saved = Student(roll, name, student.class_name.strip(), student.batch.strip(), check_email(student.email),
                        check_phone(student.phone))
        with self.db:
            if roll != replacing and self.db.execute("SELECT 1 FROM directory WHERE roll_number = ?",
                                                     (roll,)).fetchone():
                raise ValueError(f"Student ID {roll} is already in the directory")
            if replacing:
                self.db.execute("DELETE FROM directory WHERE roll_number = ?", (replacing,))
                self.db.execute("UPDATE student SET student_id = ? WHERE student_id = ?", (roll, replacing))
            self.db.execute(f"INSERT INTO directory ({STUDENT}) VALUES (?, ?, ?, ?, ?, ?)", astuple(saved)[:6])
        return saved

    def add_to_directory(self, students: list[Student]) -> tuple[int, int]:
        """Add imported students, updating those already there: (added, updated). An empty cell in the import
        keeps what the directory has."""
        known = {s.roll_number: s for s in self.directory()}
        with self.db:
            for s in students:
                old = known.get(s.roll_number)
                if old:
                    s = Student(*(new or was for new, was in zip(astuple(s), astuple(old))))
                self.db.execute(f"INSERT OR REPLACE INTO directory ({STUDENT}) VALUES (?, ?, ?, ?, ?, ?)",
                                astuple(s)[:6])
        added = sum(s.roll_number not in known for s in students)
        return added, len(students) - added

    def new_id(self) -> str:
        """A Student ID not yet used: S0001, S0002, … A letter first, so it never matches a sheet's roll number."""
        taken = [int(r[1:]) for (r,) in self.db.execute("SELECT roll_number FROM directory WHERE roll_number "
                                                         "GLOB 'S[0-9]*'") if r[1:].isdigit()]
        return f"S{max(taken, default=0) + 1:04d}"

    def link_students(self, students: list[Student]) -> tuple[list[Student], int, list[Student]]:
        """An exam's students linked to the directory (see `students.link`), adding the new ones to it with their
        own ID or a new one: (the students, how many were added, those left unlinked between namesakes)."""
        linked, new, unclear = link(students, self.directory())
        numbered = {}
        for s in new:
            sid = s.student_id or self.new_id()
            self.save_student(replace(s, roll_number=sid))
            numbered[id(s)] = sid
        return [replace(s, student_id=numbered[id(s)]) if id(s) in numbered else s for s in linked], len(new), unclear

    def exams_listed(self, student_id: str) -> set[int]:
        """The exams whose list has this directory student."""
        return {e for (e,) in self.db.execute("SELECT exam_id FROM student WHERE student_id = ?", (student_id,))}

    def link_student(self, exam_id: int, roll: str, student_id: str):
        """Say which directory student sits under a roll number on the exam's list; "" unlinks. Raises ValueError
        for an ID the directory doesn't have."""
        if student_id:
            found = [r for (r,) in self.db.execute("SELECT roll_number FROM directory")
                     if same_roll(r) == same_roll(student_id)]
            if not found:
                raise ValueError(f"no student in the directory has Student ID {student_id}")
            student_id = found[0]
        with self.db:
            self.db.execute("UPDATE student SET student_id = ? WHERE exam_id = ? AND roll_number = ?",
                            (student_id, exam_id, roll))

    @property
    def rolls_change(self) -> bool:
        """Whether students sit under a different roll number in each exam. When they don't (the default), a roll
        number is the student's ID in the directory; when they do, only an exam's list says who a roll number is."""
        row = self.db.execute("SELECT value FROM setting WHERE name = 'rolls_change'").fetchone()
        return bool(row and row[0] == "1")

    @rolls_change.setter
    def rolls_change(self, on: bool):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO setting (name, value) VALUES ('rolls_change', ?)", (str(int(on)),))

    def person(self) -> Callable[[int, str], str]:
        """Who sat under a roll number in an exam, as a key that is the same in every exam: the student linked on
        the exam's list, by ID; else the roll number as a Student ID, or, when roll numbers change from exam to
        exam, the roll number in that exam alone. Compared as `same_roll` gives them."""
        links: dict[tuple[int, str], str] = {}
        for e, r, sid in self.db.execute("SELECT exam_id, roll_number, student_id FROM student WHERE student_id != ''"):
            links[e, same_roll(r)] = same_roll(sid)
        if self.rolls_change:
            return lambda exam_id, roll: links.get((exam_id, same_roll(roll))) or f"{exam_id}:{same_roll(roll)}"
        return lambda exam_id, roll: links.get((exam_id, same_roll(roll))) or same_roll(roll)

    def remove_students(self, rolls: list[str]):
        """Take students out of the directory; exams keep their own lists and results."""
        with self.db:
            self.db.executemany("DELETE FROM directory WHERE roll_number = ?", [(r,) for r in rolls])

    def rolls_read(self) -> list[tuple[int, str]]:
        """(exam id, roll number) for every roll number read on a sheet, once per exam."""
        return self.db.execute("SELECT DISTINCT exam_id, roll_number FROM page WHERE roll_number IS NOT NULL"
                               ).fetchall()

    def log_send(self, exam_id: int, roll: str, channel: str, address: str, status: str, detail: str = "",
                 at: datetime | None = None):
        """Note one message sent or failed, as soon as it is known, so a closed app never loses track."""
        with self.db:
            self.db.execute("INSERT INTO send_log (exam_id, roll_number, channel, address, at, status, detail) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)", (exam_id, roll, channel, address,
                                                             (at or datetime.now()).isoformat(timespec="seconds"),
                                                             status, detail))

    def sent_to(self, exam_id: int, channel: str) -> set[str]:
        """Roll numbers this exam's result was already sent to by `channel`."""
        return {r for (r,) in self.db.execute("SELECT roll_number FROM send_log WHERE exam_id = ? AND channel = ? "
                                              "AND status = 'sent'", (exam_id, channel))}

    def send_times(self, channel: str, since: datetime) -> list[datetime]:
        """When each message was sent by `channel` since then, over every exam, for the provider's limits."""
        return [datetime.fromisoformat(a) for (a,) in self.db.execute(
            "SELECT at FROM send_log WHERE channel = ? AND status = 'sent' AND at >= ?",
            (channel, since.isoformat(timespec="seconds")))]

    def send_log(self, exam_id: int) -> list[tuple[str, str, str, str, str, str]]:
        """(at, roll number, channel, address, status, detail) for the exam, newest first."""
        return self.db.execute("SELECT at, roll_number, channel, address, status, detail FROM send_log WHERE "
                               "exam_id = ? ORDER BY id DESC", (exam_id,)).fetchall()

    def exams_taken(self) -> dict[str, int]:
        """Student (as `person` gives them) to the number of exams, not in the Trash, with a sheet read for them."""
        kept = {i for i, *_ in self.exams("kept")}
        person = self.person()
        rolls: dict[str, set[int]] = {}
        for e, r in self.rolls_read():
            if e in kept:
                rolls.setdefault(person(e, r), set()).add(e)
        return {r: len(e) for r, e in rolls.items()}

    def batches(self) -> list[str]:
        """The directory's batches, by name."""
        return [b for (b,) in self.db.execute("SELECT DISTINCT batch FROM directory WHERE batch != '' "
                                              "ORDER BY batch COLLATE NOCASE")]

    def png_pages(self) -> int:
        """Read pages whose image is still a PNG, from before images were saved as JPEG."""
        return self.db.execute("SELECT COUNT(*) FROM page WHERE answers IS NOT NULL AND substr(image, 1, 4) = ?",
                               (PNG_MAGIC,)).fetchone()[0]

    def shrink_images(self, progress=None) -> tuple[int, int]:
        """Save read pages' PNG images as JPEG, then compact the file: (bytes before, bytes after).

        Unreadable pages keep their PNG scan, colour and all, to read again with another sheet. Pages are
        changed in batches, each committed whole, so stopping half way loses nothing. `progress(done, total)`
        returns False to stop.
        """
        path = self.db.execute("PRAGMA database_list").fetchone()[2]
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = Path(path).stat().st_size
        ids = [i for (i,) in self.db.execute("SELECT id FROM page WHERE answers IS NOT NULL AND "
                                             "substr(image, 1, 4) = ? ORDER BY id", (PNG_MAGIC,))]
        for start in range(0, len(ids), 50):
            with self.db:
                for page_id in ids[start:start + 50]:
                    (png,) = self.db.execute("SELECT image FROM page WHERE id = ?", (page_id,)).fetchone()
                    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
                    jpg = encode_page(image) if image is not None else None
                    if jpg:  # a PNG that doesn't decode is left as it is
                        self.db.execute("UPDATE page SET image = ? WHERE id = ?", (jpg, page_id))
            if progress and progress(min(start + 50, len(ids)), len(ids)) is False:
                break
        self.db.execute("VACUUM")
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return before, Path(path).stat().st_size

    def image(self, page_id: int, as_saved: bool = False) -> np.ndarray | None:
        """The aligned page in grey, or as saved (an unreadable page's scan keeps its colour for dropout)."""
        row = self.db.execute("SELECT image FROM page WHERE id = ?", (page_id,)).fetchone()
        if not row or row[0] is None:
            return None
        return cv2.imdecode(np.frombuffer(row[0], np.uint8), cv2.IMREAD_UNCHANGED if as_saved else cv2.IMREAD_GRAYSCALE)


def _png(image: np.ndarray) -> bytes | None:
    ok, png = cv2.imencode(".png", image)
    return png.tobytes() if ok else None


def encode_page(image: np.ndarray) -> bytes | None:
    """The aligned page as grey JPEG, about 6x smaller than PNG.
    Benchmark: 300 generated and 1 real page read again from it gave the same answers and flags as the original."""
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ok, jpg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return jpg.tobytes() if ok else None


def _row(result: PageResult | None) -> tuple[tuple, bytes | None]:
    """(roll number, set code, answers, flags, sheet number, name read) as stored, and the aligned image as JPEG."""
    if result is None:
        return (None,) * 4 + ("", "[]"), None
    return ((result.roll_number, result.set_code, json.dumps(result.answers), json.dumps(result.flags), result.serial,
             json.dumps(result.name)),
            result.aligned if not isinstance(result.aligned, np.ndarray) else encode_page(result.aligned))


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
            others = ", ".join(f"{Path(pages[j].file).name} page {pages[j].page}" for j in same[:3])
            others += f" and {len(same) - 3} more" if len(same) > 3 else ""
            out.append((i, "roll number", f"same roll number as {others}"))
        elif students and "?" not in p.result.roll_number and p.result.roll_number not in students:
            out.append((i, "roll number", "not on the student list"))
    return out


def sheet_number_problems(pages: list[StoredPage]) -> str:
    """What the printed sheet numbers say about the pages: numbers on more than one page, numbers missing between
    the lowest and highest read, and pages whose number can't be read. "" when there's nothing to say."""
    seen: dict[str, int] = {}
    for p in pages:
        if p.result and p.result.serial:
            seen[p.result.serial] = seen.get(p.result.serial, 0) + 1
    unreadable = seen.pop("?", 0)
    twice = [n for n, count in seen.items() if count > 1]
    runs: dict[tuple[str, int], set[int]] = {}  # (prefix, digits) to the numbers read
    for n in seen:
        digits = len(n) - len(n.rstrip("0123456789"))
        if digits:
            runs.setdefault((n[:-digits], digits), set()).add(int(n[-digits:]))
    missing = [f"{prefix}{k:0{digits}d}" for (prefix, digits), got in runs.items()
               for k in range(min(got), max(got) + 1) if k not in got]
    out = []
    for names, what in ((twice, "on more than one page"), (missing, "not scanned")):
        if names:
            listed = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
            out.append(f"Sheet number{'s' if len(names) > 1 else ''} {listed} {what}.")
    if unreadable:
        out.append(f"{unreadable} page{'s' if unreadable > 1 else ''} with a sheet number that can't be read.")
    return " ".join(out)
