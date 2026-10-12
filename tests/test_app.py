import os

import cv2
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from omr_app import theme  # noqa: E402
from omr_app.window import TEMPLATES, MainWindow  # noqa: E402
from omr_core.template import load  # noqa: E402
from sheets import draw, random_marks, scan  # noqa: E402


@pytest.fixture
def app(tmp_path):
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))  # keep the user's settings out of it
    return QApplication.instance() or QApplication([])


def sheet_files(tmp_path, seeds):
    t = load(TEMPLATES / "test-100.json")
    out = []
    for seed in seeds:
        marks, answers, roll, set_code = random_marks(t, seed)
        path = tmp_path / f"sheet{seed}.png"
        cv2.imwrite(str(path), scan(draw(t, marks), seed=seed))
        out.append((str(path), answers, roll, set_code))
    return out


def test_reads_sheets_and_scores_them(app, tmp_path):
    (path, answers, roll, set_code), = sheet_files(tmp_path, [3])
    w = MainWindow()
    c = w.check
    c.read_files([path])
    cell = lambda col: c.table.item(0, col).text()
    assert (cell(2), cell(3), cell(5)) == (roll, set_code, "")  # no key yet, no score
    key = [answers[q] or "A" for q in c.questions]
    c.key_edit.setPlainText(f"{set_code}: " + "".join(key))
    right = sum(1 for q in c.questions if answers[q])
    assert cell(5) == str(right)
    c.wrong.setValue(-1)
    assert cell(5) == str(right)  # blanks aren't wrong
    c.table.selectRow(0)
    assert c.review_list.item(0).text() == "Nothing to check"
    assert w.dashboard.read.value.text() == "1" and w.dashboard.average.value.text() == f"{right:.1f}"
    assert w.results.table.item(0, 1).text() == roll
    assert w.results.table.item(0, 0).text() == "1"
    w.show()
    for page in ("Dashboard", "Check sheets", "Results", "Settings"):  # every page paints without errors
        w.go(page)
        assert not w.grab().isNull()


def test_dashboard_opens_the_sheets_behind_it(app, tmp_path):
    files = sheet_files(tmp_path, [1, 2])
    (tmp_path / "blank.png").write_bytes(cv2.imencode(".png", 255 + 0 * cv2.imread(files[0][0]))[1].tobytes())
    w = MainWindow()
    w.check.read_files([f[0] for f in files] + [str(tmp_path / "blank.png")])  # a page with no marks can't be read
    assert w.check.to_check() == [2]
    assert w.dashboard.to_check.value.text() == "1" and w.dashboard.batches.value.text() == "1"
    w.dashboard.to_check.mousePressEvent(None)
    assert w.stack.currentWidget() is w.check
    assert [w.check.table.isRowHidden(r) for r in range(3)] == [True, True, False]
    w.check.show_sheets(None)
    assert not any(w.check.table.isRowHidden(r) for r in range(3))


def test_settings_apply_and_are_kept(app):
    w = MainWindow()
    w.settings.theme.setCurrentText("Dark")
    w.settings._set(accent="#123456")
    w.settings.font.setCurrentText("Large")
    assert theme.tokens()["bg"] == theme.DARK["bg"] and theme.tokens()["accent"] == "#123456"
    assert theme.load_prefs() == theme.Prefs("Dark", "#123456", "Large", "Comfortable")
    w.toggle_theme()
    assert theme.load_prefs().theme == "Light" and theme.tokens()["bg"] == theme.LIGHT["bg"]


def test_bad_saved_settings_fall_back_to_defaults(app):
    s = QSettings(QSettings.IniFormat, QSettings.UserScope, "OMR", "OMR")
    for k, v in {"theme": "Neon", "accent": "not a colour", "font": "Huge", "density": 3}.items():
        s.setValue(k, v)
    s.sync()
    assert theme.load_prefs() == theme.Prefs()
