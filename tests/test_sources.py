from pathlib import Path

import cv2
import numpy as np

from omr_core.sources import is_blank, ready_files
from omr_core.template import load
from sheets import draw, scan

TEMPLATES = Path(__file__).parent.parent / "templates"


def test_blank_backs_are_blank_and_sheets_are_not():
    t = load(TEMPLATES / "test-100.json")
    assert not is_blank(scan(draw(t, {})))
    back = np.full((2339, 1654, 3), 236, np.uint8)  # off-white paper
    assert is_blank(scan(back, seed=4))
    cv2.putText(back, "page 2", (200, 300), cv2.FONT_HERSHEY_SIMPLEX, 6, (0, 0, 0), 12)
    assert not is_blank(back)  # something written on the back is kept, not skipped


def test_ready_files_waits_until_a_file_stops_growing(tmp_path):
    sizes = {}
    (tmp_path / "notes.txt").write_text("x")
    scan1 = tmp_path / "scan1.png"
    scan1.write_bytes(b"12")
    assert ready_files(tmp_path, set(), sizes) == []  # just appeared
    scan1.write_bytes(b"1234")
    assert ready_files(tmp_path, set(), sizes) == []  # still growing
    assert ready_files(tmp_path, set(), sizes) == [scan1]
    assert ready_files(tmp_path, {str(scan1)}, sizes) == []  # already read
