import pytest

from omr_core.grading import Section, check_sections, full_marks, marks_for, parse_key, rank, score


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


@pytest.mark.parametrize("text", ["ABCDA", "ABCE", "A: ABCD\nA: ABCD", "A:"])
def test_parse_key_rejects_bad_keys(text):
    with pytest.raises(ValueError):
        parse_key(text, 4, "ABCD")


def test_a_short_key_drops_the_rest():
    assert parse_key("AB", 4, "ABCD") == {"": ["A", "B", "-", "-"]}
    key = parse_key("AB", 4, "ABCD")[""]
    assert score(["A", "C", "B", ""], key, correct=4, wrong=-1) == 3  # Q3 and Q4 count for nobody
    assert full_marks(key, [(4, -1, 0)] * 4) == 8


def test_sections_have_their_own_marks():
    physics, maths = Section("Physics", 1, 2, 4, -1), Section("Maths", 3, 3, 3, -1)
    marks = marks_for([1, 2, 3, 4], 1, 0, 0, [physics, maths])
    assert marks == [(4, -1, 0), (4, -1, 0), (3, -1, 0), (1, 0, 0)]  # Q4 is in no section
    assert score(["A", "B", "C", "D"], ["A", "A", "C", "A"], marks=marks) == 4 - 1 + 3 + 0
    assert full_marks(["A", "A", "C", "-"], marks) == 11


@pytest.mark.parametrize("sections", [
    [Section("P", 1, 3, 4, -1), Section("C", 3, 4, 4, -1)],  # overlap
    [Section("P", 3, 1, 4, -1)],
    [Section("P", 1, 9, 4, -1)],  # off the sheet
    [Section("", 1, 2, 4, -1)],
    [Section("P", 1, 2, 4, -1), Section("P", 3, 4, 4, -1)],
])
def test_bad_sections_are_refused(sections):
    with pytest.raises(ValueError):
        check_sections(sections, [1, 2, 3, 4])
