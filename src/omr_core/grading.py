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
    total = 0.0
    for answer, right in zip(answers, key):
        if right == DROPPED:
            continue
        if right == BONUS or set(answer) == set(right):
            total += correct
        elif answer:
            total += wrong
        else:
            total += blank
    return total


def rank(scores: list[float]) -> list[tuple[int, float]]:
    """(rank, percentile) per score, in input order.

    Ties share a rank (1, 2, 2, 4). Percentile is the share of candidates who
    scored the same or lower, so the top score is 100.
    """
    ordered = sorted(scores, reverse=True)
    n = len(scores)
    return [(ordered.index(s) + 1, 100 * sum(t <= s for t in scores) / n) for s in scores]
