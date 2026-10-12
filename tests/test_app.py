import os

import cv2
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from omr_app.window import TEMPLATES, MainWindow  # noqa: E402
from omr_core.template import load  # noqa: E402
from sheets import draw, random_marks, scan  # noqa: E402


def test_reads_sheets_and_scores_them(tmp_path):
    app = QApplication.instance() or QApplication([])
    t = load(TEMPLATES / "test-100.json")
    marks, answers, roll, set_code = random_marks(t, 3)
    image = tmp_path / "sheet.png"
    cv2.imwrite(str(image), scan(draw(t, marks)))
    w = MainWindow()
    w.read_files([str(image)])
    cell = lambda col: w.table.item(0, col).text()
    assert (cell(2), cell(3), cell(5)) == (roll, set_code, "")  # no key yet, no score
    key = [answers[q] or "A" for q in w.questions]
    w.key_edit.setPlainText(f"{set_code}: " + "".join(key))
    assert cell(5) == str(sum(1 for q in w.questions if answers[q]))
    w.wrong.setValue(-1)
    assert cell(5) == str(sum(1 for q in w.questions if answers[q]))  # blanks aren't wrong
    w.table.selectRow(0)
    assert w.review_list.item(0).text() == "Nothing to check"
    app.processEvents()
