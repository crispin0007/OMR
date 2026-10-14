import csv
import re
import zipfile
from html.parser import HTMLParser

import cv2
import numpy as np

from omr_core.branding import Institute, prepare_logo
from omr_core.export import grade
from omr_core.grading import Section, marks_for
from omr_core.report import CODE_LETTERS, file_stem, results_code, scorecard_html, write_reports, write_site
from omr_core.students import Student
from test_export import exam_with_pages


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text, self.sources = [], []

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        self.sources += [v for k, v in attrs if k in ("src", "href")]


def test_a_scorecard_page_has_everything_and_works_offline(tmp_path):
    t, pages, key = exam_with_pages(tmp_path)
    sections = [Section("Part 1", 1, 50, 4, -1), Section("Part 2", 51, 100, 4, -1)]
    graded = grade(t, pages, key, 4, -1, 0, {"222": Student("222", "Asha <Rai> & co", "12")}, sections,
                   topics={1: "Kinematics", 2: "Kinematics", 3: "Optics"})
    marks = marks_for(t.questions(), 4, -1, 0, sections)
    logo = np.full((100, 100, 3), 255, np.uint8)
    cv2.circle(logo, (50, 50), 40, (0, 0, 200), -1)
    inst = Institute("Sunrise Academy", motto="Learn & grow", signer_name="R. Sharma", signer_title="Principal",
                     logo=prepare_logo(cv2.imencode(".png", logo)[1].tobytes()))
    g = next(x for x in graded if x.page.result.roll_number == "222")
    html = scorecard_html("Mock 1", t, g, graded, marks, sections, inst)
    p = Text()
    p.feed(html)
    text = "".join(p.text)
    assert "Asha <Rai> & co" in text and "<Rai>" not in html  # names are escaped, not markup
    for want in ("Sunrise Academy", "Learn & grow", "R. Sharma", "Principal", "Mock 1", "Roll number 222",
                 "rank of 4", "Part 1", "Part 2", "Kinematics", "Question by question", "Q100", "bonus",
                 "The answer key was changed: Q3 bonus"):
        assert want in text, want
    assert all(s.startswith("data:image/png;base64,") for s in p.sources) and p.sources  # nothing from the web
    assert "default-src 'none'" in html and "http" not in html.replace("http-equiv", "")
    assert re.search(r'<tr class="wrong"><td>Q1</td><td>B</td><td>A</td>.*?<td class="num">-1</td>', html)
    assert f"<b>{g.score:g}</b><span>out of 396</span>" in html  # Q4 dropped: 99 questions of 4 marks


def test_reports_for_a_whole_exam_go_to_a_folder_or_a_zip_named_by_roll_number(tmp_path):
    t, pages, key = exam_with_pages(tmp_path)
    graded = grade(t, pages, key, 1, 0, 0)
    graded.append(graded[0])  # the same roll number twice
    marks = marks_for(t.questions(), 1, 0, 0)
    seen = []
    assert write_reports(tmp_path / "out", "Mock 1", t, graded, marks, progress=lambda d, n: seen.append(d)) == 5
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert names == ["111-2.html", "111-2.pdf", "111.html", "111.pdf", "222.html", "222.pdf", "333.html", "333.pdf",
                     "444.html", "444.pdf"] and seen == [1, 2, 3, 4, 5]
    assert write_reports(tmp_path / "r.zip", "Mock 1", t, graded[:2], marks, progress=lambda d, n: False) == 1
    with zipfile.ZipFile(tmp_path / "r.zip") as z:
        assert sorted(z.namelist()) == ["111.html", "111.pdf"]
    assert not (tmp_path / "r.zip.part").exists()
    assert file_stem("12?4", set()) == "12_4" and file_stem("", set()) == "no-roll-number"


def test_a_results_website_opens_each_page_only_with_its_code(tmp_path):
    t, pages, key = exam_with_pages(tmp_path)
    graded = grade(t, pages, key, 1, 0, 0, {"222": Student("222", "Asha Rai", "12")})
    marks = marks_for(t.questions(), 1, 0, 0)
    codes = [results_code("secret", g.page.result.roll_number) for g in graded]
    listed = write_site(tmp_path / "site", "Mock 1", t, graded, marks, codes)
    assert listed == tmp_path / "site codes.csv"  # beside the folder, so uploading it never publishes the codes
    code = results_code("secret", "222")
    assert len(code) == 6 and set(code) <= set(CODE_LETTERS) and code != results_code("other", "222")
    assert results_code("secret", "222") == code  # the same in every exam
    names = sorted(p.name for p in (tmp_path / "site").iterdir())
    assert names == sorted(["index.html"] + [f"{g.page.result.roll_number}-{c}.html" for g, c in zip(graded, codes)])
    page = (tmp_path / "site" / f"222-{code}.html").read_text(encoding="utf-8")
    assert "Asha Rai" in page and 'name="robots" content="noindex"' in page
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Mock 1" in index and code not in index and "Asha" not in index  # the lookup page gives nothing away
    with open(listed, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["Roll number", "Name", "Code", "Page"] and ["222", "Asha Rai", code, f"222-{code}.html"] in rows
