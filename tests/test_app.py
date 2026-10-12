import os

import cv2
import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from omr_app import designer, scanner, theme  # noqa: E402
from omr_app.scan import FOLDER  # noqa: E402
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


class FakeScanner:
    name = "Test scanner"

    def __init__(self, pages, problem=""):
        self.pages_, self.problem = pages, problem

    def pages(self, dpi, duplex):
        assert (dpi, duplex) == (200, True)
        yield from self.pages_
        if self.problem:
            raise scanner.ScanStopped(self.problem)


def run_scan(app, page):
    page.start()
    page.thread.wait()
    for _ in range(5):
        app.processEvents()


def test_scanning_reads_each_page_and_stops_on_a_jam(app, tmp_path, monkeypatch):
    t = load(TEMPLATES / "test-100.json")
    fronts = [random_marks(t, seed) for seed in (1, 2, 3)]
    back = np.full((2339, 1654, 3), 240, np.uint8)
    pages = [p for m in fronts[:2] for p in (scan(draw(t, m[0]), seed=1), back)]
    monkeypatch.setattr(scanner, "scanners", lambda: [FakeScanner(pages, "Paper jam")])
    w = window(tmp_path)
    s = w.scan
    s.find_scanners()
    assert s.source.currentText() == "Test scanner"
    s.duplex.setChecked(True)
    run_scan(app, s)
    assert s.thread is None and "Paper jam" in s.status.text() and fronts[1][2] in s.status.text()
    assert (s.scanned.value.text(), s.read.value.text(), s.skipped.value.text()) == ("4", "2", "2")
    assert [p.result.roll_number for p in w.store.pages(w.check.exam.id)] == [fronts[0][2], fronts[1][2]]
    assert fronts[1][2] in s.latest_text.text()

    # The operator clears the jam and feeds the rest.
    monkeypatch.setattr(scanner, "scanners", lambda: [FakeScanner([scan(draw(t, fronts[2][0]))])])
    s.find_scanners()
    run_scan(app, s)
    assert s.status.text().startswith("Feeder empty") and len(w.store.pages(w.check.exam.id)) == 3


def test_scanning_from_a_folder(app, tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "scanners", lambda: [])
    folder = tmp_path / "scans"
    folder.mkdir()
    files = sheet_files(folder, [5, 6])
    (folder / "broken.png").write_bytes(b"not an image")
    w = window(tmp_path)
    s = w.scan
    s.find_scanners()
    assert s.source.currentText() == FOLDER and "No scanner found" in s.status.text()
    s.folder.setText(str(folder))
    s.start()
    s.poll_folder()  # sizes noted, nothing read yet
    assert s.read.value.text() == "0"
    s.poll_folder()
    assert s.read.value.text() == "2" and "broken.png" in s.status.text()
    s.poll_folder()  # nothing read twice, the broken file isn't retried
    assert len(w.store.pages(w.check.exam.id)) == 2
    assert sorted(p.result.roll_number for p in w.store.pages(w.check.exam.id)) == sorted(f[2] for f in files)
    s.stop()
    assert not s.running


def test_new_sheet_saves_a_template_and_a_pdf(app, tmp_path, monkeypatch):
    import json
    from omr_app import new_sheet
    w = window(tmp_path)
    n = w.new_sheet
    n.name.setText("Weekly test")
    n.questions.setValue(60)
    n.options.setValue(5)
    n.roll.setValue(4)
    n.sets.setCurrentIndex(0)  # no sets
    n.update_preview()
    assert n.template and not n.error.text() and not n.preview.pixmap().isNull()
    assert "60 questions" in n.summary.text()

    n.add_section()
    n.add_section()
    n.sections.item(0, 0).setText("Part A")
    n.sections.item(0, 1).setText("40")
    n.sections.item(1, 2).setText("2")
    n.update_preview()
    assert n.questions.value() == 50 and not n.questions.isEnabled()  # 40 + the new section's 10

    monkeypatch.setattr(new_sheet, "USER_TEMPLATES", tmp_path / "templates")
    monkeypatch.setattr(new_sheet.QMessageBox, "information", lambda *a: None)
    monkeypatch.setattr(new_sheet.QFileDialog, "getSaveFileName", lambda *a: (str(tmp_path / "sheet.pdf"), ""))
    n.save_template()
    n.save_pdf()
    saved = tmp_path / "templates" / "Weekly test.json"
    assert (tmp_path / "sheet.pdf").read_bytes().startswith(b"%PDF")
    exam = w.store.exam(w.store.create_exam("Week 1", saved.read_text(encoding="utf-8")))
    assert [(s.name, s.first, s.last, s.correct) for s in exam.sections] == [("Part A", 1, 40, 1), ("Section 2", 41, 50, 2)]
    assert json.loads(saved.read_text())["grids"][0]["kind"] == "roll_number"

    n.sections.item(1, 1).setText("ten")
    n.update_preview()
    assert "whole number" in n.error.text() and n.template is None
