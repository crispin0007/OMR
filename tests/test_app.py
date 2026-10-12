import os

import cv2
import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

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
    for page in ["Dashboard", "Exams", "Map printed sheet", "Settings", *w.exam_page.names]:  # every page paints
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
    assert w.showing() is w.review
    w.dashboard.open_clean()
    assert w.showing() is w.check
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
    assert c.exam.name == "Mock" and w.showing() is w.dashboard
    assert c.table.item(0, 2).text() == roll and c.wrong.value() == -0.25
    assert c.table.item(0, 6).text() == str(sum(1 for q in c.questions if answers[q]))
    c.table.selectRow(0)
    assert c.page_view.pixmap() is not None and not c.page_view.pixmap().isNull()  # the page image was saved


def test_first_run_starts_on_exams(app, tmp_path):
    w = MainWindow(tmp_path / "omr.db")
    assert w.check.exam is None and w.showing() is w.exams
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
    w.students.import_button.click()
    assert shown and shown[0].startswith("Imported 1 student into")
    assert w.check.table.item(0, 3).text() == "Asha Rai" and w.students.table.item(0, 1).text() == "Asha Rai"
    w.check.key_edit.setPlainText("A" * 100)
    assert w.results.table.item(0, 2).text() == "Asha Rai"


def test_designer_maps_a_sheet_and_saves_a_template(app, tmp_path, monkeypatch):
    t = load(TEMPLATES / "test-100.json")
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), scan(draw(t, {}), angle=0.5))
    w = window(tmp_path)
    w.show()
    w.go("Map printed sheet")
    d = w.designer
    assert d.intro.isVisible() and not d.split.isVisible()  # says what the page is for, and points to New exam
    from omr_app import exams
    monkeypatch.setattr(exams.NewExamWizard, "exec", lambda self: False)
    d.new_exam_wanted.emit()
    assert w.showing() is w.exams
    w.go("Map printed sheet")
    d.load_scan(str(blank))
    assert not d.intro.isVisible() and d.split.isVisible()
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
    assert w.check.table.rowCount() == 2 and w.check.table.item(1, 2).text() == fronts[1][2]  # shown on stopping

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


def test_new_exam_wizard_makes_the_exam_and_its_sheet(app, tmp_path, monkeypatch):
    import json
    from omr_app import exams, new_exam
    w = MainWindow(tmp_path / "omr.db")
    logo = tmp_path / "logo.png"
    cv2.imwrite(str(logo), np.full((30, 90, 3), (0, 120, 0), np.uint8))
    monkeypatch.setattr(new_exam.QFileDialog, "getOpenFileName", lambda *a: (str(logo), ""))

    def fill(z):
        assert z.next.text() == "Next" and not z.back.isEnabled()
        z.forward()  # Start: make the sheet for me
        z.forward()
        assert z.error.text() == "Give the exam a name"
        z.name.setText("Weekly test")
        z.class_name.setText("Class 10")
        z.minutes.setValue(60)
        z.forward()
        z.add_section()
        z.add_section()
        z.sections.item(0, 0).setText("Physics")
        z.sections.item(0, 1).setText("20")
        z.sections.item(1, 0).setText("Physics")
        assert z.sections.item(1, 2).text() == "21 to 45" and z.total.value() == 45
        z.forward()
        assert "own name" in z.error.text()
        z.sections.item(1, 0).setText("Chemistry")
        z.forward()
        z.options.setValue(5)
        z.roll.setValue(4)
        z.sets.setCurrentIndex(0)  # no sets
        z.forward()
        assert z.section_marks.rowCount() == 2
        z.section_marks.cellWidget(0, 1).setValue(4)
        z.section_marks.cellWidget(0, 2).setValue(-1)
        z.section_marks.item(1, 3).setCheckState(Qt.Checked)
        z.forward()
        z.colour.setCurrentIndex(z.colour.findText("Blue"))
        z.choose_logo()
        z.forward()
        assert z.next.text() == "Create exam" and "45 questions, 5 options each" in z.summary.text()
        assert "Chemistry: 25 questions, 1 right, 0 wrong, partial marking" in z.summary.text()
        z.forward()
        return z.result()

    monkeypatch.setattr(exams.NewExamWizard, "exec", fill)
    w.exams.new_exam()
    exam = w.check.exam
    assert exam.name == "Weekly test" and w.showing() is w.print_sheet and w.print_sheet.save.isEnabled()
    assert exam.details["class"] == "Class 10" and exam.details["minutes"] == 60
    assert "Class 10" in w.exam_page.about.text() and "60 minutes" in w.exam_page.about.text()
    assert [(s.name, s.first, s.last, s.correct, s.wrong, s.partial) for s in exam.sections] == [
        ("Physics", 1, 20, 4, -1, False), ("Chemistry", 21, 45, 1, 0, True)]
    t = json.loads(exam.template_json)
    assert t["print"]["colour"] == "#1565c0" and t["print"]["logo_jpeg"]
    assert [g.get("multi", False) for g in t["grids"] if g["kind"] == "questions"][-1]

    def own(z):
        z.own_sheet.setChecked(True)
        z.template_path = ""
        z.forward()
        assert "template" in z.error.text()
        z.template_path = str(TEMPLATES / "test-100.json")
        z.forward()
        z.name.setText("Printed one")
        z.forward()
        assert STEP(z) == "Marking" and z.section_marks.isHidden()
        z.correct.setValue(2)
        z.wrong.setValue(-0.5)
        z.forward()
        assert STEP(z) == "Review and create" and "Your printed sheet" in z.summary.text()
        z.forward()
        return z.result()

    STEP = lambda z: new_exam.STEPS[z.steps.currentIndex()]  # noqa: E731
    monkeypatch.setattr(exams.NewExamWizard, "exec", own)
    w.exams.new_exam()
    assert w.check.exam.name == "Printed one" and w.showing() is w.scan
    e = w.check.exam
    assert (e.correct, e.wrong, e.blank, e.details["minutes"]) == (2, -0.5, 0, 90)


