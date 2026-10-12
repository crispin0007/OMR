"""Read one page: prepare, align, read bubbles, decide (Constitution III, IV).

Every page source hands a BGR or grayscale NumPy image to `read_page`. The
engine never guesses: anything unclear comes back as a flag for review.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

from .template import Grid, Template

SCALE = 8  # pixels per mm in the aligned page, about 203 DPI
MIN_MARKER_SCORE = 0.3
SNAP_MM = 1.5  # how far a printed bubble may sit from its template position
MIN_RING_INK = 0.15  # share of a bubble-sized ring that must be ink for that bubble to vote
MIN_GAP = 0.25  # darkness between empty and filled bubbles when a sheet has few or no marks
FILLED, UNCLEAR = 0.45, 0.2  # share of that gap above the empty level
MIN_COVER = 0.75  # share of a filled bubble's inside that must be ink


class UnreadablePage(Exception):
    """The page can't be read at all (no markers, wrong orientation); keep it for review."""


@dataclass
class PageResult:
    roll_number: str = ""
    set_code: str = ""
    answers: dict[int, str] = field(default_factory=dict)
    flags: list[tuple[str, str]] = field(default_factory=list)  # (where, why)
    aligned: np.ndarray | None = None  # page in template coordinates, for the review screen


def read_page(page: np.ndarray, template: Template) -> PageResult:
    gray = _prepare(page, template.dropout)
    aligned = _flatten(_align(gray, template))
    pixels = [_sample(aligned, g, template.bubble) for g in template.grids]
    empty, gap = _levels(np.concatenate([p.mean(-1).ravel() for p in pixels]))
    result = PageResult(aligned=aligned)
    for grid, p in zip(template.grids, pixels):
        darkness = p.mean(-1)
        covered = (p > empty + gap / 2).mean(-1)  # a half-filled bubble can be as dark on average as a light full one
        filled = (darkness >= empty + FILLED * gap) & (covered >= MIN_COVER)
        unclear = (darkness > empty + UNCLEAR * gap) & ~filled
        if grid.kind == "questions":
            for r in range(grid.rows):
                q = grid.first + r
                result.answers[q] = "".join(o for o, f in zip(grid.options, filled[r]) if f)
                if unclear[r].any():
                    result.flags.append((f"Q{q}", "unclear mark"))
                elif len(result.answers[q]) > 1 and not grid.multi:
                    result.flags.append((f"Q{q}", "multiple marks"))
        elif grid.kind == "roll_number":
            result.roll_number = "".join(
                _single(result, filled[:, c], unclear[:, c], "0123456789", f"roll number digit {c + 1}")
                for c in range(grid.cols))
        else:
            result.set_code = _single(result, filled[0], unclear[0], grid.options, "set code")
    return result


def _single(result: PageResult, filled, unclear, labels: str, where: str) -> str:
    """One choice from a column; '?' and a flag when it isn't exactly one clear mark."""
    if unclear.any():
        result.flags.append((where, "unclear mark"))
    elif filled.sum() == 1:
        return labels[int(filled.argmax())]
    else:
        result.flags.append((where, "blank" if not filled.any() else "multiple marks"))
    return "?"


def _prepare(page: np.ndarray, dropout: str | None) -> np.ndarray:
    if page.ndim == 2:
        return page
    # Pink or red print is near white in the red channel, so only pen marks stay dark.
    return page[:, :, 2].copy() if dropout == "red" else cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)


def _align(gray: np.ndarray, t: Template) -> np.ndarray:
    """Warp the page so template millimetres map to SCALE pixels each."""
    found = _find_markers(gray, t)
    size = (round(t.page[0] * SCALE), round(t.page[1] * SCALE))
    for turn in (0, 2):  # upright, then upside down (markers swap TL<->BR, TR<->BL)
        dst = np.float32(t.markers[turn:] + t.markers[:turn]) * SCALE
        warp = cv2.getPerspectiveTransform(np.float32(found), dst)
        aligned = cv2.warpPerspective(gray, warp, size, flags=cv2.INTER_AREA, borderValue=255)
        if t.orientation is None:
            return aligned  # shortcut: without an orientation mark an upside-down page is not detected
        x, y, w, h = (round(v * SCALE) for v in t.orientation)
        if aligned[y:y + h, x:x + w].mean() < 128:
            return aligned
    raise UnreadablePage("orientation mark not found")


def _flatten(aligned: np.ndarray) -> np.ndarray:
    """Divide out uneven lighting (shadows, photocopier fade) so paper is white everywhere."""
    small = cv2.resize(aligned, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)  # lighting changes slowly
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * SCALE, 2 * SCALE))  # 8 mm at full size, wider than any bubble
    paper = cv2.GaussianBlur(cv2.dilate(small, k), (0, 0), SCALE)
    paper = cv2.resize(paper, (aligned.shape[1], aligned.shape[0]), interpolation=cv2.INTER_LINEAR)
    return cv2.divide(aligned, np.maximum(paper, 1), scale=255)


