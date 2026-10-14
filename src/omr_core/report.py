"""A student's scorecard as one HTML file that works offline in any browser or phone, and the scorecards of a
whole exam, HTML and PDF, into a folder or a zip named by roll number. Nothing is fetched from anywhere."""

import base64
import csv
import hashlib
import hmac
import re
import tempfile
import zipfile
from contextlib import nullcontext
from datetime import date
from html import escape
from pathlib import Path

from .branding import Institute
from .export import Graded, write_scorecards
from .grading import BONUS, DROPPED, Section, changed_questions, describe, score, status
from .students import same_roll
from .template import Template

STATES = {"right": "Right", "wrong": "Wrong", "blank": "Blank", "dropped": "Not counted"}


def scorecard_html(exam_name: str, t: Template, g: Graded, everyone: list[Graded], marks: list[tuple],
                   sections: list[Section] = (), institute: Institute | None = None, written_out_of: float = 0) -> str:
    """One student's scorecard. `everyone` is the whole class, for rank and the class average; `marks` gives
    each question's (correct, wrong, blank, partial, single) marks, from `marks_for`; `written_out_of` is the
    marks of a written part added to the sheet's."""
    qs = t.questions()
    r = g.page.result
    colour = institute.colour if institute else "#1565c0"
    counted = [n for n, k in enumerate(g.key) if k != DROPPED]
    out_of = sum(marks[n][0] for n in counted) + written_out_of
    scores = [x.score for x in everyone] or [g.score]
    rows = []
    for n, (q, k) in enumerate(zip(qs, g.key)):
        answer = r.answers[q]
        state = status(answer, k)
        got = score([answer], [k], marks=[marks[n]]) if k != DROPPED else 0.0
        rows.append(f'<tr class="{state}"><td>Q{q}</td><td>{escape(answer or "–")}</td>'
                    f'<td>{escape("bonus" if k == BONUS else "" if k == DROPPED else describe(k))}</td>'
                    f'<td><span class="tag {state}">{STATES[state]}</span></td><td class="num">{got:+g}</td></tr>')
    bars = []
    for sec in sections:
        part = [n for n, q in enumerate(qs) if sec.first <= q <= sec.last and g.key[n] != DROPPED]
        most = sum(marks[n][0] for n in part)
        bars.append(_bar(sec.name, g.sections.get(sec.name, 0.0), most, f"{g.sections.get(sec.name, 0):g} / {most:g}"))
    topics = [_bar(name, right, n, f"{right} of {n} right") for name, (right, n) in g.topics.items() if n]
    changes = changed_questions(g.key, qs)
    s = g.student
    who = escape(s.name) if s and s.name else f"Roll number {escape(r.roll_number)}"
    facts = [f"Roll number {escape(r.roll_number)}"] if s and s.name else []
    facts += [f"Class {escape(s.class_name)}"] if s and s.class_name else []
    facts += [f"Set {escape(r.set_code)}"] if r.set_code else []
    split = (f'<p class="muted">Sheet {g.omr:g} + written {g.written:g}</p>' if g.written is not None else "")
    head = _letterhead(institute)
    foot = []
    if institute and institute.signer_name:
        foot.append(f'<div class="sign"><div class="line"></div><b>{escape(institute.signer_name)}</b>'
                    f'<span>{escape(institute.signer_title)}</span></div>')
    if institute and institute.footer:
        foot.append(f'<p class="muted">{escape(institute.footer)}</p>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>{escape(exam_name)}: {who}</title>
<style>
:root {{ --brand: {colour}; --right: #1f9d55; --wrong: #d64545; --blank: #8a8f98; --line: #e3e6ea; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f4f5f7; color: #1d2330; font: 15px/1.45 -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif; }}
main {{ max-width: 860px; margin: 0 auto; padding: 16px; }}
.card {{ background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 18px; margin-bottom: 14px; }}
.letterhead {{ display: flex; gap: 16px; align-items: center; border-bottom: 3px solid var(--brand); }}
.letterhead img {{ height: 72px; width: auto; max-width: 160px; object-fit: contain; }}
.letterhead h1 {{ margin: 0; color: var(--brand); font-size: 22px; }}
.letterhead p {{ margin: 2px 0; color: #4a5160; font-size: 13px; }}
.motto {{ font-style: italic; }}
h2 {{ margin: 0 0 4px; font-size: 20px; }} h3 {{ margin: 0 0 12px; font-size: 16px; }}
.muted {{ color: #5f6673; font-size: 13px; margin: 4px 0; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
.tile {{ border: 1px solid var(--line); border-radius: 10px; padding: 12px; }}
.tile b {{ display: block; font-size: 26px; color: var(--brand); }}
.tile span {{ color: #5f6673; font-size: 13px; }}
.stack {{ display: flex; height: 14px; border-radius: 7px; overflow: hidden; margin: 12px 0 6px; background: var(--line); }}
.stack i {{ display: block; }}
.legend {{ display: flex; gap: 14px; flex-wrap: wrap; font-size: 13px; }}
.legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; }}
.bar {{ margin: 10px 0; }} .bar div {{ display: flex; justify-content: space-between; font-size: 14px; }}
.bar .track {{ height: 10px; background: var(--line); border-radius: 5px; margin-top: 4px; }}
.bar .fill {{ height: 100%; background: var(--brand); border-radius: 5px; }}
.filters {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }}
.filters button {{ border: 1px solid var(--line); background: #fff; border-radius: 16px; padding: 5px 12px; font: inherit; cursor: pointer; }}
.filters button[aria-pressed="true"] {{ background: var(--brand); border-color: var(--brand); color: #fff; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th, td {{ text-align: left; padding: 7px 6px; border-bottom: 1px solid var(--line); }}
th {{ color: #5f6673; font-weight: 600; font-size: 12px; text-transform: uppercase; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.tag {{ border-radius: 10px; padding: 1px 8px; font-size: 12px; color: #fff; }}
.tag.right {{ background: var(--right); }} .tag.wrong {{ background: var(--wrong); }} .tag.blank, .tag.dropped {{ background: var(--blank); }}
.note {{ background: #fff6e0; border: 1px solid #f0d48a; border-radius: 10px; padding: 10px 14px; font-size: 14px; }}
.sign {{ margin-left: auto; width: 220px; text-align: center; display: flex; flex-direction: column; }}
.sign .line {{ border-top: 1px solid #1d2330; margin: 36px 0 6px; }} .sign span {{ color: #5f6673; font-size: 13px; }}
footer {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }}
@media (max-width: 560px) {{ .letterhead {{ flex-direction: column; align-items: flex-start; }} td:nth-child(5), th:nth-child(5) {{ display: none; }} }}
@media print {{ body {{ background: #fff; }} .card {{ border: 0; padding: 8px 0; }} .filters {{ display: none; }} tr {{ display: table-row !important; }} }}
</style></head>
<body><main>
{head}
<section class="card">
  <h2>{who}</h2>
  <p class="muted">{escape(exam_name)}{" · " if facts else ""}{" · ".join(facts)}</p>
  <div class="tiles">
    <div class="tile"><b>{g.score:g}</b><span>out of {out_of:g}</span></div>
    <div class="tile"><b>{g.rank}</b><span>rank of {len(scores)}</span></div>
    <div class="tile"><b>{g.percentile:.1f}</b><span>percentile</span></div>
    <div class="tile"><b>{sum(scores) / len(scores):.1f}</b><span>class average (top {max(scores):g})</span></div>
  </div>
  {split}
  <div class="stack" role="img" aria-label="{g.right} right, {g.wrong} wrong, {g.blank} blank">
    {_part(g.right, len(counted), "var(--right)")}{_part(g.wrong, len(counted), "var(--wrong)")}{_part(g.blank, len(counted), "var(--blank)")}
  </div>
  <div class="legend"><span><i style="background:var(--right)"></i>{g.right} right</span>
    <span><i style="background:var(--wrong)"></i>{g.wrong} wrong</span>
    <span><i style="background:var(--blank)"></i>{g.blank} blank</span></div>
  {'<p class="muted">Some marks on this sheet were still being checked when this was made.</p>' if g.to_check else ""}
</section>
{f'<section class="card"><h3>By section</h3>{"".join(bars)}</section>' if bars else ""}
{f'<section class="card"><h3>By topic</h3>{"".join(topics)}</section>' if topics else ""}
{('<section class="note">The answer key was changed: ' + escape("; ".join(f"Q{q} {c}" for q, c in changes)) + ".</section>") if changes else ""}
<section class="card">
  <h3>Question by question</h3>
  <div class="filters" role="group" aria-label="Show">
    <button aria-pressed="true" data-show="all">All {len(qs)}</button>
    <button aria-pressed="false" data-show="wrong">Wrong {g.wrong}</button>
    <button aria-pressed="false" data-show="blank">Blank {g.blank}</button>
    <button aria-pressed="false" data-show="right">Right {g.right}</button>
  </div>
  <table><thead><tr><th>Question</th><th>Your answer</th><th>Key</th><th>Result</th><th class="num">Marks</th></tr></thead>
  <tbody>{"".join(rows)}</tbody></table>
</section>
<footer class="card">{"".join(foot)}<p class="muted">Made {date.today():%d %b %Y} with OMR Checker.</p></footer>
</main>
<script>
document.querySelectorAll(".filters button").forEach(function (b) {{
  b.addEventListener("click", function () {{
    document.querySelectorAll(".filters button").forEach(function (o) {{ o.setAttribute("aria-pressed", o === b); }});
    var show = b.dataset.show;
    document.querySelectorAll("tbody tr").forEach(function (tr) {{
      tr.style.display = show === "all" || tr.classList.contains(show) ? "" : "none";
    }});
  }});
}});
</script>
</body></html>
"""


def _letterhead(inst: Institute | None) -> str:
    if not inst:
        return ""
    logo = (f'<img alt="" src="data:image/png;base64,{base64.b64encode(inst.logo).decode("ascii")}">'
            if inst.logo else "")
    lines = [f"<p>{escape(inst.address).replace(chr(10), ', ')}</p>"] if inst.address else []
    lines += [f"<p>{escape(inst.contact())}</p>"] if inst.contact() else []
    lines += [f'<p class="motto">{escape(inst.motto)}</p>'] if inst.motto else []
    return f'<header class="card letterhead">{logo}<div><h1>{escape(inst.name)}</h1>{"".join(lines)}</div></header>'


def _bar(name: str, value: float, most: float, text: str) -> str:
    share = max(0.0, min(1.0, value / most)) if most else 0.0
    return (f'<div class="bar"><div><span>{escape(name)}</span><span>{escape(text)}</span></div>'
            f'<div class="track"><div class="fill" style="width:{100 * share:.1f}%"></div></div></div>')


def _part(n: int, total: int, colour: str) -> str:
    return f'<i style="width:{100 * n / total:.2f}%;background:{colour}"></i>' if total and n else ""


def file_stem(roll_number: str, taken: set[str]) -> str:
    """A file name for a student's report: the roll number, made safe, with -2, -3… when it is taken."""
    stem = re.sub(r"[^0-9A-Za-z_-]", "_", roll_number) or "no-roll-number"
    name, n = stem, 1
    while name.lower() in taken:
        n += 1
        name = f"{stem}-{n}"
    taken.add(name.lower())
    return name


def write_reports(dest: str | Path, exam_name: str, t: Template, graded: list[Graded], marks: list[tuple],
                  sections: list[Section] = (), institute: Institute | None = None, written_out_of: float = 0,
                  progress=None) -> int:
    """Each student's scorecard as `<roll number>.html` and `.pdf`, into the folder `dest`, or the zip file
    `dest` when it ends in .zip. `progress(done, total)` returns False to stop. Returns how many were written."""
    dest = Path(dest)
    taken: set[str] = set()
    zipped = dest.suffix.lower() == ".zip"
    part = dest.with_name(dest.name + ".part")
    if not zipped:
        dest.mkdir(parents=True, exist_ok=True)
    done = 0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, \
            (zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) if zipped else nullcontext()) as z:
        for g in sorted(graded, key=lambda g: g.page.result.roll_number):
            stem = file_stem(g.page.result.roll_number, taken)
            html = scorecard_html(exam_name, t, g, graded, marks, sections, institute, written_out_of)
            pdf = Path(tmp) / f"{stem}.pdf"
            write_scorecards(pdf, exam_name, t, [g], institute, out_of=len(graded))
            if zipped:
                z.writestr(f"{stem}.html", html)
                z.write(pdf, f"{stem}.pdf")
            else:
                (dest / f"{stem}.html").write_text(html, encoding="utf-8")
                (dest / f"{stem}.pdf").write_bytes(pdf.read_bytes())
            pdf.unlink()
            done += 1
            if progress and progress(done, len(graded)) is False:
                break
    if zipped:
        part.replace(dest)  # a half-written zip never takes the name
    return done


CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to misread


def results_code(secret: str, person: str) -> str:
    """A student's code for the results website: the same in every exam, and not guessable without `secret`."""
    digest = hmac.new(secret.encode(), person.encode(), hashlib.sha256).digest()
    return "".join(CODE_LETTERS[b % 32] for b in digest[:6])


def write_site(dest: str | Path, exam_name: str, t: Template, graded: list[Graded], marks: list[tuple],
               codes: list[str], sections: list[Section] = (), institute: Institute | None = None,
               written_out_of: float = 0) -> Path:
    """A results website in the folder `dest`: `index.html` asks for a roll number and code and opens that
    student's scorecard, saved as `<roll number>-<code>.html`, so a page can only be found with its code.
    `codes` is each graded student's code, in order. The list of codes to hand out goes next to the folder,
    not in it, so uploading the folder never publishes them; its path is returned."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    taken: set[str] = set()
    rows = []
    for g, code in sorted(zip(graded, codes), key=lambda x: x[0].page.result.roll_number):
        roll = g.page.result.roll_number
        stem = file_stem(f"{file_stem(same_roll(roll), set())}-{code}", taken)
        html = scorecard_html(exam_name, t, g, graded, marks, sections, institute, written_out_of)
        html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n<meta name="robots" content="noindex">', 1)
        (dest / f"{stem}.html").write_text(html, encoding="utf-8")
        rows.append([roll, g.student.name if g.student else "", code, f"{stem}.html"])
    (dest / "index.html").write_text(_lookup_html(exam_name, institute), encoding="utf-8")
    listed = dest.with_name(f"{dest.name} codes.csv")
    with open(listed, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel reads the names right
        csv.writer(f).writerows([["Roll number", "Name", "Code", "Page"]] + rows)
    return listed


def _lookup_html(exam_name: str, institute: Institute | None) -> str:
    colour = institute.colour if institute else "#1565c0"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="robots" content="noindex">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'">
<title>{escape(exam_name)}: results</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f4f5f7; color: #1d2330; font: 15px/1.45 -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif; }}
main {{ max-width: 460px; margin: 0 auto; padding: 16px; }}
.card {{ background: #fff; border: 1px solid #e3e6ea; border-radius: 12px; padding: 18px; margin-bottom: 14px; }}
.letterhead {{ display: flex; gap: 16px; align-items: center; border-bottom: 3px solid {colour}; }}
.letterhead img {{ height: 56px; width: auto; max-width: 120px; object-fit: contain; }}
.letterhead h1 {{ margin: 0; color: {colour}; font-size: 20px; }}
.letterhead p {{ margin: 2px 0; color: #4a5160; font-size: 13px; }}
h2 {{ margin: 0 0 12px; font-size: 20px; }}
label {{ display: block; margin: 12px 0 4px; font-weight: 600; }}
input {{ width: 100%; padding: 10px; font: inherit; border: 1px solid #c9ced6; border-radius: 8px; }}
button {{ margin-top: 16px; width: 100%; padding: 11px; font: inherit; font-weight: 600; color: #fff; background: {colour}; border: 0; border-radius: 8px; cursor: pointer; }}
#wrong {{ color: #d64545; min-height: 1.4em; margin: 10px 0 0; }}
.muted {{ color: #5f6673; font-size: 13px; }}
</style></head>
<body><main>
{_letterhead(institute)}
<form class="card" id="find">
  <h2>{escape(exam_name)}</h2>
  <label for="roll">Roll number</label>
  <input id="roll" autocomplete="off" inputmode="numeric" required>
  <label for="code">Your code</label>
  <input id="code" autocomplete="off" autocapitalize="characters" spellcheck="false" required>
  <button type="submit">See my result</button>
  <p id="wrong" role="alert"></p>
  <p class="muted">Your code is on the slip or message from your institute.</p>
</form>
</main>
<script>
document.getElementById("find").addEventListener("submit", function (e) {{
  e.preventDefault();
  var roll = document.getElementById("roll").value.trim();
  if (/^[0-9]+$/.test(roll)) roll = roll.replace(/^0+/, "") || "0";  // 0016 and 16 are one roll number
  roll = roll.replace(/[^0-9A-Za-z_-]/g, "_");
  var code = document.getElementById("code").value.toUpperCase().replace(/[^A-Z0-9]/g, "");
  var page = encodeURIComponent(roll + "-" + code) + ".html";
  if (location.protocol === "file:") {{ location.href = page; return; }}
  fetch(page, {{ method: "HEAD" }}).then(function (r) {{
    if (r.ok) location.href = page;
    else document.getElementById("wrong").textContent = "That roll number and code don't match. Check them and try again.";
  }}, function () {{ location.href = page; }});
}});
</script>
</body></html>
"""
