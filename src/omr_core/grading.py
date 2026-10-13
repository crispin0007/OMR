"""Score answered sheets against a key, and rank the results.

Answers and keys are strings of option letters: "B" for one answer, "AC" for
multi-correct, "" for blank. A numeric question's answer and key are its
digits, e.g. "42"; an answer is right when it is the same number. In a key, "*" is a bonus question (everyone gets
the correct marks) and "-" is a dropped question (it counts for nobody).
Sheets reach grading after review, so every answer here is already decided.

Sections give a range of questions its own marks, e.g. 4 right and -1 wrong
for Physics 1 to 50; questions outside every section use the exam's marks.
A section with partial marking gives part of the correct marks to an answer
that picks some of a multi-correct question's options and no wrong one.
Two or more bubbles filled on a single-answer question (one printed for one
answer, with a one-letter key) are invalid: no marks, not even negative ones;
the reader flags them for review.
"""

import csv
import io
import re
from dataclasses import asdict, dataclass

from .template import DIGITS

BONUS, DROPPED = "*", "-"


@dataclass(frozen=True)
class Section:
    name: str
    first: int  # question numbers, inclusive
    last: int
    correct: float
    wrong: float
    blank: float = 0.0
    partial: bool = False  # part marks for some but not all of a multi-correct answer


def check_sections(sections: list[Section], questions: list[int]) -> None:
    """Raises ValueError when a section is empty, off the sheet, or overlaps another."""
    names = set()
    for s in sections:
        if not s.name.strip():
            raise ValueError("every section needs a name")
        if s.name in names:
            raise ValueError(f"two sections are called {s.name}")
        names.add(s.name)
        if s.wrong > 0 or s.blank > 0:
            raise ValueError(f"{s.name}: wrong and blank marks can't be more than 0; use e.g. -0.25 for negative marking")
        if s.first > s.last:
            raise ValueError(f"{s.name}: starts at question {s.first} but ends at {s.last}")
        if s.first not in questions or s.last not in questions:
            raise ValueError(f"{s.name}: the sheet has questions {questions[0]} to {questions[-1]}")
    ordered = sorted(sections, key=lambda s: s.first)
    for a, b in zip(ordered, ordered[1:]):
        if b.first <= a.last:
            raise ValueError(f"{a.name} and {b.name} both have question {b.first}")


def sections_to_json(sections: list[Section]) -> list[dict]:
    return [asdict(s) for s in sections]


def sections_from_json(data: list[dict]) -> list[Section]:
    """Sections from stored or template JSON. Raises ValueError for anything that isn't a section."""
    try:
        return [Section(str(d["name"]), int(d["first"]), int(d["last"]), float(d["correct"]), float(d["wrong"]),
                        float(d.get("blank", 0)), bool(d.get("partial", False))) for d in data]
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"sections need a name, first and last question, and correct and wrong marks ({e})") from e


def marks_for(questions: list[int], correct: float, wrong: float, blank: float,
              sections: list[Section] = (), single: set[int] | None = None) -> list[tuple[float, float, float, bool, bool]]:
    """(correct, wrong, blank, partial, single) marks for each question, from its section or the exam's marks.

    `single` are the questions printed for one answer only; None means all of them.
    """
    out = []
    for q in questions:
        s = next((s for s in sections if s.first <= q <= s.last), None)
        out.append(((s.correct, s.wrong, s.blank, s.partial) if s else (correct, wrong, blank, False))
                   + (single is None or q in single,))
    return out


def score(answers: list[str], key: list[str], correct: float = 1.0, wrong: float = 0.0, blank: float = 0.0,
          marks: list[tuple] | None = None) -> float:
    """Total marks for one sheet. `wrong` is negative for negative marking, e.g. -1.

    `marks` gives each question its own (correct, wrong, blank, partial, single), from `marks_for`.
    Without `marks` every question is single-answer.
    """
    if len(answers) != len(key):
        raise ValueError(f"sheet has {len(answers)} answers but key has {len(key)}")
    marks = marks or [(correct, wrong, blank, False, True)] * len(key)
    total = 0.0
    for answer, right, (c, w, b, partial, single) in zip(answers, key, marks):
        if single and len(answer) > 1 and len(right) == 1 and right != BONUS:
            continue  # invalid: two bubbles where one answer was asked for earns nothing
        if partial and _part_right(answer, right):
            # shortcut: counted as wrong in right/wrong/blank counts and colours; only the marks are partial
            total += c * len(set(answer)) / len(set(right))
            continue
        total += {"right": c, "wrong": w, "blank": b, "dropped": 0.0}[status(answer, right)]
    return total


