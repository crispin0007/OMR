"""Make a new answer sheet from a few choices, and print it (US6).

`layout` turns the choices (questions, options, roll number digits, sets and
sections) into a template; `write_pdf` prints any template as a sheet the
reader can read. The PDF is drawn from the template itself, so the printed
sheet and the template always agree.
"""

import io
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .template import parse

PAGE = (210.0, 297.0)  # shortcut: A4 only; add Letter when a school asks for it
MARK = 8.0  # registration mark size, mm
MARKS = [[12, 12], [198, 12], [198, 285], [12, 285]]
ORIENTATION = [26, 9.5, 36, 5]  # a black bar near the top-left mark; upside-down pages are found by it
LEFT, RIGHT, BOTTOM = 14.0, 196.0, 276.0  # printable area for bubbles, inside the marks
ID_TOP = 34.0  # below the title and the name and class lines
NUMBER_W, COLUMN_GAP, HEADER = 7.0, 4.0, 5.0  # question number width, gap between columns, column heading
# Bubble pitch and size, from roomy to compact; the roomiest that fits is used.
SIZES = [(6.0, 6.0, 4.6, 3.4), (5.5, 5.5, 4.4, 3.2), (5.0, 5.0, 4.0, 3.0), (4.6, 4.6, 3.8, 2.9)]
INK = colors.Color(0.45, 0.45, 0.45)  # outlines and letters: visible, but far lighter than a filled mark


@dataclass
class SheetSection:
    name: str
    questions: int
    correct: float = 1.0
    wrong: float = 0.0


@dataclass
class SheetSpec:
    name: str
    questions: int
    options: int = 4
    roll_digits: int = 5
    sets: int = 4  # 0 for no set code
    sections: list[SheetSection] = field(default_factory=list)


def layout(spec: SheetSpec) -> dict:
    """The template for a sheet with these choices. Raises ValueError when they can't fit one A4 page."""
    if not spec.name.strip():
        raise ValueError("give the sheet a name")
    if not 2 <= spec.options <= 8:
        raise ValueError("questions need 2 to 8 options")
    if not 0 <= spec.roll_digits <= 12:
        raise ValueError("the roll number can have 0 to 12 digits")
    if spec.sets == 1 or not 0 <= spec.sets <= 8:
        raise ValueError("choose no sets, or 2 to 8 sets")
    sections = spec.sections or [SheetSection("", spec.questions)]
    if any(s.questions < 1 for s in sections):
        raise ValueError("every section needs at least one question")
    if spec.sections and len({s.name.strip() for s in sections}) != len(sections) or any(
            spec.sections and not s.name.strip() for s in sections):
        raise ValueError("every section needs its own name")
    if sum(s.questions for s in sections) != spec.questions:
        raise ValueError("the sections' questions don't add up to the sheet's questions")
    if spec.questions < 1:
        raise ValueError("the sheet needs at least one question")
    # Questions below the roll number look tidiest; beside it too only when that's the only way to keep bubbles big.
    tries = [(size, False) for size in SIZES[:3]] + [(size, True) for size in SIZES] + [(SIZES[3], False)]
    for size, beside in tries:
        grids = _place(spec, sections, size, beside)
        if grids is not None:
            break
    else:
        raise ValueError(f"{spec.questions} questions with {spec.options} options don't fit on one A4 page; "
                         "use fewer questions, options or sections")
    d = {"name": spec.name.strip(), "version": 1, "page_mm": list(PAGE),
         "markers": {"shape": "square", "size_mm": MARK, "centres_mm": MARKS},
         "orientation_mm": ORIENTATION, "bubble_mm": list(size[2:]), "grids": grids}
    if spec.sections:
        first = 1
        d["sections"] = []
        for s in spec.sections:
            d["sections"].append({"name": s.name.strip(), "first": first, "last": first + s.questions - 1,
                                  "correct": s.correct, "wrong": s.wrong, "blank": 0.0})
            first += s.questions
    parse(d)
    return d


