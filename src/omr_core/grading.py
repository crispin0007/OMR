"""Score answered sheets against a key, and rank the results.

Answers and keys are strings of option letters: "B" for one answer, "AC" for
multi-correct, "" for blank. In a key, "*" is a bonus question (everyone gets
the correct marks) and "-" is a dropped question (it counts for nobody).
Sheets reach grading after review, so every answer here is already decided.
"""

BONUS, DROPPED = "*", "-"


def score(answers: list[str], key: list[str], correct: float = 1.0, wrong: float = 0.0, blank: float = 0.0) -> float:
    """Total marks for one sheet. `wrong` is negative for negative marking, e.g. -1."""
    if len(answers) != len(key):
        raise ValueError(f"sheet has {len(answers)} answers but key has {len(key)}")
    marks = {"right": correct, "wrong": wrong, "blank": blank, "dropped": 0.0}
    return sum(marks[status(answer, right)] for answer, right in zip(answers, key))


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
        if len(key) != count:
            raise ValueError(f"line {n}: {len(key)} answers, the sheet has {count} questions")
        bad = sorted({c for a in key if a not in (BONUS, DROPPED) for c in a if c not in options})
        if bad:
            raise ValueError(f"line {n}: {', '.join(bad)} is not an option ({options})")
        keys[set_code] = key
    return keys