def test_new_exam_wizard_true_false_and_layout_problems(app, tmp_path):
    import json
    from omr_app.new_exam import NewExamWizard
    w = MainWindow(tmp_path / "omr.db")
    z = NewExamWizard(w, w.store)
    z.name.setText("Quick quiz")
    z.true_false.setChecked(True)
    z.total.setValue(20)
    z.roll.setValue(0)
    z.update_preview()
    assert z.options.value() == 2 and not z.options.isEnabled() and z.made
    assert {g["options"] for g in z.made["grids"] if g["kind"] == "questions"} == {"TF"}
    z.total.setValue(300)
    z.options.setEnabled(True)
    z.true_false.setChecked(False)
    z.options.setValue(8)
    z.update_preview()
    assert z.made is None and z.layout_problem
    assert z.check_step("Review and create") == z.layout_problem
    z.total.setValue(40)
    z.update_preview()
    z.create()
    assert json.loads(w.store.exam(z.exam_id).template_json)["print"]


def test_answer_key_grid_keyboard_and_csv(app, tmp_path, monkeypatch):
    from PySide6.QtTest import QTest
    from omr_app import answer_key
    w = window(tmp_path)
    k = w.check.key_tab
    g = k.grid
    assert g.rowCount() == 100 and g.horizontalHeaderItem(2).text() == "A" and g.currentRow() == 0
    QTest.keyClick(g, Qt.Key_B)
    QTest.keyClick(g, Qt.Key_D)
    assert g.currentRow() == 2 and w.check.key_edit.toPlainText() == "BD"
    QTest.keyClick(g, Qt.Key_Up)
    QTest.keyClick(g, Qt.Key_A, Qt.ShiftModifier)  # a second correct option for question 2
    assert w.check.key_edit.toPlainText() == "B, AD" and g.currentRow() == 1
    QTest.keyClick(g, Qt.Key_Down)
    QTest.keyClick(g, Qt.Key_Asterisk)
    QTest.keyClick(g, Qt.Key_Return)
    QTest.keyClick(g, Qt.Key_C)
    assert w.check.key_edit.toPlainText() == "B, AD, *, -, C" and "4 of 100" in k.count.text()
    g.setCurrentCell(4, 2)
    g.cellClicked.emit(4, 2)  # click A for question 5
    assert w.check.key_edit.toPlainText() == "B, AD, *, -, A"
    QTest.keyClick(g, Qt.Key_Space)  # the current row (question 5) is dropped again
    g.setCurrentCell(0, 2)
    QTest.keyClick(g, Qt.Key_Delete)
    assert w.check.key_edit.toPlainText() == "-, AD, *"
    assert w.store.exam(w.check.exam.id).answer_key == "-, AD, *"  # saved as it is set

    k.sets.setCurrentText("B")
    assert "uses the key for all sets" in k.count.text()
    QTest.keyClick(g, Qt.Key_C)
    assert w.check.key_edit.toPlainText() == "-, AD, *\nB: -C"

    path = tmp_path / "key.csv"
    monkeypatch.setattr(answer_key.QFileDialog, "getSaveFileName", lambda *a: (str(path), ""))
    k.export_csv()
    assert path.read_text().splitlines()[:3] == ["set,question,answer", ",1,", ",2,AD"]
    w.check.key_edit.clear()
    monkeypatch.setattr(answer_key.QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    k.import_csv()
    assert w.check.key_edit.toPlainText() == "-, AD, *\nB: -C"
    path.write_text("question,answer\n1,Z\n")
    warned = []
    monkeypatch.setattr(answer_key.QMessageBox, "warning", lambda *a: warned.append(a[2]))
    k.import_csv()
    assert "Z is not an option" in warned[0] and w.check.key_edit.toPlainText() == "-, AD, *\nB: -C"

    k.paste_button.click()
    assert g.isHidden() and not w.check.key_edit.isHidden()


def test_a_page_that_cant_be_read_says_why_and_offers_mapping(app, tmp_path):
    w = window(tmp_path)
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((2339, 1654, 3), 255, np.uint8))
    w.check.read_files([str(blank)])
    c = w.check
    assert c.table.item(0, 2).text().startswith("Can't read this page: ") and c.table.columnSpan(0, 2) == 5
    assert "1 of 1 pages couldn't be read" in c.mismatch.text() and not c.map_button.isHidden()
    c.map_button.click()
    assert w.showing() is w.designer


