import json
from pathlib import Path

import cv2
import pytest

from omr_core.designer import align, find_bubbles, fit_grid, marker_at
from omr_core.reader import _markers_near, read_page
from omr_core.template import load, parse
from sheets import draw, random_marks, scan

TEMPLATES = Path(__file__).parent.parent / "templates"
FIXTURES = Path(__file__).parent / "fixtures"


def map_sheet(gray, t, clicks_px, marks_mm=None):
    """What the designer does: refine the clicked marks, align, then fit each grid from a box around it.

    The boxes come from the known template, so `marks_mm` can pin the frame to it.
    """
    px_per_mm = gray.shape[1] / t.page[0]  # the scan covers the whole page
    marks = [marker_at(gray, x, y, px_per_mm) for x, y in clicks_px]
    assert all(marks)
    marks_mm = marks_mm or [(m[0] / px_per_mm, m[1] / px_per_mm) for m in marks]
    aligned = align(gray, [m[:2] for m in marks], marks_mm, t.page)
    grids = []
    for g in t.grids:
        (x0, y0), (x1, y1) = g.centre(0, 0), g.centre(g.rows - 1, g.cols - 1)
        centres, size = find_bubbles(aligned, (x0 - 4, y0 - 4, x1 + 4, y1 + 4))
        grids.append(fit_grid(centres, size))
    return marks, marks_mm, grids, size


def test_maps_a_scanned_blank_sheet_to_its_template():
    t = load(TEMPLATES / "test-100.json")
    blank = scan(draw(t, {}), angle=0.6)
    gray = cv2.cvtColor(blank, cv2.COLOR_BGR2GRAY)
    s = gray.shape[1] / t.page[0]
    clicks = [(x * s + 6, y * s - 5) for x, y in t.markers]  # a person clicks near, not on, the centre
    marks, marks_mm, grids, size = map_sheet(gray, t, clicks)
    assert all(m[3] == "square" for m in marks)
    assert all(abs(m[2] / s - t.marker_size) < 1 for m in marks)
    for (origin, pitch, rows, cols), g in zip(grids, t.grids):
        assert (rows, cols) == (g.rows, g.cols)
        # The mapped frame comes from the skewed scan's marks, so positions move a little; reading below is the test.
        assert abs(origin[0] - g.origin[0]) < 2 and abs(origin[1] - g.origin[1]) < 2
        assert abs(pitch[0] - g.pitch[0]) < 0.1 and abs(pitch[1] - g.pitch[1]) < 0.1
    assert abs(size[0] - t.bubble[0]) < 0.6 and abs(size[1] - t.bubble[1]) < 0.6

    # A template built from what was found reads filled sheets correctly.
    d = json.loads((TEMPLATES / "test-100.json").read_text())
    d.pop("orientation_mm")
    d["markers"]["centres_mm"] = [list(m) for m in marks_mm]
    for gd, (origin, pitch, _, _) in zip(d["grids"], grids):
        gd["origin_mm"], gd["pitch_mm"] = list(origin), list(pitch)
    mapped = parse(d)
    marks_drawn, answers, roll, set_code = random_marks(t, 11)
    result = read_page(scan(draw(t, marks_drawn), angle=-0.4), mapped)
    assert (result.roll_number, result.set_code) == (roll, set_code)
    assert result.answers == answers and not result.flags


def test_no_grid_in_an_empty_box():
    t = load(TEMPLATES / "test-100.json")
    gray = cv2.cvtColor(draw(t, {}), cv2.COLOR_BGR2GRAY)
    aligned = align(gray, [(m[0] * 200 / 25.4, m[1] * 200 / 25.4) for m in t.markers], list(t.markers), t.page)
    centres, _ = find_bubbles(aligned, (150, 60, 200, 100))  # blank paper
    with pytest.raises(ValueError):
        fit_grid(centres, (4, 3))


def test_maps_the_private_sample_sheet():
    folder = FIXTURES / "private-sample-200q"
    if not (folder / "photocopy.png").exists():
        pytest.skip("private sample not available")
    t = load(folder / "sample-200q.json")
    gray = cv2.imread(str(folder / "photocopy.png"), cv2.IMREAD_GRAYSCALE)
    marks, marks_mm, grids, size = map_sheet(gray, t, _markers_near(gray, t), list(t.markers))  # stands in for clicks
    assert all(m[3] == "ring" for m in marks)
    d = json.loads((folder / "sample-200q.json").read_text())
    d["bubble_mm"] = list(size)
    for gd, (origin, pitch, rows, cols), g in zip(d["grids"], grids, t.grids):
        assert (rows, cols) == (g.rows, g.cols), g.kind
        gd["origin_mm"], gd["pitch_mm"] = list(origin), list(pitch)
    want = json.loads((folder / "expected.json").read_text())["sheets"]["photocopy.png"]
    r = read_page(cv2.imread(str(folder / "photocopy.png")), parse(d))
    assert (r.roll_number, r.set_code, r.flags) == (want["roll_number"], want["set_code"], [])
    assert {str(q): a for q, a in r.answers.items() if a} == want["answers"]
