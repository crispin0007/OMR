import json

import cv2
import numpy as np
import pytest

from omr_core.names import as_text, matches, suggest
from omr_core.reader import read_page
from omr_core.sheet import SheetSpec, layout, render
from omr_core.students import Student
from omr_core.template import parse
from sheets import fill

DPI = 200


def write_name(page: np.ndarray, t, words: list[str]) -> np.ndarray:
    """Block capitals in the name boxes, one a box, like a student writes them."""
    px = DPI / 25.4
    for word, boxes in zip(words, t.names):
        for letter, (x, y, w, h) in zip(word, boxes):
            size, _ = cv2.getTextSize(letter, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 3)
            cv2.putText(page, letter, (round((x + w / 2) * px - size[0] / 2), round((y + h * 0.8) * px)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 40, 40), 3, cv2.LINE_AA)
    return page


def test_the_name_written_is_read_and_matched_to_the_directory():
    d = layout(SheetSpec("Names", 20, roll_digits=3, sets=0))
    t = parse(d)
    assert len(t.names) == 3 and all(len(w) == 12 for w in t.names)
    page = write_name(fill(render(d), t, {}), t, ["ASHA", "", "RAI"])
    r = read_page(page, t)
    text = as_text(r.name)
    assert [len(w) for w in text.split()] == [4, 3]  # two words, every letter found, the empty boxes left out
    students = [Student("101", "Bikash Lama"), Student("102", "Asha Rai"), Student("103", "Sita Rai"),
                Student("104", "Asmita Shah"), Student("105", "Ramesh Thapa")]
    assert suggest(r.name, students).name == "Asha Rai"
    assert suggest(r.name, students, "10?").name == "Asha Rai"
    assert suggest(r.name, students, "101") is None  # only Bikash Lama fits that roll number, and not the writing
    assert suggest(read_page(fill(render(d), t, {}), t).name, students) is None  # nothing written


def test_roll_numbers_with_unclear_digits_match_the_directory():
    assert matches("162", "0016?") and matches("00162", "0016?") and not matches("172", "0016?")
    assert matches("123", "00123") and not matches("123", "1?3?")


def test_sheets_made_here_before_have_their_name_boxes_too():
    d = layout(SheetSpec("Old", 20, roll_digits=3, sets=0))
    boxes = d.pop("name_boxes_mm")
    assert [list(map(list, w)) for w in parse(d).names] == boxes
    del d["print"]
    assert parse(d).names == ()  # a sheet from elsewhere: no name boxes known
    with pytest.raises(ValueError):
        parse({**json.loads(json.dumps(d)), "name_boxes_mm": [[[500, 30, 4, 5]]]})