def test_pages_can_be_deleted_or_moved_to_another_exam(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    from PySide6.QtCore import QItemSelectionModel
    files = sheet_files(tmp_path, [1, 2, 3])
    w = window(tmp_path)
    other = w.store.create_exam("Retest", (TEMPLATES / "test-100.json").read_text(encoding="utf-8"))
    c = w.check
    c.read_files([f[0] for f in files])
    assert not c.delete_button.isEnabled()
    c.table.selectRow(0)
    c.table.selectionModel().select(c.table.model().index(2, 0),
                                    QItemSelectionModel.Select | QItemSelectionModel.Rows)
    assert c.selected() == [0, 2] and c.move_button.isEnabled()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a: ("Retest", True))
    c.move_selected()
    assert [p.result.roll_number for p in w.store.pages(other)] == [files[0][2], files[2][2]]
    assert [s.result.roll_number for s in c.sheets] == [files[1][2]] and c.table.rowCount() == 1
    c.table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    c.delete_selected()
    assert c.sheets == [] and w.store.pages(c.exam.id) == [] and c.table.rowCount() == 0


def test_sections_and_a_short_key(app, tmp_path, monkeypatch):
    from omr_app import sections

    (path, answers, roll, set_code), = sheet_files(tmp_path, [4])
    w = window(tmp_path)
    c = w.check
    c.read_files([path])
    c.key_edit.setPlainText("".join(answers[q] or "A" for q in c.questions[:60]))  # only 60 questions in this paper
    assert "60 of 100 questions counted" in c.key_status.text()
    right = sum(1 for q in c.questions[:60] if answers[q])
    assert c.table.item(0, 6).text() == str(right) and c.full_marks() == 60

    def fill(dialog):
        dialog.add()
        dialog.table.item(0, 0).setText("Physics")
        dialog.table.item(0, 2).setText("30")
        dialog.table.item(0, 3).setText("4")
        dialog.add()  # starts at 31
        return dialog.table.item(1, 1).text() == "31" and dialog.accept() is None
    monkeypatch.setattr(sections.SectionsDialog, "exec", fill)
    w.go("Marks and sections")
    c.sections_button.click()  # the real button, so a missing import or a broken dialog fails here
    assert [s.name for s in w.store.exam(c.exam.id).sections] == ["Physics", "Section 2"]
    assert "Physics: questions 1 to 30" in c.sections_label.text()
    physics = sum(1 for q in c.questions[:30] if answers[q])
    assert c.table.item(0, 6).text() == str(4 * physics + right - physics)
    assert c.full_marks() == 4 * 30 + 30
    headers = [w.results.table.horizontalHeaderItem(i).text() for i in range(w.results.table.columnCount())]
    assert headers[4:7] == ["Score", "Physics", "Section 2"]
    assert w.results.table.item(0, 5).text() == str(4 * physics)

    dialog = sections.SectionsDialog(c, [], c.questions, (1, 0, 0))
    dialog.add()
    dialog.table.item(0, 2).setText("120")
    dialog.accept()
    assert "100" in dialog.error.text() and dialog.result() == 0  # stays open, says why


