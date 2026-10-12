import os

import cv2
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from omr_app import designer, theme  # noqa: E402
from omr_app.window import TEMPLATES, MainWindow  # noqa: E402
from omr_core.reader import SCALE, read_page  # noqa: E402
from omr_core.template import load, parse  # noqa: E402
from sheets import draw, random_marks, scan  # noqa: E402


@pytest.fixture
def app(tmp_path):
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))  # keep the user's settings out of it
    return QApplication.instance() or QApplication([])


def window(tmp_path) -> MainWindow:
    w = MainWindow(tmp_path / "omr.db")
    w.open_exam(w.store.create_exam("Mock", (TEMPLATES / "test-100.json").read_text(encoding="utf-8")))
    return w


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
    w = window(tmp_path)
    c = w.check
    c.read_files([path])
    cell = lambda col: c.table.item(0, col).text()
    assert (cell(2), cell(4), cell(6)) == (roll, set_code, "")  # no key yet, no score
    key = [answers[q] or "A" for q in c.questions]
    c.key_edit.setPlainText(f"{set_code}: " + "".join(key))
    right = sum(1 for q in c.questions if answers[q])
    assert cell(6) == str(right)
    c.wrong.setValue(-1)
    assert cell(6) == str(right)  # blanks aren't wrong
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
    w = window(tmp_path)
    w.check.read_files([f[0] for f in files] + [str(tmp_path / "blank.png")])  # a page with no marks can't be read
    assert w.check.to_check() == [2]
    assert w.dashboard.to_check.value.text() == "1" and w.dashboard.batches.value.text() == "1"
    w.dashboard.to_check.mousePressEvent(None)
    assert w.stack.currentWidget() is w.review
    w.dashboard.open_clean()
    assert w.stack.currentWidget() is w.check
    assert [w.check.table.isRowHidden(r) for r in range(3)] == [False, False, True]
    w.check.show_sheets(None)
    assert not any(w.check.table.isRowHidden(r) for r in range(3))


def test_exam_is_there_after_reopening(app, tmp_path):
    (path, answers, roll, set_code), = sheet_files(tmp_path, [4])
    w = window(tmp_path)
    w.check.read_files([path])
    w.check.key_edit.setPlainText("".join(answers[q] or "A" for q in w.check.questions))
    w.check.wrong.setValue(-0.25)
    w.close()

    w = MainWindow(tmp_path / "omr.db")  # opens the last exam
    c = w.check
    assert c.exam.name == "Mock" and w.stack.currentWidget() is w.dashboard
    assert c.table.item(0, 2).text() == roll and c.wrong.value() == -0.25
    assert c.table.item(0, 6).text() == str(sum(1 for q in c.questions if answers[q]))
    c.table.selectRow(0)
    assert c.page_view.pixmap() is not None and not c.page_view.pixmap().isNull()  # the page image was saved


def test_first_run_starts_on_exams(app, tmp_path):
    w = MainWindow(tmp_path / "omr.db")
    assert w.check.exam is None and w.stack.currentWidget() is w.exams
    assert not w.check.open_button.isEnabled()


def test_settings_apply_and_are_kept(app, tmp_path):
    w = MainWindow(tmp_path / "omr.db")
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


def test_review_fixes_a_flagged_answer_and_logs_it(app, tmp_path):
    t = load(TEMPLATES / "test-100.json")
    marks, answers, roll, set_code = random_marks(t, 5)
    q_grid = next(i for i, g in enumerate(t.grids) if g.kind == "questions")
    for c in range(4):
        marks.pop((q_grid, 0, c), None)
    marks[q_grid, 0, 2] = "half"  # question 1 half filled: the reader flags it, never guesses
    path = tmp_path / "half.png"
    cv2.imwrite(str(path), scan(draw(t, marks)))
    w = window(tmp_path)
    c = w.check
    c.read_files([str(path)])
    c.key_edit.setPlainText("".join(["C"] + [answers[q] or "A" for q in c.questions[1:]]))
    before = float(c.table.item(0, 6).text())
    w.go("Review")
    assert [item for _, item, _ in w.review.items] == ["Q1"]
    assert w.review.picture.pixmap() is not None and not w.review.picture.pixmap().isNull()
    w.review.fix("Q1", "C")
    assert w.review.items == [] and float(c.table.item(0, 6).text()) == before + 1
    assert w.store.audit(c.exam.id)[0][4:] == ("Q1", "", "C")
    assert w.review.log.count() == 1


