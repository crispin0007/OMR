from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from omr_core.parallel import PageReader
from omr_core.reader import read_or_reason
from omr_core.template import load
from sheets import draw, random_marks, scan

TEMPLATES = Path(__file__).parent.parent / "templates"


def test_pages_read_on_other_cores_come_back_in_order_and_the_same(tmp_path):
    t = load(TEMPLATES / "test-100.json")
    pages = [scan(draw(t, random_marks(t, seed)[0]), seed=seed) for seed in range(4)]
    files = []
    for i, page in enumerate(pages[:2]):
        files.append(tmp_path / f"{i}.png")
        cv2.imwrite(str(files[-1]), page)
    Image.fromarray(pages[2][:, :, ::-1]).save(tmp_path / "two.pdf", save_all=True, resolution=200,
                                                append_images=[Image.fromarray(pages[3][:, :, ::-1])])
    (tmp_path / "bad.png").write_bytes(b"not an image")
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((2339, 1654, 3), 255, np.uint8))
    files += [tmp_path / "two.pdf", tmp_path / "bad.png", blank]

    reader = PageReader(t, skip_blank=True, workers=2)
    assert reader.pool is not None
    for f in files:
        reader.add(str(f))
    got = []
    while reader.busy:
        r = reader.next(timeout=1)
        if r:
            got.append(r)
    reader.close()
    assert [Path(p).name for p, _ in got] == ["0.png", "1.png", "two.pdf", "two.pdf", "bad.png", "blank.png"]
    assert "can't read image" in got[4][1]
    assert [(n, b, r) for n, _, b, r in got[5][1]] == [(1, True, None)]  # a blank back is skipped, not read
    read = [x for _, pages in got[:4] for x in pages]
    assert [n for n, *_ in read] == [1, 1, 1, 2]
    for (n, page, blank, (result, problem)), want in zip(read, pages):
        mine, _ = read_or_reason(want, t)
        assert not blank and not problem
        assert result.roll_number == mine.roll_number and result.answers == mine.answers


def test_stopping_says_which_files_were_not_finished(tmp_path):
    t = load(TEMPLATES / "test-100.json")
    paths = []
    for i in range(3):
        paths.append(str(tmp_path / f"{i}.png"))
        cv2.imwrite(paths[-1], scan(draw(t, random_marks(t, i)[0]), seed=i))
    reader = PageReader(t, skip_blank=False, workers=1)
    for p in paths:
        reader.add(p)
    assert reader.next()[0] == paths[0]
    assert reader.stop() == set(paths[1:]) and not reader.busy


def test_pages_are_read_here_when_the_readers_cant_start_or_die(tmp_path):
    t = load(TEMPLATES / "test-100.json")
    paths = []
    for i in range(3):
        paths.append(str(tmp_path / f"{i}.png"))
        cv2.imwrite(paths[-1], scan(draw(t, random_marks(t, i)[0]), seed=i))

    class Broken:
        def __init__(self):
            self.calls = 0

        def submit(self, *a):
            from concurrent.futures import Future
            from concurrent.futures.process import BrokenProcessPool
            self.calls += 1
            if self.calls > 1:
                raise BrokenProcessPool("a reader died")
            f = Future()
            f.set_exception(BrokenProcessPool("a reader died"))
            return f

        def shutdown(self, **k):
            pass
    reader = PageReader(t, skip_blank=False, workers=1)
    reader.pool = Broken()
    for p in paths:
        reader.add(p)
    got = []
    while reader.busy:
        got.append(reader.next(timeout=1))
    assert [p for p, _ in got] == paths and all(pages[0][3][0] is not None for _, pages in got)