def test_clicking_an_exam_opens_its_page(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from omr_core.sheet import SheetSpec, layout
    import json
    w = MainWindow(tmp_path / "omr.db")
    made = w.store.create_exam("Made here", json.dumps(layout(SheetSpec("Weekly", 30))))
    mapped = w.store.create_exam("Mapped", (TEMPLATES / "test-100.json").read_text(encoding="utf-8"))
    w.exams.refresh()
    assert "Check sheets" not in w.PAGES and w.showing() is w.exams
    row = next(r for r in range(w.exams.table.rowCount()) if w.exams.table.item(r, 0).text() == "Made here")
    w.exams.table.cellClicked.emit(row, 0)
    assert w.check.exam.id == made and w.showing() is w.print_sheet  # nothing read yet: print the sheet first
    assert w.exam_page.title.text() == "Made here" and w.print_sheet.save.isEnabled()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "sheet.pdf"), ""))
    w.print_sheet.save.click()
    assert (tmp_path / "sheet.pdf").read_bytes().startswith(b"%PDF")

    w.exam_settings.name.setText("Weekly 1")
    w.exam_settings.rename()
    assert w.store.exam(made).name == "Weekly 1" and w.exam_page.title.text() == "Weekly 1"
    w.exam_page.back.emit()
    assert w.showing() is w.exams

    w.open_exam(mapped)
    assert not w.print_sheet.save.isEnabled() and "print yourself" in w.print_sheet.note.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w.go("Exams")
    w.open_exam(mapped)
    w.go("Exam settings")
    assert w.showing() is w.exam_settings
    w.exam_settings.delete()
    assert w.check.exam is None and w.showing() is w.exams and [e[0] for e in w.store.exams()] == [made]


def test_the_installer_recipe_finds_everything_it_bundles():
    from pathlib import Path
    from omr_app import new_exam
    root = Path(__file__).parent.parent
    for path in ("src/omr_core/fonts/Poppins-Regular.ttf", "src/omr_app/icon.png", "templates/test-100.json",
                 "packaging/omr.ico", "LICENSE"):
        assert (root / path).is_file(), path
    assert (new_exam.TEMPLATES / "test-100.json").is_file()


def test_changing_the_sheet_reads_every_page_again(app, tmp_path, monkeypatch):
    import json
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from omr_core.sheet import SheetSpec, layout
    files = sheet_files(tmp_path, [1, 2])
    t = load(TEMPLATES / "test-100.json")
    scanned = random_marks(t, 3)  # from the scanner: no file to go back to
    w = window(tmp_path)
    w.open_exam(w.store.create_exam("Wrong sheet", json.dumps(layout(SheetSpec("Weekly", 30)))))
    c = w.check
    c.read_files([f[0] for f in files])
    c.read_image(scan(draw(t, scanned[0]), seed=3), "Scanner", "Scanner", 1)
    assert all(s.result is None for s in c.sheets)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(TEMPLATES / "test-100.json"), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    w.exam_settings.change_sheet()
    assert c.exam.template.name == t.name and "3 of 3 pages read" in shown[0]
    assert [(s.result.roll_number, s.result.answers) for s in c.sheets] == [
        (files[0][2], files[0][1]), (files[1][2], files[1][1]), (scanned[2], scanned[1])]
    assert c.table.rowCount() == 3 and c.mismatch.isHidden()


