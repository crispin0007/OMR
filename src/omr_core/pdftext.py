"""Text an institute types (names, titles, instructions, addresses) in the PDFs the app makes, in English or in
Hindi, Marathi, Nepali and the other languages written in Devanagari. Devanagari text is set in Noto Sans
Devanagari (SIL Open Font License, fonts/OFL-NotoSansDevanagari.txt) and shaped, so its letters join as they
should; any other text keeps the PDF's own font."""

import re
from pathlib import Path

from reportlab.lib.abag import ABag
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, shapeFragWord

FONTS = Path(__file__).parent / "fonts"
DEVANAGARI, DEVANAGARI_BOLD = "NotoSansDevanagari", "NotoSansDevanagari-SemiBold"


def is_devanagari(s: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" or "\ua8e0" <= ch <= "\ua8ff" or "\u1cd0" <= ch <= "\u1cff" for ch in s)


def font(s: str, latin: str) -> str:
    """The font to set `s` in, where English text is set in `latin`."""
    if not is_devanagari(s):
        return latin
    if DEVANAGARI not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(DEVANAGARI, str(FONTS / "NotoSansDevanagari-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(DEVANAGARI_BOLD, str(FONTS / "NotoSansDevanagari-SemiBold.ttf")))
    return DEVANAGARI_BOLD if "Bold" in latin else DEVANAGARI


def _shaped(s: str, latin: str, size: float) -> tuple[str, str, float]:
    """(font, text, width in points) for `s`: Devanagari shaped into its joined letters by HarfBuzz."""
    name = font(s, latin)
    if name == latin:
        return name, s, pdfmetrics.stringWidth(s, name, size)
    # The canvas only shapes with the rlbidi package as well, so the text is shaped here, a word at a time:
    # HarfBuzz guesses the script from the start of the text, and would take "Topic: गति" for English.
    text, total = "", 0.0
    for word in re.split(r"( )", s):
        w = pdfmetrics.stringWidth(word, name, size)
        if is_devanagari(word):
            shaped = shapeFragWord([w, (ABag(fontName=name, fontSize=size), word)])
            word, w = shaped[1][1], shaped[0]
        text, total = text + word, total + w
    return name, text, total


def width(s: str, latin: str, size: float) -> float:
    """How wide `s` prints, in points, as `draw` sets it."""
    return _shaped(s, latin, size)[2]


def draw(c, x: float, y: float, s: str, latin: str, size: float, align: str = "left"):
    """Set `s` on canvas `c` at (x, y) in points, aligned "left", "centre" or "right" on x."""
    name, text, w = _shaped(s, latin, size)
    c.setFont(name, size)
    c.drawString(x - {"left": 0, "centre": w / 2, "right": w}[align], y, text)


def split(s: str, latin: str, size: float, room: float) -> list[str]:
    """`s` wrapped into lines `room` points wide."""
    return simpleSplit(s, font(s, latin), size, room)
