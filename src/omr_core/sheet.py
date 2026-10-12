"""Make a new answer sheet from a few choices, and print it (US6).

`layout` turns the choices (questions, options, roll number digits, sets,
sections, colour, heading, logo and instructions) into a template; `write_pdf`
prints that template as a sheet the reader can read. The PDF is drawn from the
template itself, so the printed sheet and the template always agree.

The sheet has a header (heading and logo, name boxes, roll number, program,
instructions with fill examples, signatures and question set) above bordered
question columns with banded rows and pill-shaped bubbles. Everything but the
corner marks, the orientation bar and the question numbers is printed in the
chosen colour.
"""

import base64
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .template import parse

PAGE = (210.0, 297.0)  # shortcut: A4 only; add Letter when a school asks for it
MARK = 8.0  # corner target size, mm
MARKS = [[12, 12], [198, 12], [198, 285], [12, 285]]
ORIENTATION = [172, 9, 18, 5]  # a black bar near the top-right mark; upside-down pages are found by it
LEFT, RIGHT, BOTTOM = 15.0, 195.0, 278.0  # printable area inside the marks
BUBBLE = (3.8, 2.1)  # pill width and height, mm; every grid uses the same size
LINE = 0.35  # outline width, mm
MAX_ROLL_DIGITS = 9  # more leaves too little room for the instructions beside them
LIGHTEST_LETTER = 0.32  # bubble letters are at least this light (0 black, 1 white) in grey, whatever the colour

# Header, in mm from the top of the page.
NAME_TOP, NAME_BOTTOM = 18.0, 37.5
BLOCK_TOP, BLOCK_BOTTOM = 39.5, 90.5
BAND = 5.0  # height of a tinted heading band
ROLL_ROW0, ROLL_PITCH = 55.0, 3.6  # first digit row's centre and the pitch between digit rows
# Pitches leave at least the reader's snapping reach (1.5 mm) between neighbouring bubbles, so a pen
# mark in one bubble can't pull the reader's search for the empty bubble beside it.
SIDE = 57.0  # width of the signatures and question set column on the right
GAP = 2.5  # between boxes
INSTRUCTION_TOP, INSTRUCTION_BOTTOM = 54.0, BLOCK_BOTTOM - 12.5  # the instruction lines go between these
INSTRUCTION_SIZES = [7.0, 6.5, 6.0]  # points; smaller only when the lines don't fit otherwise

# Question columns.
COLUMNS_TOP = BLOCK_BOTTOM + 3
NUMBER_W = 7.0  # the question number cell on the left of each column
COLUMN_GAP = 2.5
ROOMY_OPTION = 9.0  # option pitch the column count is chosen for (4 options give 4 columns)
MIN_OPTION = BUBBLE[0] + 1.5  # narrowest option pitch that still reads well
PITCHES = [5.0, 4.6, 4.2, 3.8, 3.6]  # row pitch from roomy to compact; the roomiest that fits is used

DEFAULT_HEADING = "Answer Sheet (OMR)"
DEFAULT_COLOUR = "#e4007c"
DEFAULT_INSTRUCTIONS = [
    "Write your roll number in the boxes and fill the matching bubble below each digit.",
    "Use a black or blue ball pen and fill the bubble completely.",
    "Fill only one bubble for each question.",
    "Do not alter or erase an answer once it is filled.",
    "Do not make stray marks or rough work on this sheet.",
    "Fill the question set printed on your question paper.",
]
LOGO_MAX_BYTES = 1_000_000
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

FONTS = Path(__file__).parent / "fonts"  # Poppins, SIL Open Font License (fonts/OFL.txt)
REGULAR, BOLD = "Poppins", "Poppins-SemiBold"


@dataclass
class SheetSection:
    name: str
    questions: int
    correct: float = 1.0
    wrong: float = 0.0
    partial: bool = False  # more than one bubble may be filled, with part marks for part of a multi-correct answer