def test_exams_are_backed_up_and_restored(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: shown.append(a[2]))
    w = window(tmp_path)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(tmp_path / "backup.db"), ""))
    w.exams.backup()
    assert (tmp_path / "backup.db").is_file() and "Every exam is saved" in shown[-1]

    new_pc = MainWindow(tmp_path / "new" / "omr.db")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(tmp_path / "backup.db"), ""))
    new_pc.exams.restore()
    assert shown[-1] == "Restored Mock." and new_pc.exams.table.item(0, 0).text() == "Mock"
    (tmp_path / "x.db").write_text("not a backup")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(tmp_path / "x.db"), ""))
    new_pc.exams.restore()
    assert "isn't an OMR backup" in shown[-1] and new_pc.exams.table.rowCount() == 1


def test_a_printed_copy_is_checked_before_printing_the_rest(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from omr_app.exam_page import print_check
    t = load(TEMPLATES / "test-100.json")
    assert "Every bubble reads empty" in print_check(scan(draw(t, {})), t)
    marks, answers, roll, _ = random_marks(t, 4)
    said = print_check(scan(draw(t, marks)), t)
    assert "This copy reads" in said and f"Roll number {roll}" in said
    assert "can't be read" in print_check(np.full((2339, 1654, 3), 255, np.uint8), t)

    w = window(tmp_path)
    path = tmp_path / "copy.png"
    cv2.imwrite(str(path), scan(draw(t, {})))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    assert w.print_sheet.try_print.isEnabled()
    w.print_sheet.check_print()
    assert shown and shown[0].startswith("This copy reads")
def test_window_carries_the_app_name(app, tmp_path):
    w = window(tmp_path)
    assert w.windowTitle() == "OMR Checker  ·  Mock"
    w.open_exam(None)
    assert w.windowTitle() == "OMR Checker"


def test_first_run_shows_the_steps_and_help_has_the_shortcuts(app, tmp_path, monkeypatch):
    from omr_app import exams, help
    w = MainWindow(tmp_path / "omr.db")
    assert not w.exams.start.isHidden() and w.exams.table.isHidden()
    assert "Create the exam" in w.exams.start.text()
    shown = []
    monkeypatch.setattr(help.HelpDialog, "exec", lambda self: shown.append(self.findChild(QLabel).text()))
    w.show_help()
    assert "Ctrl+N" in shown[0] and str(tmp_path) in shown[0] and "OMR Checker" in shown[0]
    monkeypatch.setattr(exams.NewExamWizard, "exec", lambda self: False)
    w.new_exam()
    assert w.showing() is w.exams
    w.import_scans()  # no exam open yet: stays on Exams
    assert w.showing() is w.exams

    w.open_exam(w.store.create_exam("Mock", (TEMPLATES / "test-100.json").read_text(encoding="utf-8")))
    w.exams.refresh()
    assert w.exams.start.isHidden() and not w.exams.table.isHidden()


def test_written_marks_are_typed_and_added_on_results(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QTableWidgetItem
    files = sheet_files(tmp_path, [1, 2])
    w = window(tmp_path)
    c = w.check
    c.read_files([f[0] for f in files])
    c.key_edit.setPlainText("A" * 100)
    tab = w.written
    tab.refresh()
    assert tab.table.isHidden() and "Set the marks" in tab.note.text()
    tab.out_of.setValue(20)
    tab.save_out_of()
    tab.refresh()
    assert tab.table.rowCount() == 2 and "2 of 2 still to type" in tab.note.text()
    roll = tab.table.item(0, 0).text()
    before = next(c.score_of(s) for s in c.sheets if s.result.roll_number == roll)
    tab.table.setItem(0, 2, QTableWidgetItem("15"))
    assert w.store.written(c.exam.id) == {roll: 15}
    assert next(c.score_of(s) for s in c.sheets if s.result.roll_number == roll) == before + 15
    w.results.refresh()
    head = [w.results.table.horizontalHeaderItem(i).text() for i in range(w.results.table.columnCount())]
    assert head[4:7] == ["Score", "Sheet", "Written"]
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    tab.table.setItem(1, 2, QTableWidgetItem("25"))  # above the written part's 20
    assert warned and "0 to 20" in warned[0] and len(w.store.written(c.exam.id)) == 1