def _place(spec: SheetSpec, sections: list[SheetSection], size, beside: bool) -> list[dict] | None:
    """Grids for the roll number, set code and questions at one bubble size, or None if they don't fit."""
    px, py, _, _ = size
    grids = []
    id_bottom, id_right = ID_TOP, LEFT
    grid_top = ID_TOP + 12 + py / 2  # a label and a row of write-in boxes above the bubbles
    if spec.roll_digits:
        x = LEFT + 6 + px / 2  # room for the digit labels on the left
        grids.append({"kind": "roll_number", "origin_mm": [x, grid_top], "pitch_mm": [px, py],
                      "rows": 10, "cols": spec.roll_digits})
        id_right = x + (spec.roll_digits - 1) * px + px / 2
        id_bottom = grid_top + 9.5 * py
    if spec.sets:
        x = id_right + 10 + px / 2
        grids.append({"kind": "set_code", "options": "ABCDEFGH"[:spec.sets], "origin_mm": [x, grid_top],
                      "pitch_mm": [px + 2, 0], "rows": 1, "cols": spec.sets})
        id_right = x + (spec.sets - 1) * (px + 2) + px / 2
        id_bottom = max(id_bottom, grid_top + py / 2 + 4)
    # Questions go in columns: first beside the roll number and set code, then across the page below them.
    width = NUMBER_W + spec.options * px + COLUMN_GAP
    columns = []
    if grids and beside:
        x = id_right + 10
        while x + width - COLUMN_GAP <= RIGHT:
            columns.append((x, ID_TOP, id_bottom))
            x += width
    top = id_bottom + 6 if grids else ID_TOP
    x = LEFT
    while x + width - COLUMN_GAP <= RIGHT:
        columns.append((x, top, BOTTOM))
        x += width
    first, col = 1, 0
    for s in sections:
        left = s.questions
        while left:  # each section starts in a new column, under its own heading
            if col == len(columns):
                return None
            x, y0, y1 = columns[col]
            fits = int((y1 - y0 - HEADER) // py)
            rows = min(left, fits, -(-left // max(1, -(-left // max(fits, 1)))))  # spread evenly over its columns
            col += 1
            if rows < 1:
                continue
            grids.append({"kind": "questions", "first": first, "options": "ABCDEFGH"[:spec.options],
                          "origin_mm": [round(x + NUMBER_W + px / 2, 2), round(y0 + HEADER + py / 2, 2)],
                          "pitch_mm": [px, py], "rows": rows, "cols": spec.options})
            first += rows
            left -= rows
    # Spread the full-width columns that were used across the page instead of crowding them to the left.
    below = [i for i in range(col) if columns[i][1] == top]
    if len(below) > 1:
        spare = RIGHT - LEFT - len(below) * width + COLUMN_GAP
        extra = min(spare / (len(below) - 1), 12.0)
        shift = {columns[i][0]: (spare - extra * (len(below) - 1)) / 2 + n * extra for n, i in enumerate(below)}
        for g in grids:
            if g["kind"] == "questions" and g["origin_mm"][1] == round(top + HEADER + py / 2, 2):
                x = g["origin_mm"][0] - NUMBER_W - px / 2
                g["origin_mm"][0] = round(g["origin_mm"][0] + shift[min(shift, key=lambda c: abs(c - x))], 2)
    return grids


def write_pdf(template: dict, out: str | Path | io.BytesIO):
    """Print a template as an A4 answer sheet: marks, bubbles with their letters, numbers and labels."""
    t = parse(template)
    w, h = t.page
    c = canvas.Canvas(out if isinstance(out, io.BytesIO) else str(out), pagesize=(w * mm, h * mm))
    c.setTitle(t.name)
    y = lambda v: (h - v) * mm  # templates measure from the top, PDFs from the bottom
    c.setFillColor(colors.black)
    s = t.marker_size
    for mx, my in t.markers:
        c.rect((mx - s / 2) * mm, y(my + s / 2), s * mm, s * mm, stroke=0, fill=1)
    if t.orientation:
        ox, oy, ow, oh = t.orientation
        c.rect(ox * mm, y(oy + oh), ow * mm, oh * mm, stroke=0, fill=1)
        c.setFont("Helvetica-Bold", 12)
        c.drawString((ox + ow + 6) * mm, y(oy + oh - 0.5), t.name)
    else:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(30 * mm, y(14), t.name)
    c.setFont("Helvetica", 9)
    for label, x0, x1 in (("Name", 16, 112), ("Class", 118, 158), ("Date", 164, 194)):
        c.drawString(x0 * mm, y(27), label)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.4)
        c.line((x0 + len(label) * 1.9 + 2) * mm, y(27.5), x1 * mm, y(27.5))

    bw, bh = t.bubble
    sections = {sec["first"]: sec["name"] for sec in template.get("sections", [])}
    for g in t.grids:
        letters = "0123456789" if g.kind == "roll_number" else g.options
        for r in range(g.rows):
            for col in range(g.cols):
                cx, cy = g.centre(r, col)
                c.setStrokeColor(INK)
                c.setLineWidth(0.5)
                c.ellipse((cx - bw / 2) * mm, y(cy + bh / 2), (cx + bw / 2) * mm, y(cy - bh / 2), stroke=1, fill=0)
                c.setFillColor(INK)
                c.setFont("Helvetica", min(6.0, bh * 1.9))
                c.drawCentredString(cx * mm, y(cy + bh * 0.22), letters[r if g.kind == "roll_number" else col])
        c.setFillColor(colors.black)
        (x0, y0), (x1, _) = g.centre(0, 0), g.centre(0, g.cols - 1)
        if g.kind == "questions":
            c.setFont("Helvetica", 7)
            for r in range(g.rows):
                c.drawRightString((x0 - bw / 2 - 1) * mm, y(g.centre(r, 0)[1] + 1.1), str(g.first + r))
            name = sections.get(g.first)
            if name:
                c.setFont("Helvetica-Bold", 7.5)
                c.drawString((x0 - bw / 2 - 5) * mm, y(y0 - g.pitch[1] / 2 - 1), name)
        else:
            c.setFont("Helvetica-Bold", 8)
            label = "Roll number" if g.kind == "roll_number" else "Set"
            c.drawString((x0 - bw / 2) * mm, y(y0 - g.pitch[1] / 2 - 8.5), label)
            if g.kind == "roll_number":  # boxes to write the number in, above its columns
                c.setStrokeColor(colors.black)
                c.setLineWidth(0.4)
                for col in range(g.cols):
                    bx = g.centre(0, col)[0] - g.pitch[0] / 2
                    c.rect(bx * mm, y(y0 - g.pitch[1] / 2 - 1), g.pitch[0] * mm, 6 * mm, stroke=1, fill=0)
    c.setFont("Helvetica", 7)
    c.setFillColor(INK)
    c.drawString(30 * mm, y(h - 4), "Fill one bubble fully with a dark pen or pencil. Do not fold or mark the corners.")
    c.showPage()
    c.save()


def render(template: dict, dpi: int = 200) -> np.ndarray:
    """The printed sheet as a BGR image, for the preview and for tests."""
    buf = io.BytesIO()
    write_pdf(template, buf)
    pdf = pdfium.PdfDocument(buf.getvalue())
    try:
        rgb = pdf[0].render(scale=dpi / 72).to_numpy()
    finally:
        pdf.close()
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