def test_results_export_asks_while_marks_wait_for_review(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    files = sheet_files(tmp_path, [1, 2])
    (tmp_path / "blank.png").write_bytes(cv2.imencode(".png", 255 + 0 * cv2.imread(files[0][0]))[1].tobytes())
    w = window(tmp_path)
    w.check.read_files([f[0] for f in files] + [str(tmp_path / "blank.png")])  # the blank page waits for review
    w.check.key_edit.setPlainText("A" * 100)
    assert w.results.table.rowCount() == 2
    out = tmp_path / "merit.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    w.results.excel.click()
    assert not out.exists()  # said no
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w.results.excel.click()
    assert out.exists()


def test_imported_students_show_by_name(app, tmp_path, monkeypatch):
    from openpyxl import Workbook
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    (path, answers, roll, set_code), = sheet_files(tmp_path, [6])
    wb = Workbook()
    wb.active.append(["Roll number", "Name", "Class"])
    wb.active.append([roll, "Asha Rai", "10 A"])
    wb.save(tmp_path / "students.xlsx")
    w = window(tmp_path)
    w.check.read_files([path])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(tmp_path / "students.xlsx"), ""))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    w.exams.table.selectRow(0)
    w.exams.students_button.click()
    assert shown and shown[0].startswith("Imported 1 student into")
    assert w.check.table.item(0, 3).text() == "Asha Rai"
    w.check.key_edit.setPlainText("A" * 100)
    assert w.results.table.item(0, 2).text() == "Asha Rai"


def test_designer_maps_a_sheet_and_saves_a_template(app, tmp_path, monkeypatch):
    t = load(TEMPLATES / "test-100.json")
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), scan(draw(t, {}), angle=0.5))
    w = window(tmp_path)
    w.show()
    w.go("Sheet designer")
    d = w.designer
    d.load_scan(str(blank))
    s = d.gray.shape[1] / t.page[0]
    d.mark_clicked(170 * s, 80 * s)  # blank paper, nowhere near a mark
    assert d.error.text() and not d.marks
    for x, y in t.markers:
        d.mark_clicked(x * s + 5, y * s - 4)
    assert len(d.marks) == 4 and d.canvas.drag_boxes
    for g in t.grids:
        (x0, y0), (x1, y1) = g.centre(0, 0), g.centre(g.rows - 1, g.cols - 1)
        d.canvas.boxed.emit(QRectF((x0 - 4) * SCALE, (y0 - 4) * SCALE, (x1 - x0 + 8) * SCALE, (y1 - y0 + 8) * SCALE))
    assert [b["kind"] for b in d.blocks] == [g.kind for g in t.grids]
    assert [b.get("first") for b in d.blocks] == [None, None, 1, 26, 51, 76]
    assert d.blocks[1]["options"] == "ABCD"

    marks, answers, roll, set_code = random_marks(t, 5)
    filled = tmp_path / "filled.png"
    cv2.imwrite(str(filled), scan(draw(t, marks), seed=5))
    d.load_scan(str(filled))  # a new scan starts the corners again
    assert not d.blocks
    for x, y in t.markers:
        d.mark_clicked(x * s, y * s)
    for g in t.grids:
        (x0, y0), (x1, y1) = g.centre(0, 0), g.centre(g.rows - 1, g.cols - 1)
        d.canvas.boxed.emit(QRectF((x0 - 4) * SCALE, (y0 - 4) * SCALE, (x1 - x0 + 8) * SCALE, (y1 - y0 + 8) * SCALE))
    d.test_read()
    assert f"roll number {roll}, set {set_code}" in d.test_result.text()

    monkeypatch.setattr(designer, "USER_TEMPLATES", tmp_path / "templates")
    monkeypatch.setattr(designer.QFileDialog, "getSaveFileName", lambda _p, _t, path, _f: (path, ""))
    monkeypatch.setattr(designer.QMessageBox, "information", lambda *a: None)
    d.name.setText("My sheet")
    d.save()
    saved = load(tmp_path / "templates" / "My sheet.json")
    result = read_page(scan(draw(t, marks), seed=6), saved)
    assert (result.roll_number, result.set_code, result.answers) == (roll, set_code, answers)


def test_designer_maps_a_barcode(app, tmp_path):
    import json
    d = json.loads((TEMPLATES / "test-100.json").read_text(encoding="utf-8"))
    d["barcode_mm"] = [140, 55, 55, 18]
    t = parse(d)
    marks, answers, roll, set_code = random_marks(t, 8)
    path = tmp_path / "filled.png"
    cv2.imwrite(str(path), scan(draw(t, marks, barcode="2026-0042"), seed=8))
    w = window(tmp_path)
    page = w.designer
    page.load_scan(str(path))
    s = page.gray.shape[1] / t.page[0]
    for x, y in t.markers:
        page.mark_clicked(x * s, y * s)
    for g in t.grids:
        if g.kind != "roll_number":
            (x0, y0), (x1, y1) = g.centre(0, 0), g.centre(g.rows - 1, g.cols - 1)
            page.canvas.boxed.emit(QRectF((x0 - 4) * SCALE, (y0 - 4) * SCALE, (x1 - x0 + 8) * SCALE,
                                          (y1 - y0 + 8) * SCALE))
    page.barcode_button.setChecked(True)
    page.canvas.boxed.emit(QRectF(137 * SCALE, 52 * SCALE, 61 * SCALE, 24 * SCALE))
    assert page.template_dict()["barcode_mm"] == [137, 52, 61, 24]
    page.test_read()
    assert f"roll number 2026-0042, set {set_code}" in page.test_result.text()