def _find_markers(gray: np.ndarray, t: Template) -> list[tuple[float, float]]:
    """Centre of each registration mark, searched near where the template puts it."""
    s = gray.shape[1] / t.page[0]  # rough px per mm, assuming the scan is cropped to the page
    d = t.marker_size * s
    pad = int(d)
    padded = cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    radius = int(0.15 * gray.shape[1])
    found = []
    for mx, my in t.markers:
        cx, cy = int(mx * s) + pad, int(my * s) + pad
        x0, y0 = max(cx - radius, 0), max(cy - radius, 0)
        roi = padded[y0:cy + radius, x0:cx + radius]
        best = (MIN_MARKER_SCORE, None)
        for k in (0.8, 0.9, 1.0, 1.1, 1.25):  # the scan's scale is only a guess
            mark = _marker_image(t.marker_shape, d * k)
            if roi.shape[0] < mark.shape[0] or roi.shape[1] < mark.shape[1]:
                continue
            score = cv2.matchTemplate(roi, mark, cv2.TM_CCOEFF_NORMED)
            half = mark.shape[0] // 2
            ys, xs = np.mgrid[0:score.shape[0], 0:score.shape[1]]
            px, py = xs + x0 + half - pad, ys + y0 + half - pad
            score[(px < 0) | (py < 0) | (px >= gray.shape[1]) | (py >= gray.shape[0])] = -1  # centre must be on the page
            _, m, _, (lx, ly) = cv2.minMaxLoc(score)
            if m > best[0]:
                best = (m, (lx + x0 + half - pad, ly + y0 + half - pad))
        if best[1] is None:
            raise UnreadablePage("registration mark not found")
        found.append(best[1])
    if len(set(found)) < 4:
        raise UnreadablePage("registration marks overlap")
    return found


def _marker_image(shape: str, d: float) -> np.ndarray:
    size = int(d * 1.5) | 1
    img = np.full((size, size), 255, np.uint8)
    c = size // 2
    if shape == "square":
        h = int(d / 2)
        img[c - h:c + h + 1, c - h:c + h + 1] = 0
    else:  # target rings: outer ring, inner ring, centre dot
        cv2.circle(img, (c, c), int(d * 0.44), 0, max(1, int(d * 0.12)))
        cv2.circle(img, (c, c), int(d * 0.25), 0, max(1, int(d * 0.08)))
        cv2.circle(img, (c, c), max(1, int(d * 0.08)), 0, -1)
    return cv2.GaussianBlur(img, (0, 0), max(d * 0.05, 0.5))


def _sample(aligned: np.ndarray, grid: Grid, bubble: tuple[float, float]) -> np.ndarray:
    """Darkness 0 (paper) to 1 (ink) of the pixels inside each bubble, skipping its printed outline.

    Shape (rows, cols, pixels).
    """
    ax, ay = max(1, int(bubble[0] * SCALE * 0.3)), max(1, int(bubble[1] * SCALE * 0.3))
    mask = np.zeros((2 * ay + 1, 2 * ax + 1), np.uint8)
    cv2.ellipse(mask, (ax, ay), (ax, ay), 0, 0, 360, 1, -1)
    mask = mask.astype(bool)
    out = np.empty((grid.rows, grid.cols, int(mask.sum())))
    for r in range(grid.rows):
        centres = [tuple(round(v * SCALE) for v in grid.centre(r, c)) for c in range(grid.cols)]
        dx, dy = _row_offset(aligned, centres, bubble)
        for c, (x, y) in enumerate(centres):
            x, y = x + dx, y + dy
            out[r, c] = 1 - aligned[y - ay:y + ay + 1, x - ax:x + ax + 1][mask] / 255
    return out


def _row_offset(aligned: np.ndarray, centres: list[tuple[int, int]], bubble: tuple[float, float]) -> tuple[int, int]:
    """Where this row's printed bubbles really are, within SNAP_MM of the template.

    Paper stretch, curl and scanner drift move rows by a millimetre or two. Each
    empty bubble votes with where a bubble-sized ring finds the most ink, its
    printed outline. Marked bubbles don't vote (a pen mark rarely matches the
    bubble's shape), nor do outlines too faint to see (dropped-out print).
    """
    w, h = round(bubble[0] * SCALE), round(bubble[1] * SCALE)
    ring = np.zeros((h + 2, w + 2), np.float32)
    cv2.ellipse(ring, (w // 2 + 1, h // 2 + 1), (w // 2, h // 2), 0, 0, 360, 1, max(1, round(h * 0.15)))
    full = ring.sum() * 255
    reach = round(SNAP_MM * SCALE)
    offsets = []
    for x, y in centres:
        x0, y0 = x - ring.shape[1] // 2 - reach, y - ring.shape[0] // 2 - reach
        roi = aligned[max(y0, 0):y0 + ring.shape[0] + 2 * reach, max(x0, 0):x0 + ring.shape[1] + 2 * reach]
        if x0 < 0 or y0 < 0 or roi.shape[0] < ring.shape[0] + 2 * reach or roi.shape[1] < ring.shape[1] + 2 * reach:
            continue  # bubble too close to the page edge to search around
        inside = roi[reach + ring.shape[0] // 4:reach + ring.shape[0] * 3 // 4,
                     reach + ring.shape[1] // 4:reach + ring.shape[1] * 3 // 4]
        if inside.mean() < 160:
            continue  # marked
        ink = cv2.matchTemplate((255 - roi).astype(np.float32), ring, cv2.TM_CCORR)
        _, best, _, (lx, ly) = cv2.minMaxLoc(ink)
        if best >= MIN_RING_INK * full:
            offsets.append((lx - reach, ly - reach))
    if not offsets:
        return 0, 0
    dx, dy = np.median(offsets, axis=0)
    return int(round(dx)), int(round(dy))


def _levels(values: np.ndarray) -> tuple[float, float]:
    """This sheet's own empty level and the gap up to its filled level, so pens of any darkness read."""
    empty = float(np.median(values))  # most bubbles on a sheet are empty
    return empty, max(float(np.percentile(values, 99)) - empty, MIN_GAP)
