"""A read sheet with its marking drawn on it, to see at a glance what was right and wrong and to check that every
bubble of the template sits on a bubble of the paper.

Green rings a filled bubble that is right, red one that is wrong, and blue the right answer the student missed
(wrong or blank). Purple rings what was read where there is nothing to mark (the roll number, the set, a question
with no key yet), grey a filled bubble on a dropped question, and orange boxes what waits on Review. With
`every_bubble`, a thin circle shows where the template expects each bubble.
"""

import io
from pathlib import Path

import cv2
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .branding import Institute
from .grading import BONUS, DROPPED, EITHER, status
from .reader import SCALE, PageResult
from .template import Template

# BGR
RIGHT, WRONG, ANSWER, READ, DROP, CHECK, GUIDE = ((46, 125, 50), (40, 40, 211), (210, 120, 30), (150, 60, 140),
                                                  (150, 150, 150), (0, 140, 255), (200, 170, 0))
LEGEND = [(RIGHT, "right"), (WRONG, "wrong"), (ANSWER, "the right answer, missed"), (READ, "read, nothing to mark"),
          (DROP, "dropped question"), (CHECK, "to check")]


def mark_sheet(aligned: np.ndarray, t: Template, r: PageResult, key: dict[int, str], every_bubble: bool = False,
               boxes: list[tuple[float, float, float, float]] = ()) -> np.ndarray:
    """The aligned page in colour with the marking drawn on it. `key` is the answer for each question (none for a
    question without one); `boxes` are areas to check, in mm."""
    out = cv2.cvtColor(aligned, cv2.COLOR_GRAY2BGR) if aligned.ndim == 2 else aligned.copy()
    radius = round(max(t.bubble) / 2 * SCALE) + 3

    def at(g, row: int, col: int) -> tuple[int, int]:
        x, y = g.centre(row, col)
        return round(x * SCALE), round(y * SCALE)

    def ring(g, row: int, col: int, colour, width: int = 3):
        cv2.circle(out, at(g, row, col), radius, colour, width, cv2.LINE_AA)

    if every_bubble:  # where the template expects each bubble: it should sit on the printed one
        for g in t.grids:
            for row in range(g.rows):
                for col in range(g.cols):
                    cv2.circle(out, at(g, row, col), round(max(t.bubble) / 2 * SCALE), GUIDE, 1, cv2.LINE_AA)
    for g in t.grids:
        if g.kind == "questions":
            for row in range(g.rows):
                q = g.first + row
                answer, right = r.answers.get(q, ""), key.get(q)
                state = status(answer, right) if right else None
                colour = (READ if state is None else DROP if state == "dropped" else
                          RIGHT if state == "right" else WRONG)
                for letter in answer:
                    if letter in g.options:
                        ring(g, row, g.options.index(letter), colour)
                if state in ("wrong", "blank") and right not in (BONUS, DROPPED):
                    for option in right.replace(EITHER, ""):  # every right option, of each answer accepted
                        if option in g.options and option not in answer:
                            ring(g, row, g.options.index(option), ANSWER, 2)
        elif g.kind == "numeric":  # the digits read aren't placed by column, so the whole grid is boxed
            right = key.get(g.first)
            state = status(r.answers.get(g.first, ""), right) if right else None
            colour = (READ if state is None else DROP if state == "dropped" else RIGHT if state == "right" else
                      WRONG if state == "wrong" else ANSWER)
            (x0, y0), (x1, y1) = at(g, 0, 0), at(g, g.rows - 1, g.cols - 1)
            cv2.rectangle(out, (x0 - radius, y0 - radius), (x1 + radius, y1 + radius), colour, 3)
            if state in ("wrong", "blank") and right not in (BONUS, DROPPED):
                cv2.putText(out, right, (x0 - radius, y0 - radius - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.8, ANSWER, 2,
                            cv2.LINE_AA)
        elif g.kind == "roll_number":
            for col, digit in enumerate(r.roll_number[:g.cols]):
                if digit.isdigit():
                    ring(g, int(digit), col, READ)
        elif g.kind == "set_code" and r.set_code and r.set_code in g.options:
            ring(g, 0, g.options.index(r.set_code), READ)
    for x0, y0, x1, y1 in boxes:
        cv2.rectangle(out, (round(x0 * SCALE), round(y0 * SCALE)), (round(x1 * SCALE), round(y1 * SCALE)), CHECK, 4)
    return out


def with_legend(marked: np.ndarray, every_bubble: bool = False) -> np.ndarray:
    """The marked sheet with a strip below saying what each colour means."""
    w = marked.shape[1]
    strip = np.full((70, w, 3), 255, np.uint8)
    x = 20
    for colour, text in LEGEND + ([(GUIDE, "where each bubble is expected")] if every_bubble else []):
        cv2.circle(strip, (x + 12, 35), 12, colour, 3, cv2.LINE_AA)
        cv2.putText(strip, text, (x + 32, 43), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 60, 60), 2, cv2.LINE_AA)
        x += 50 + cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0][0]
    return np.vstack([marked, strip])


def write_marked_sheets(path: str | Path, exam_name: str, t: Template, graded: list, image_of,
                        institute: Institute | None = None, every_bubble: bool = False) -> int:
    """One A4 page per student, by rank: who they are, their score, and their sheet with its marking and the
    legend. `image_of(page id)` gives the saved page image (None when there is none, and the page is left out).
    Returns how many pages were written."""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(f"{exam_name} marked sheets")
    c.setAuthor(institute.name if institute else "")
    w, h = A4
    done = 0
    for g in graded:
        image = image_of(g.page.id)
        if image is None:
            continue
        r = g.page.result
        marked = with_legend(mark_sheet(image, t, r, dict(zip(t.questions(), g.key)), every_bubble), every_bubble)
        jpeg = cv2.imencode(".jpg", marked, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
        who = g.student.name + "   " if g.student and g.student.name else ""
        c.setFont("Helvetica-Bold", 11)
        c.drawString(12 * mm, h - 12 * mm, f"{institute.name}: {exam_name}" if institute and institute.name
                     else exam_name)
        c.setFont("Helvetica", 10)
        c.drawString(12 * mm, h - 18 * mm, f"{who}Roll number {r.roll_number}    Score {g.score:g}    Rank {g.rank}"
                     f"    Right {g.right}  Wrong {g.wrong}  Blank {g.blank}")
        ih, iw = marked.shape[:2]
        scale = min((w - 24 * mm) / iw, (h - 30 * mm) / ih)
        c.drawImage(ImageReader(io.BytesIO(jpeg)), 12 * mm, h - 22 * mm - ih * scale,
                    iw * scale, ih * scale)
        c.showPage()
        done += 1
    c.save()
    return done
