import csv
from pathlib import Path

import cv2

from omr_core.cli import main
from omr_core.template import load
from sheets import draw, random_marks, scan

TEMPLATE = Path(__file__).parent.parent / "templates" / "test-100.json"


def test_reads_files_and_writes_csv(tmp_path, capsys):
    t = load(TEMPLATE)
    marks, answers, roll, set_code = random_marks(t, 12)
    image = tmp_path / "sheet.png"
    cv2.imwrite(str(image), scan(draw(t, marks)))
    (tmp_path / "broken.pdf").write_bytes(b"nope")
    out = tmp_path / "results.csv"
    code = main([str(TEMPLATE), str(image), str(tmp_path / "broken.pdf"), "--csv", str(out)])
    assert code == 1  # the broken file is reported, the good one still read
    assert f"roll {roll}  set {set_code}" in capsys.readouterr().out
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 1 and rows[0]["roll_number"] == roll
    assert all(rows[0][f"Q{q}"] == a for q, a in answers.items())
