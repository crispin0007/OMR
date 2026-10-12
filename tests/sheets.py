"""Draw filled sheets from a template, with known answers, for reader tests."""

import cv2
import numpy as np

from omr_core.template import Template

INK = {"pen": 25, "pencil": 110}


def draw(t: Template, marks: dict[tuple[int, int, int], str], dpi: int = 200, print_bgr=(110, 110, 110)) -> np.ndarray:
    """A clean, upright page. `marks` maps (grid index, row, col) to "pen", "pencil" or "half"."""
    s = dpi / 25.4
    page = np.full((round(t.page[1] * s), round(t.page[0] * s), 3), 255, np.uint8)
    p = lambda x, y: (round(x * s), round(y * s))
    for mx, my in t.markers:
        h = t.marker_size / 2
        cv2.rectangle(page, p(mx - h, my - h), p(mx + h, my + h), (0, 0, 0), -1)
    if t.orientation:
        x, y, w, h = t.orientation
        cv2.rectangle(page, p(x, y), p(x + w, y + h), (0, 0, 0), -1)
    axes = p(t.bubble[0] / 2, t.bubble[1] / 2)
    for gi, g in enumerate(t.grids):
        for r in range(g.rows):
            for c in range(g.cols):
                centre = p(*g.centre(r, c))
                cv2.ellipse(page, centre, axes, 0, 0, 360, print_bgr, max(1, round(0.2 * s)))
                style = marks.get((gi, r, c))
                if style == "half":
                    cv2.ellipse(page, centre, axes, 0, 90, 270, (INK["pen"],) * 3, -1)
                elif style:
                    cv2.ellipse(page, centre, axes, 0, 0, 360, (INK[style],) * 3, -1)
    return page


def scan(page: np.ndarray, angle: float = 0, upside_down: bool = False, noise: float = 6, seed: int = 0) -> np.ndarray:
    """What a scanner returns: a little skew, noise and blur, maybe upside down."""
    h, w = page.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1)
    out = cv2.warpAffine(page, m, (w, h), borderValue=(255, 255, 255))
    if upside_down:
        out = cv2.rotate(out, cv2.ROTATE_180)
    out = cv2.GaussianBlur(out, (3, 3), 0)
    rng = np.random.default_rng(seed)
    return np.clip(out + rng.normal(0, noise, out.shape), 0, 255).astype(np.uint8)


def random_marks(t: Template, seed: int) -> tuple[dict, dict[int, str], str, str]:
    """One random pen answer per question (some blank), a roll number and a set code."""
    rng = np.random.default_rng(seed)
    marks, answers, roll, set_code = {}, {}, "", ""
    for gi, g in enumerate(t.grids):
        if g.kind == "questions":
            for r in range(g.rows):
                c = int(rng.integers(-1, g.cols))  # -1 leaves it blank
                answers[g.first + r] = g.options[c] if c >= 0 else ""
                if c >= 0:
                    marks[gi, r, c] = "pen"
        elif g.kind == "roll_number":
            for c in range(g.cols):
                d = int(rng.integers(10))
                marks[gi, d, c] = "pen"
                roll += str(d)
        else:
            c = int(rng.integers(g.cols))
            marks[gi, 0, c] = "pen"
            set_code = g.options[c]
    return marks, answers, roll, set_code
