import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from omr_core.reader import UnreadablePage, read_page
from omr_core.sources import read_pages
from omr_core.template import load, parse
from sheets import draw, random_marks, scan

TEMPLATE = load(Path(__file__).parent.parent / "templates" / "test-100.json")


@pytest.mark.parametrize("seed, angle, upside_down", [
    (1, 0, False), (2, 2.5, False), (3, -5, False), (4, 0, True), (5, 4, True), (6, -1.5, False),
])
def test_reads_every_bubble_on_skewed_and_flipped_scans(seed, angle, upside_down):
    marks, answers, roll, set_code = random_marks(TEMPLATE, seed)
    r = read_page(scan(draw(TEMPLATE, marks), angle, upside_down, seed=seed), TEMPLATE)
    assert (r.answers, r.roll_number, r.set_code, r.flags) == (answers, roll, set_code, [])


def test_pencil_reads_like_pen():
    marks, answers, _, _ = random_marks(TEMPLATE, 7)
    marks = {k: "pencil" for k in marks}
    r = read_page(scan(draw(TEMPLATE, marks)), TEMPLATE)
    assert r.answers == answers and r.flags == []


def test_problems_are_flagged_not_guessed():
    marks, _, _, _ = random_marks(TEMPLATE, 8)
    q = TEMPLATE.grids[2]  # questions 1 to 25
    for c in range(4):
        marks.pop((2, 0, c), None), marks.pop((2, 1, c), None), marks.pop((2, 2, c), None)
    marks[2, 0, 0] = marks[2, 0, 2] = "pen"  # Q1: two answers
    marks[2, 1, 1] = "half"  # Q2: half filled
    for d in range(10):
        marks.pop((0, d, 0), None)  # first roll digit left blank
    r = read_page(scan(draw(TEMPLATE, marks)), TEMPLATE)
    assert q.first == 1 and r.answers[1] == "AC" and r.answers[3] == ""
    assert ("Q1", "multiple marks") in r.flags
    assert ("Q2", "unclear mark") in r.flags
    assert ("roll number digit 1", "blank") in r.flags and r.roll_number[0] == "?"


def test_blank_sheet_reads_blank():
    r = read_page(scan(draw(TEMPLATE, {})), TEMPLATE)
    assert set(r.answers.values()) == {""}


def test_red_dropout_ignores_pink_print():
    t = parse({**_raw(), "dropout": "red"})
    marks, answers, _, _ = random_marks(t, 9)
    page = draw(t, marks, print_bgr=(180, 150, 255))  # pink bubbles, black pen
    assert read_page(scan(page), t).answers == answers


def test_page_without_markers_is_unreadable():
    with pytest.raises(UnreadablePage):
        read_page(np.full((2339, 1654, 3), 255, np.uint8), TEMPLATE)


def test_page_reads_in_under_0_3_seconds():
    marks, _, _, _ = random_marks(TEMPLATE, 10)
    page = scan(draw(TEMPLATE, marks), 2)
    read_page(page, TEMPLATE)  # warm up
    start = time.perf_counter()
    for _ in range(5):
        read_page(page, TEMPLATE)
    assert (time.perf_counter() - start) / 5 < 0.3


def test_reads_pages_from_pdf_and_tiff(tmp_path):
    marks, answers, _, _ = random_marks(TEMPLATE, 11)
    page = scan(draw(TEMPLATE, marks))
    tiff = tmp_path / "pages.tiff"
    assert cv2.imwritemulti(str(tiff), [page, page])
    pdf = tmp_path / "pages.pdf"
    _write_pdf(pdf, page)
    for path, count in ((tiff, 2), (pdf, 1)):
        pages = list(read_pages(path))
        assert len(pages) == count
        assert all(read_page(p, TEMPLATE).answers == answers for p in pages)


def test_bad_files_raise_value_error(tmp_path):
    for name, data in (("broken.pdf", b"not a pdf"), ("broken.png", b"nope"), ("notes.txt", b"hi")):
        (tmp_path / name).write_bytes(data)
        with pytest.raises(ValueError):
            list(read_pages(tmp_path / name))


def _raw():
    import json
    return json.loads((Path(__file__).parent.parent / "templates" / "test-100.json").read_text())


def _write_pdf(path, bgr):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    ok, jpg = cv2.imencode(".jpg", bgr)
    jpg_path = path.with_suffix(".jpg")
    jpg_path.write_bytes(jpg.tobytes())
    pdf = pdfium.PdfDocument.new()
    w, h = 210 / 25.4 * 72, 297 / 25.4 * 72
    page = pdf.new_page(w, h)
    image = pdfium.PdfImage.new(pdf)
    with open(jpg_path, "rb") as f:
        image.load_jpeg(f, inline=True)
    image.set_matrix(pdfium.PdfMatrix().scale(w, h))
    page.insert_obj(image)
    page.gen_content()
    pdf.save(path)