@dataclass
class SheetSpec:
    name: str
    questions: int
    options: int = 4
    roll_digits: int = 5
    sets: int = 4  # 0 for no set code
    sections: list[SheetSection] = field(default_factory=list)
    colour: str = DEFAULT_COLOUR
    heading: str = DEFAULT_HEADING
    instructions: list[str] = field(default_factory=lambda: list(DEFAULT_INSTRUCTIONS))
    logo: bytes = b""  # JPEG from `logo_jpeg`, or nothing
    true_false: bool = False  # two options printed T and F


def layout(spec: SheetSpec) -> dict:
    """The template for a sheet with these choices. Raises ValueError when they can't fit one A4 page."""
    if not spec.name.strip():
        raise ValueError("give the sheet a name")
    if not 2 <= spec.options <= 8:
        raise ValueError("questions need 2 to 8 options")
    if spec.true_false and spec.options != 2:
        raise ValueError("true or false questions have 2 options")
    if not 0 <= spec.roll_digits <= MAX_ROLL_DIGITS:
        raise ValueError(f"the roll number can have 0 to {MAX_ROLL_DIGITS} digits")
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
    style = {"colour": spec.colour.lower(), "heading": spec.heading.strip(),
             "instructions": [i.strip() for i in spec.instructions if i.strip()]}
    if spec.logo:
        style["logo_jpeg"] = base64.b64encode(spec.logo).decode("ascii")
    _check_style(style)

    grids = _id_grids(spec.roll_digits, spec.sets)
    grids += _question_grids("TF" if spec.true_false else "ABCDEFGH"[:spec.options], sections, bool(spec.sections))
    d = {"name": spec.name.strip(), "version": 1, "page_mm": list(PAGE),
         "markers": {"shape": "ring", "size_mm": MARK, "centres_mm": MARKS},
         "orientation_mm": ORIENTATION, "bubble_mm": list(BUBBLE), "grids": grids, "print": style}
    if spec.sections:
        first = 1
        d["sections"] = []
        for s in spec.sections:
            d["sections"].append({"name": s.name.strip(), "first": first, "last": first + s.questions - 1,
                                  "correct": s.correct, "wrong": s.wrong, "blank": 0.0, "partial": s.partial})
            first += s.questions
    t = parse(d)
    _instruction_lines(style["instructions"], _header(t)["middle"])  # raises when they don't fit
    return d


def logo_jpeg(data: bytes) -> bytes:
    """A logo image file as a small JPEG on white, ready to put on a sheet. Raises ValueError if it isn't an image."""
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("the logo isn't an image this app can open (use PNG or JPEG)")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:  # transparent parts become white paper
        alpha = image[:, :, 3:] / 255.0
        image = (image[:, :, :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)
    scale = min(1.0, 600 / max(image.shape[:2]))
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def _check_style(style: dict):
    if not COLOUR.match(str(style.get("colour", ""))):
        raise ValueError("the colour must look like #e4007c")
    if not isinstance(style.get("heading"), str) or not isinstance(style.get("instructions"), list) or not all(
            isinstance(i, str) for i in style["instructions"]):
        raise ValueError("the heading and instructions must be text")
    if "logo_jpeg" in style:
        try:
            data = base64.b64decode(style["logo_jpeg"], validate=True)
        except (ValueError, TypeError) as e:
            raise ValueError("the logo is damaged") from e
        if len(data) > LOGO_MAX_BYTES or cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) is None:
            raise ValueError("the logo is damaged or too large")


def _style(template: dict) -> dict:
    """The colour, heading, instructions and logo to print; plain defaults for templates without them."""
    style = {"colour": DEFAULT_COLOUR, "heading": template.get("name", ""), "instructions": DEFAULT_INSTRUCTIONS,
             **template.get("print", {})}
    _check_style(style)
    return style


# -- geometry ---------------------------------------------------------------------------------------------


def _roll_pitch(digits: int) -> float:
    return 6.0 if digits <= 5 else 5.5


