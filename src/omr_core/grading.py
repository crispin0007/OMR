"""Score answered sheets against a key, and rank the results.

Answers and keys are strings of option letters: "B" for one answer, "AC" for
multi-correct, "" for blank. In a key, "*" is a bonus question (everyone gets
the correct marks) and "-" is a dropped question (it counts for nobody).
Sheets reach grading after review, so every answer here is already decided.

Sections give a range of questions its own marks, e.g. 4 right and -1 wrong
for Physics 1 to 50; questions outside every section use the exam's marks.
"""

from dataclasses import asdict, dataclass

BONUS, DROPPED = "*", "-"


@dataclass(frozen=True)
class Section:
    name: str
    first: int  # question numbers, inclusive
    last: int
    correct: float
    wrong: float
    blank: float = 0.0


def check_sections(sections: list[Section], questions: list[int]) -> None:
    """Raises ValueError when a section is empty, off the sheet, or overlaps another."""
    names = set()
    for s in sections:
        if not s.name.strip():
            raise ValueError("every section needs a name")
        if s.name in names:
            raise ValueError(f"two sections are called {s.name}")
        names.add(s.name)
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
    return [Section(**d) for d in data]


def marks_for(questions: list[int], correct: float, wrong: float, blank: float,
              sections: list[Section] = ()) -> list[tuple[float, float, float]]:
    """(correct, wrong, blank) marks for each question, from its section or the exam's marks."""
    out = []
    for q in questions:
        s = next((s for s in sections if s.first <= q <= s.last), None)
        out.append((s.correct, s.wrong, s.blank) if s else (correct, wrong, blank))
    return out


def score(answers: list[str], key: list[str], correct: float = 1.0, wrong: float = 0.0, blank: float = 0.0,
          marks: list[tuple[float, float, float]] | None = None) -> float:
    """Total marks for one sheet. `wrong` is negative for negative marking, e.g. -1.

    `marks` gives each question its own (correct, wrong, blank), from `marks_for`.
    """
    if len(answers) != len(key):
        raise ValueError(f"sheet has {len(answers)} answers but key has {len(key)}")
    marks = marks or [(correct, wrong, blank)] * len(key)
    total = 0.0
    for answer, right, (c, w, b) in zip(answers, key, marks):
        total += {"right": c, "wrong": w, "blank": b, "dropped": 0.0}[status(answer, right)]
    return total


def full_marks(key: list[str], marks: list[tuple[float, float, float]]) -> float:
    """The most a sheet can score: every counted question right."""
    return sum(c for k, (c, _, _) in zip(key, marks) if k != DROPPED)


def status(answer: str, right: str) -> str:
    """"right", "wrong", "blank" or "dropped" for one answer against its key."""
    if right == DROPPED:
        return "dropped"
    if right == BONUS or set(answer) == set(right):
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


def parse_key(text: str, count: int, options: str) -> dict[str, list[str]]:
    """Answer keys typed by a person, one per set code; "" is the key for every set.

    Each line is an optional set code and a colon, then the answers in question
    order: "A: ABCDA..." with one letter per question, or separated by spaces or
    commas when a question has more than one correct option ("A, AC, *, -").
    A key shorter than the sheet leaves the rest of the questions out of the
    score (dropped), for papers that use only part of the sheet.
    """
    keys = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        set_code, _, answers = line.rpartition(":")
        set_code = set_code.strip().upper()
        answers = answers.upper().replace(",", " ")
        key = answers.split() if " " in answers.strip() else list(answers.strip())
        if set_code in keys:
            raise ValueError(f"line {n}: a second key for {'set ' + set_code if set_code else 'all sets'}")
        if len(key) > count:
            raise ValueError(f"line {n}: {len(key)} answers, the sheet has {count} questions")
        if not key:
            raise ValueError(f"line {n}: no answers")
        key += [DROPPED] * (count - len(key))
        bad = sorted({c for a in key if a not in (BONUS, DROPPED) for c in a if c not in options})
        if bad:
            raise ValueError(f"line {n}: {', '.join(bad)} is not an option ({options})")
        keys[set_code] = key
    return keys
