import pytest

from omr_core.grading import parse_key, rank, score


def test_score_plain_mcq():
    assert score(["A", "B", "C"], ["A", "C", "C"]) == 2


def test_score_negative_marking_and_blank():
    # +4 correct, -1 wrong, 0 blank
    assert score(["A", "B", ""], ["A", "C", "D"], correct=4, wrong=-1) == 3


def test_score_multi_correct_needs_exact_set():
    assert score(["CA", "A"], ["AC", "AC"]) == 1


def test_score_bonus_and_dropped():
    assert score(["", "B", "A"], ["*", "-", "A"], correct=4, wrong=-1) == 8


def test_score_rejects_length_mismatch():
    with pytest.raises(ValueError):
        score(["A"], ["A", "B"])


def test_rank_ties_share_rank():
    assert rank([50, 80, 80, 20]) == [(3, 50.0), (1, 100.0), (1, 100.0), (4, 25.0)]


def test_parse_key_letters_and_sets():
    assert parse_key("ABCD", 4, "ABCD") == {"": ["A", "B", "C", "D"]}
    assert parse_key("a: ab*-\nB: dcba", 4, "ABCD") == {"A": ["A", "B", "*", "-"], "B": ["D", "C", "B", "A"]}


def test_parse_key_multi_correct_needs_separators():
    assert parse_key("A, AC, *, -", 4, "ABCD") == {"": ["A", "AC", "*", "-"]}


@pytest.mark.parametrize("text", ["ABC", "ABCE", "A: ABCD\nA: ABCD"])
def test_parse_key_rejects_bad_keys(text):
    with pytest.raises(ValueError):
        parse_key(text, 4, "ABCD")