def _id_grids(digits: int, sets: int) -> list[dict]:
    grids = []
    if digits:
        p = _roll_pitch(digits)
        grids.append({"kind": "roll_number", "origin_mm": [LEFT + 3 + p / 2, ROLL_ROW0], "pitch_mm": [p, ROLL_PITCH],
                      "rows": 10, "cols": digits})
    if sets:
        x0, y, pitch = _set_row(sets)
        grids.append({"kind": "set_code", "options": "ABCDEFGH"[:sets], "origin_mm": [x0, y],
                      "pitch_mm": [pitch, 0], "rows": 1, "cols": sets})
    return grids


def _set_row(sets: int) -> tuple[float, float, float]:
    """First set bubble's centre and the pitch: beside the label for up to 4 sets, else on a row below it."""
    left = RIGHT - SIDE
    if sets <= 4:
        return left + 36.5, BLOCK_BOTTOM - 5.5, 5.8
    pitch = (SIDE - 4) / sets
    return left + 2 + pitch / 2, BLOCK_BOTTOM - 3.5, pitch


def _header(t) -> dict:
    """Header boxes as (x0, y0, x1, y1) mm, worked out from the template's roll number and set grids."""
    roll = next((g for g in t.grids if g.kind == "roll_number"), None)
    sets = next((g for g in t.grids if g.kind == "set_code"), None)
    h = {}
    x = LEFT
    if roll:
        p = roll.pitch[0]
        h["roll"] = (LEFT, BLOCK_TOP, LEFT + 6 + roll.cols * p, BLOCK_BOTTOM)
        x = h["roll"][2] + GAP
    h["middle"] = (x, BLOCK_TOP, RIGHT - SIDE - GAP, BLOCK_BOTTOM)
    side = RIGHT - SIDE
    top = BLOCK_TOP + 13 if sets else BLOCK_TOP + 20
    half = (SIDE - GAP) / 2
    h["signatures"] = [(side, top, side + half, top + 20), (side + half + GAP, top, RIGHT, top + 20)]
    if sets:
        h["sets"] = (side, BLOCK_BOTTOM - (11 if sets.cols <= 4 else 13), RIGHT, BLOCK_BOTTOM)
    return h


