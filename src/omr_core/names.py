"""The student's name as written in block letters, one letter a box, read as a suggestion for a person to confirm.

Only sheets made here have name boxes the reader knows the place of. Each box is cut out of the aligned page,
its printed outline taken away and the ink scaled to a small square; a small network (two layers on the
letter's shape) names the letter. The network is trained on open-licence handwriting fonts by
tools/train_letters.py, never on students' sheets.

A name read this way is never trusted on its own: it is shown as a suggestion, matched against the student
directory where one is set up, and kept only when a person confirms it.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .reader import SCALE
from .students import Student, same_roll
from .template import Template

SIZE = 28  # the letter is scaled into a square this many pixels wide
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MIN_INK = 0.02  # share of a box that must be ink for it to hold a letter
MODEL = Path(__file__).with_name("letters.npz")


@dataclass(frozen=True)
class Word:
    text: str
    sure: float  # the least sure letter's probability, 0 to 1


def normalise(crop: np.ndarray, margin: int) -> np.ndarray | None:
    """The letter in one box as a SIZE x SIZE float image, ink 1 on paper 0, or None for an empty box.

    `crop` is the box with `margin` pixels of page around it on every side, so a letter that runs over the
    box's edge is still whole."""
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ink = (gray < min(160, cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0])).astype(np.uint8)
    h, w = ink.shape
    # The printed box: rows and columns near its sides that are mostly ink (a letter's own stroke doesn't run
    # the whole way across). The page can stretch a little, so each side is looked for, not assumed.
    sides = []
    for profile, size in ((ink.mean(1), h), (ink.mean(0), w)):
        lines = np.flatnonzero(profile > 0.6)
        first = lines[lines < 2 * margin]
        last = lines[lines >= size - 2 * margin]
        sides.append((first.max() + 1 if len(first) else margin, last.min() if len(last) else size - margin))
        for i in np.concatenate([first, last]):
            if size == h:
                ink[i] = 0
            else:
                ink[:, i] = 0
    (top, bottom), (left, right) = sides
    # Keep the strokes that reach well into the box; what's left of its sides, and a neighbour's letter running
    # over the edge, don't.
    count, parts, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    core = np.zeros(ink.shape, bool)
    core[top + 3:bottom - 3, left + 3:right - 3] = True
    keep = np.zeros_like(ink)
    for i in range(1, count):
        part = parts == i
        if stats[i, cv2.CC_STAT_AREA] >= 6 and (part & core).sum() >= 0.3 * stats[i, cv2.CC_STAT_AREA]:
            keep[part] = 1
    if keep[top:bottom, left:right].mean() < MIN_INK:
        return None
    ys, xs = np.nonzero(keep)
    if len(xs) < 8:
        return None
    letter = keep[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
    side = max(letter.shape)
    square = np.zeros((side, side), np.float32)
    y0, x0 = (side - letter.shape[0]) // 2, (side - letter.shape[1]) // 2
    square[y0:y0 + letter.shape[0], x0:x0 + letter.shape[1]] = letter
    inner_size = SIZE - 4
    small = cv2.resize(square, (inner_size, inner_size), interpolation=cv2.INTER_AREA)
    return cv2.copyMakeBorder(small, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=0)


def features(letters: np.ndarray) -> np.ndarray:
    """The shape of each letter (n, SIZE, SIZE): which way its strokes run in each 7-pixel cell (9 directions,
    normalised over 2 x 2 cells), and the letter at half size."""
    n = len(letters)
    gx = np.stack([cv2.Sobel(im, cv2.CV_32F, 1, 0) for im in letters])
    gy = np.stack([cv2.Sobel(im, cv2.CV_32F, 0, 1) for im in letters])
    strength = np.hypot(gx, gy)
    direction = np.minimum((np.arctan2(gy, gx) % np.pi) / np.pi * 9, 8).astype(int)
    cells = SIZE // 7
    hist = np.zeros((n, cells, cells, 9), np.float32)
    for b in range(9):
        hist[..., b] = (strength * (direction == b)).reshape(n, cells, 7, cells, 7).sum((2, 4))
    blocks = [hist[:, y:y + 2, x:x + 2].reshape(n, -1) for y in range(cells - 1) for x in range(cells - 1)]
    blocks = [b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-3) for b in blocks]
    small = np.stack([cv2.resize(im, (14, 14), interpolation=cv2.INTER_AREA).ravel() for im in letters])
    return np.concatenate(blocks + [small], 1).astype(np.float32)


_net = None