def _part_right(answer: str, right: str) -> bool:
    """Some, but not all, of a multi-correct question's options, and no wrong one."""
    return right not in (BONUS, DROPPED) and not right.isdigit() and bool(answer) and set(answer) < set(right)


def full_marks(key: list[str], marks: list[tuple]) -> float:
    """The most a sheet can score: every counted question right."""
    return sum(m[0] for k, m in zip(key, marks) if k != DROPPED)


def status(answer: str, right: str) -> str:
    """"right", "wrong", "blank" or "dropped" for one answer against its key."""
    if right == DROPPED:
        return "dropped"
    if right == BONUS:
        return "right"
    if right.isdigit():
        return "right" if answer.isdigit() and int(answer) == int(right) else "wrong" if answer else "blank"
    if set(answer) == set(right):
        return "right"
    return "wrong" if answer else "blank"


def rank(scores: list[float]) -> list[tuple[int, float]]:
    """(rank, percentile) per score, in input order.

    Ties share a rank (1, 2, 2, 4). Percentile is the share of candidates who
    scored the same or lower, so the top score is 100.
    """
    ordered = sorted(scores, reverse=True)
    n = len(scores)
    return [(ordered.index(s) + 1, 100 * sum(t <= s for t in scores) / n) for s in scores]


def parse_key(text: str, count: int, options: str | list[str]) -> dict[str, list[str]]:
    """Answer keys typed by a person, one per set code; "" is the key for every set.

    Each line is an optional set code and a colon, then the answers in question
    order: "A: ABCDA..." with one letter per question (and a numeric question's
    digits together, "ABC42D"), or separated by spaces or commas when a question
    has more than one correct option ("A, AC, *, -").
    `options` is the option letters of every question, or each question's from
    `Template.answer_options`, where DIGITS marks a numeric question.
    A key shorter than the sheet leaves the rest of the questions out of the
    score (dropped), for papers that use only part of the sheet.
    """
    each = [options] * count if isinstance(options, str) else options
    keys = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        set_code, _, answers = line.rpartition(":")
        set_code = set_code.strip().upper()
        answers = answers.upper().replace(",", " ")
        key = answers.split() if " " in answers.strip() else re.findall(r"\d+|\S", answers)
        if set_code in keys:
            raise ValueError(f"line {n}: a second key for {'set ' + set_code if set_code else 'all sets'}")
        if len(key) > count:
            raise ValueError(f"line {n}: {len(key)} answers, the sheet has {count} questions")
        if not key:
            raise ValueError(f"line {n}: no answers")
        key += [DROPPED] * (count - len(key))
        keys[set_code] = [_checked(a, opts, f"line {n}") for a, opts in zip(key, each)]
    return keys


def _checked(answer: str, options: str, where: str) -> str:
    """A key's answer as kept, or ValueError when it can't answer a question with these options."""
    if answer in (BONUS, DROPPED):
        return answer
    if options == DIGITS:
        if not answer.isdigit():
            raise ValueError(f"{where}: {answer} is not a number, and this question is answered with one")
        return str(int(answer))
    bad = sorted({c for c in answer if c not in options})
    if bad:
        raise ValueError(f"{where}: {', '.join(bad)} is not an option ({options})")
    return answer


def format_key(keys: dict[str, list[str]]) -> str:
    """Keys as the text `parse_key` reads, leaving off the dropped questions at the end."""
    lines = []
    for set_code, key in keys.items():
        key = list(key)
        while key and key[-1] == DROPPED:
            key.pop()
        if not key:
            continue
        answers = ", ".join(key) if any(len(a) > 1 for a in key) else "".join(key)
        lines.append(f"{set_code}: {answers}" if set_code else answers)
    return "\n".join(lines)