def _question_grids(letters: str, sections: list[SheetSection], headed: bool) -> list[dict]:
    """Question grids in bordered columns; each section starts a new column."""
    options = len(letters)
    width = RIGHT - LEFT
    roomy = int((width + COLUMN_GAP) // (NUMBER_W + options * ROOMY_OPTION + COLUMN_GAP))
    head = BAND if headed else 0
    for pitch in PITCHES:
        fit = int((BOTTOM - COLUMNS_TOP - head - 0.5) // pitch)
        cols = [-(-s.questions // fit) for s in sections]
        if sum(cols) <= roomy:
            break
    n = max(roomy, sum(cols))
    column = (width - (n - 1) * COLUMN_GAP) / n
    option = (column - NUMBER_W) / options
    if option < MIN_OPTION:
        raise ValueError(f"{sum(s.questions for s in sections)} questions with {options} options don't fit on one "
                         "A4 page; use fewer questions, options or sections")
    # Spare columns go to the longest sections, so short sheets spread across the page.
    while sum(cols) < roomy:
        i = max(range(len(sections)), key=lambda k: -(-sections[k].questions // cols[k]))
        if -(-sections[i].questions // cols[i]) <= 10:
            break
        cols[i] += 1
    used = sum(cols)
    x = LEFT + (width - used * column - (used - 1) * COLUMN_GAP) / 2
    grids, first = [], 1
    for s, c in zip(sections, cols):
        left = s.questions
        for k in range(c):
            rows = -(-left // (c - k))
            grids.append({"kind": "questions", "first": first, "options": letters, "multi": s.partial,
                          "origin_mm": [round(x + NUMBER_W + option / 2, 2), round(COLUMNS_TOP + head + pitch / 2, 2)],
                          "pitch_mm": [round(option, 3), pitch], "rows": rows, "cols": options})
            first += rows
            left -= rows
            x += column + COLUMN_GAP
    return grids


def _instruction_lines(instructions: list[str], box) -> tuple[list[tuple[str, str]], float, float]:
    """(number, text) per printed line wrapped to the instruction box, the font size and the leading in mm.

    Raises ValueError when they don't fit even in the smallest size.
    """
    _fonts()
    width = (box[2] - box[0] - 8) * mm
    for size in INSTRUCTION_SIZES:
        leading = size * 0.42
        lines = []
        for n, text in enumerate(instructions, 1):
            for k, part in enumerate(simpleSplit(text, REGULAR, size, width)):
                lines.append((f"{n}." if k == 0 else "", part))
        if len(lines) * leading <= INSTRUCTION_BOTTOM - INSTRUCTION_TOP:
            return lines, size, leading
    raise ValueError(f"the instructions need {len(lines)} lines and don't fit in the box; shorten them")


# -- drawing ----------------------------------------------------------------------------------------------


def _fonts():
    if REGULAR not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(REGULAR, str(FONTS / "Poppins-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(BOLD, str(FONTS / "Poppins-SemiBold.ttf")))


def write_pdf(template: dict, out: str | Path | io.BytesIO):
    """Print a template made by `layout` as an A4 answer sheet."""
    t = parse(template)
    style = _style(template)
    _fonts()
    ink = colors.HexColor(style["colour"])
    letters = _readable(ink)
    band = _mix(ink, 0.28)  # heading bands
    stripe = _mix(ink, 0.11)  # every other question row
    w, h = t.page
    c = canvas.Canvas(out if isinstance(out, io.BytesIO) else str(out), pagesize=(w * mm, h * mm))
    c.setTitle(t.name)
    y = lambda v: (h - v) * mm  # templates measure from the top, PDFs from the bottom

    def box(x0, y0, x1, y1, fill=None, stroke=True, width=LINE):
        c.setLineWidth(width * mm)
        c.setStrokeColor(ink)
        if fill is not None:
            c.setFillColor(fill)
        c.rect(x0 * mm, y(y1), (x1 - x0) * mm, (y1 - y0) * mm, stroke=1 if stroke else 0, fill=fill is not None)

    def text(x, base, s, size, font=REGULAR, colour=colors.black, align="left"):
        c.setFillColor(colour)
        c.setFont(font, size)
        {"left": c.drawString, "centre": c.drawCentredString, "right": c.drawRightString}[align](x * mm, y(base), s)

    def banded(x0, y0, x1, title, size=8.5):
        box(x0, y0, x1, y0 + BAND, fill=band)
        text((x0 + x1) / 2, y0 + BAND / 2 + size * 0.12, title, size, BOLD, align="centre")

    def pill(cx, cy, letter="", filled=None):
        bw, bh = t.bubble
        c.setLineWidth(LINE * mm)
        c.setStrokeColor(ink)
        c.setFillColor(filled or colors.white)
        c.roundRect((cx - bw / 2) * mm, y(cy + bh / 2), bw * mm, bh * mm, bh / 2 * mm, stroke=1, fill=1)
        if letter:
            text(cx, cy + bh * 0.27, letter, bh * 2.4, BOLD, letters, "centre")

    # Corner targets and the orientation bar stay black so they read on any print colour.
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.black)
    s = t.marker_size
    for mx, my in t.markers:
        for r, line in ((0.44, 0.12), (0.25, 0.08)):
            c.setLineWidth(s * line * mm)
            c.circle(mx * mm, y(my), s * r * mm, stroke=1, fill=0)
        c.circle(mx * mm, y(my), s * 0.08 * mm, stroke=0, fill=1)
    if t.orientation:
        ox, oy, ow, oh = t.orientation
        c.rect(ox * mm, y(oy + oh), ow * mm, oh * mm, stroke=0, fill=1)

    # Heading and logo.
    logo_right = LEFT + 5
    if "logo_jpeg" in style:
        image = ImageReader(io.BytesIO(base64.b64decode(style["logo_jpeg"])))
        iw, ih = image.getSize()
        lh = 10.0
        lw = min(lh * iw / ih, 40.0)
        lh = lw * ih / iw
        c.drawImage(image, (LEFT + 5) * mm, y(12.5 + lh / 2), lw * mm, lh * mm)
        logo_right = LEFT + 5 + lw
    room = 2 * (w / 2 - logo_right - 3) * mm
    size = 12.0
    while size > 7 and pdfmetrics.stringWidth(style["heading"], BOLD, size) > room:
        size -= 0.5
    text(w / 2, 14.5, style["heading"], size, BOLD, align="centre")

    # Student's name in block letters: first, middle and last.
    box(LEFT, NAME_TOP, RIGHT, NAME_BOTTOM)
    banded(LEFT, NAME_TOP, RIGHT, "Student’s Name (IN BLOCK LETTERS)", 10)
    third = (RIGHT - LEFT) / 3
    for i, label in enumerate(("First Name", "Middle Name", "Last Name")):
        x0 = LEFT + i * third
        text(x0 + third / 2, 28.6, label, 9.5, align="centre")
        cell = (third - 4) / 12
        for k in range(12):
            box(x0 + 2 + k * cell, 30.5, x0 + 2 + (k + 1) * cell, 36.0, width=0.2)

    hd = _header(t)
    roll = next((g for g in t.grids if g.kind == "roll_number"), None)
    if roll:
        x0, y0, x1, y1 = hd["roll"]
        box(x0, y0, x1, y1)
        banded(x0, y0, x1, "ROLL NUMBER")
        for col in range(roll.cols):
            cx = roll.centre(0, col)[0]
            box(cx - roll.pitch[0] / 2 + 0.5, y0 + BAND + 1.5, cx + roll.pitch[0] / 2 - 0.5, y0 + BAND + 7, width=0.2)
            for r in range(10):
                pill(cx, roll.centre(r, col)[1], str(r))

    # Program line, then the instructions with examples of wrong and right fills.
    x0, y0, x1, y1 = hd["middle"]
    box(x0, y0, x1, y0 + 6)
    text(x0 + 2, y0 + 4.1, "Program :", 8.5, colour=ink)
    top = y0 + 8
    box(x0, top, x1, y1)
    banded(x0, top, x1, "INSTRUCTION")
    lines, size, leading = _instruction_lines(style["instructions"], hd["middle"])
    for k, (number, line) in enumerate(lines):
        base = INSTRUCTION_TOP + (k + 0.8) * leading
        text(x0 + 2, base, number, size, colour=ink)
        text(x0 + 6, base, line, size, colour=ink)
    c.setStrokeColor(ink)
    c.setLineWidth(LINE * mm)
    c.line(x0 * mm, y(y1 - 11.5), x1 * mm, y(y1 - 11.5))
    quarter = (x1 - x0) / 4
    text(x0 + quarter, y1 - 7.7, "Incorrect fill", 8, colour=ink, align="centre")
    text(x1 - quarter, y1 - 7.7, "Correct fill", 8, colour=ink, align="centre")
    bw, bh = t.bubble
    ey = y1 - 3.7
    for k, (letter, mark) in enumerate((("A", ""), ("B", "cross"), ("C", "tick"), ("D", "half"))):
        cx = x0 + quarter + (k - 1.5) * (bw + 2.5)
        pill(cx, ey, "" if mark == "half" else letter)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.35 * mm)
        if mark == "cross":
            c.line((cx - bw / 3) * mm, y(ey - bh * 0.6), (cx + bw / 3) * mm, y(ey + bh * 0.6))
            c.line((cx - bw / 3) * mm, y(ey + bh * 0.6), (cx + bw / 3) * mm, y(ey - bh * 0.6))
        elif mark == "tick":
            path = c.beginPath()
            path.moveTo((cx - bw / 2.5) * mm, y(ey))
            path.lineTo((cx - bw / 8) * mm, y(ey + bh * 0.55))
            path.lineTo((cx + bw / 2) * mm, y(ey - bh * 0.7))
            c.drawPath(path, stroke=1, fill=0)
        elif mark == "half":
            c.setFillColor(colors.black)
            c.circle((cx - bw / 5) * mm, y(ey), bh * 0.42 * mm, stroke=0, fill=1)
    for k, letter in enumerate("ABCD"):
        cx = x1 - quarter + (k - 1.5) * (bw + 2.5)
        pill(cx, ey, "" if k == 2 else letter, colors.black if k == 2 else None)

    # Signatures and the question set.
    for (sx0, sy0, sx1, sy1), label in zip(hd["signatures"], ("Signature of invigilator", "Signature of student")):
        box(sx0, sy0, sx1, sy1)
        box(sx0, sy1 - 4, sx1, sy1, fill=band)
        text((sx0 + sx1) / 2, sy1 - 1.15, label, 6, BOLD, align="centre")
    sets = next((g for g in t.grids if g.kind == "set_code"), None)
    if sets:
        sx0, sy0, sx1, sy1 = hd["sets"]
        box(sx0, sy0, sx1, sy1)
        label_bottom = sy1 if sets.cols <= 4 else sy0 + 6
        box(sx0, sy0, sx0 + 26, label_bottom, fill=band)
        text(sx0 + 13, (sy0 + label_bottom) / 2 + 1.1, "QUESTION SET", 7.5, BOLD, align="centre")
        box(sx0 + 27.5, sy0 + 1.2, sx0 + 33.5, label_bottom - 1.2, width=0.2)  # write the set letter here
        for col in range(sets.cols):
            pill(*sets.centre(0, col), sets.options[col])

    # Question columns: a border, the number cell, banded rows and the bubbles.
    headings = {sec["first"]: sec["name"] for sec in template.get("sections", [])}
    head = BAND if headings else 0
    questions = [g for g in t.grids if g.kind == "questions"]
    rows = max(g.rows for g in questions)
    for g in questions:
        option, pitch = g.pitch
        x0 = g.origin[0] - option / 2 - NUMBER_W
        x1 = x0 + NUMBER_W + option * g.cols
        top = g.origin[1] - pitch / 2 - head
        bottom = top + head + rows * pitch + 0.5
        for r in range(0, g.rows, 2):
            ry = g.origin[1] - pitch / 2 + r * pitch
            box(x0, ry, x1, ry + pitch, fill=stripe, stroke=False)
        box(x0, top, x1, bottom)
        c.line((x0 + NUMBER_W) * mm, y(top + head), (x0 + NUMBER_W) * mm, y(bottom))
        if head:
            section = max((f for f in headings if f <= g.first), default=None)
            banded(x0, top, x1, headings.get(section, ""), 7.5)
        for r in range(g.rows):
            cy = g.centre(r, 0)[1]
            text(x0 + 1, cy + 1.2, str(g.first + r), 8.5 if pitch >= 4.2 else 7.5, BOLD)
            for col in range(g.cols):
                pill(g.centre(r, col)[0], cy, g.options[col])
    text(w / 2, h - 5, "Fill one bubble fully with a dark pen. Do not fold the sheet or mark the corners.", 7,
         colour=ink, align="centre")
    c.showPage()
    c.save()


def _mix(colour: colors.Color, share: float) -> colors.Color:
    """The colour diluted with white, `share` being how much of the colour is left."""
    return colors.Color(*(1 - share + share * v for v in (colour.red, colour.green, colour.blue)))


def _readable(colour: colors.Color) -> colors.Color:
    """The colour for letters inside bubbles: as chosen, or lightened when it is nearly as dark as a pen mark.

    The reader looks inside each bubble, where the letter is, so a very dark letter could look partly filled.
    """
    grey = 0.299 * colour.red + 0.587 * colour.green + 0.114 * colour.blue
    return colour if grey >= LIGHTEST_LETTER else _mix(colour, (1 - LIGHTEST_LETTER) / (1 - grey))


def render(template: dict, dpi: int = 200) -> np.ndarray:
    """The printed sheet as a BGR image, for the preview and for tests."""
    buf = io.BytesIO()
    write_pdf(template, buf)
    pdf = pdfium.PdfDocument(buf.getvalue())
    try:
        return pdf[0].render(scale=dpi / 72).to_numpy().copy()  # pdfium renders BGR
    finally:
        pdf.close()