def letter_odds(letters: np.ndarray) -> np.ndarray:
    """Each letter's probability of being A to Z, shape (n, 26)."""
    global _net
    if _net is None:
        _net = dict(np.load(MODEL))
    n = _net
    x = (features(letters) - n["mean"]) / n["std"]
    hidden = np.maximum(x @ n["w1"].astype(np.float32) + n["b1"], 0)
    z = hidden @ n["w2"].astype(np.float32) + n["b2"]
    z = np.exp(z - z.max(1, keepdims=True))
    return z / z.sum(1, keepdims=True)


GAP = -np.log(0.02)  # the cost of a letter read that the name doesn't have, or the other way round


def fit(words: list[np.ndarray], name: str) -> float:
    """How well a name fits the letters read, as the average cost per letter (lower is better): `words` holds
    the odds (letters, 26) of each word's boxes, in order. Words are compared in order; a word the name has and
    the sheet doesn't (or the other way round) costs its letters."""
    have = [w for w in words if len(w)]
    want = [w for w in name.upper().split() if w]
    if not have or not want:
        return np.inf
    cost = -np.log(np.clip(np.concatenate(have), 1e-6, 1))  # (letters read, 26)
    want_text = "".join(want)
    n, m = len(cost), len(want_text)
    # Edit distance between the letters read and the name's letters, ignoring where words break.
    d = np.full((n + 1, m + 1), np.inf)
    d[0] = np.arange(m + 1) * GAP
    d[:, 0] = np.arange(n + 1) * GAP
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            k = LETTERS.find(want_text[j - 1])
            here = cost[i - 1, k] if k >= 0 else GAP
            d[i, j] = min(d[i - 1, j - 1] + here, d[i - 1, j] + GAP, d[i, j - 1] + GAP)
    words_off = abs(len(have) - len(want))
    return float(d[n, m] + words_off * GAP) / max(n, m)


SURE, CLEAR = 2.3, 0.3
FEW = 25  # a name fits when it costs less than SURE a letter, and CLEAR less than the next best


def read_name(aligned: np.ndarray, t: Template) -> list[dict[str, float]]:
    """The odds of each letter written in the sheet's name boxes, word by word: a word is a list of
    {letter: probability}, leaving out the unlikely ones; [] when the sheet has no name boxes."""
    out = []
    margin = SCALE
    for word in t.names:
        letters = []
        for x, y, w, h in word:
            x0, y0 = round(x * SCALE) - margin, round(y * SCALE) - margin
            crop = aligned[max(y0, 0):round((y + h) * SCALE) + margin, max(x0, 0):round((x + w) * SCALE) + margin]
            if x0 >= 0 and y0 >= 0 and (m := normalise(crop, margin)) is not None:
                letters.append(m)
        odds = letter_odds(np.array(letters)) if letters else np.zeros((0, 26))
        out.append([{LETTERS[i]: round(float(p), 3) for i, p in enumerate(row) if p >= 0.01} for row in odds])
    return out


def _arrays(words: list[list[dict[str, float]]]) -> list[np.ndarray]:
    return [np.array([[odds.get(c, 0.001) for c in LETTERS] for odds in word]).reshape(-1, 26) for word in words]


def as_text(words: list[list[dict[str, float]]]) -> str:
    """The likeliest reading, e.g. "ASHA RAI"."""
    return " ".join("".join(max(odds, key=odds.get) for odds in word if odds) for word in words if word)


def matches(roll: str, pattern: str) -> bool:
    """Whether a student's roll number fits one read with unclear digits ('?')."""
    if "?" not in pattern:
        return same_roll(roll) == same_roll(pattern)
    roll = roll.zfill(len(pattern)) if roll.isdigit() else roll
    return len(roll) == len(pattern) and all(p in ("?", r) for p, r in zip(pattern, roll))


def suggest(words: list[list[dict[str, float]]], students: list[Student], roll: str = "") -> Student | None:
    """The student whose name the writing fits, among those whose roll number fits `roll` when one is given;
    None unless one fits clearly better than the rest."""
    odds = _arrays(words)
    if not any(len(w) for w in odds):
        return None
    fits = [i for i, s in enumerate(students) if not roll or matches(s.roll_number, roll)]
    # A quick first pass: how likely each name's letters are anywhere in the writing. Only the closest few are
    # aligned letter by letter, which takes longer.
    best = -np.log(np.clip(np.concatenate([w for w in odds if len(w)]).max(0), 1e-6, 1))
    rough = sorted(fits, key=lambda i: np.mean([best[LETTERS.index(c)] if c in LETTERS else GAP
                                                 for c in students[i].name.upper() if c != " "] or [GAP]))
    scored = sorted(((fit(odds, students[i].name), i) for i in rough[:FEW]), key=lambda c: c[0])
    if not scored or scored[0][0] >= SURE or len(scored) > 1 and scored[1][0] - scored[0][0] < CLEAR:
        return None
    return students[scored[0][1]]