def key_from_sheet(answers: dict[int, str], flags: list[tuple[str, str]],
                   questions: list[int]) -> tuple[list[str], list[int]]:
    """The key a filled master sheet gives, and the questions left out for a person to give.

    A question is left out (dropped) when it is blank or flagged on the sheet: an unclear mark, or more than one
    mark where one answer is allowed. The key is never guessed from a doubtful mark.
    """
    doubtful = {int(where[1:]) for where, _ in flags if where.startswith("Q") and where[1:].isdigit()}
    key = [DROPPED if q in doubtful or not answers.get(q) else answers[q] for q in questions]
    return key, [q for q in questions if q in doubtful]


def key_to_csv(keys: dict[str, list[str]], questions: list[int]) -> str:
    """Keys as CSV: set, question, answer; set is empty for the key of every set and answer empty when dropped."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["set", "question", "answer"])
    for set_code, key in keys.items():
        for q, a in zip(questions, key):
            w.writerow([set_code, q, "" if a == DROPPED else a])
    return out.getvalue()


def key_from_csv(text: str, questions: list[int], options: str | list[str]) -> dict[str, list[str]]:
    """Keys from CSV with a header of question and answer columns, and a set column when there are sets.

    Answers are option letters ("B", "AC" or "A;C"), "*" for bonus, and empty or "-" for dropped. Questions
    left out are dropped. Raises ValueError naming the line of anything that can't be used.
    """
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))  # Excel may start the file with a BOM
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("the file is empty")
    header = [c.strip().lower() for c in rows[0]]
    if "question" not in header or "answer" not in header:
        raise ValueError("the first line must name the columns: question, answer (and set when there are sets)")
    qi, ai, si = header.index("question"), header.index("answer"), header.index("set") if "set" in header else None
    place = {q: i for i, q in enumerate(questions)}
    each = [options] * len(questions) if isinstance(options, str) else options
    keys: dict[str, list[str]] = {}
    for n, row in enumerate(rows[1:], 2):
        cell = lambda i: row[i].strip() if i is not None and i < len(row) else ""  # noqa: E731
        set_code = cell(si).upper()
        try:
            q = int(cell(qi))
        except ValueError:
            raise ValueError(f"line {n}: question “{cell(qi)}” is not a number") from None
        if q not in place:
            raise ValueError(f"line {n}: the sheet has no question {q}")
        answer = _checked("".join(cell(ai).upper().replace(";", " ").replace(",", " ").split()) or DROPPED,
                          each[place[q]], f"line {n}")
        if answer not in (BONUS, DROPPED) and not answer.isdigit():
            answer = "".join(sorted(set(answer)))
        key = keys.setdefault(set_code, [DROPPED] * len(questions))
        key[place[q]] = answer
    return keys


def parse_topics(text: str, questions: list[int]) -> dict[int, str]:
    """The topic of each question, from lines like "1-10: Kinematics" or "11: Work and energy".

    A tab works in place of the colon, for two columns pasted from Excel. Questions left out have no topic.
    Raises ValueError naming the line of anything that can't be used.
    """
    topics: dict[int, str] = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        where, sep, topic = line.replace("\t", ":", 1).partition(":")
        first, _, last = where.replace("to", "-").partition("-")
        try:
            first, last = int(first), int(last or first)
        except ValueError:
            raise ValueError(f"line {n}: start with the questions, e.g. 1-10: Kinematics") from None
        if not sep or not topic.strip():
            raise ValueError(f"line {n}: give questions {first} to {last} a topic after a colon")
        if first > last or first not in questions or last not in questions:
            raise ValueError(f"line {n}: the sheet has questions {questions[0]} to {questions[-1]}")
        for q in range(first, last + 1):
            if q in topics:
                raise ValueError(f"line {n}: question {q} already has the topic {topics[q]}")
            topics[q] = topic.strip()
    return topics


def format_topics(topics: dict[int, str]) -> str:
    """Topics as the text `parse_topics` reads, one line per run of questions with the same topic."""
    lines, run = [], []
    for q in sorted(topics):
        if run and (q != run[-1] + 1 or topics[q] != topics[run[0]]):
            lines.append(run)
            run = []
        run.append(q)
    if run:
        lines.append(run)
    return "\n".join(f"{r[0]}-{r[-1]}: {topics[r[0]]}" if len(r) > 1 else f"{r[0]}: {topics[r[0]]}" for r in lines)
