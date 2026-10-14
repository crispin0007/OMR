"""Read one page: prepare, align, read bubbles, decide (Constitution III, IV).

Every page source hands a BGR or grayscale NumPy image to `read_page`. The
engine never guesses: anything unclear comes back as a flag for review.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np
import zxingcpp

from .template import DIGITS, Grid, Template

SCALE = 8  # pixels per mm in the aligned page, about 203 DPI
MIN_MARKER_SCORE = 0.3
MARKED = 0.75  # a bubble whose inside is darker than this share of its row's lightest is taken as marked
SNAP_MM = 1.5  # how far a printed bubble may sit from where the row before it was found
MAX_DRIFT_MM = 3.0  # how far a row may drift from its template position in all
MIN_RING_INK = 0.15  # share of a bubble-sized ring that must be ink for that bubble to vote
MIN_GAP = 0.25  # darkness between empty and filled bubbles when a sheet has few or no marks
FILLED, UNCLEAR = 0.45, 0.2  # share of that gap above the empty level
MIN_COVER = 0.75  # share of a filled bubble's inside that must be ink
CUT_MM = 0.5  # a corner mark closer than this to the scan's edge may be cut off
CUT_MARK = "a corner mark is cut off at the edge of the scan"
MAX_SKEW_MM = 1.5  # how far a corner mark may sit from where the other three put it (tilt, stretch, phone angle)
MAX_LOST_ROWS = 0.25  # share of bubble rows found only at the edge of the search before the page counts as misaligned


class UnreadablePage(Exception):
    """The page can't be read at all (no markers, wrong orientation); keep it for review."""


@dataclass
class PageResult:
    roll_number: str = ""
    set_code: str = ""
    answers: dict[int, str] = field(default_factory=dict)
    flags: list[tuple[str, str]] = field(default_factory=list)  # (where, why)
    aligned: np.ndarray | bytes | None = None  # page in template coordinates, for review; bytes once encoded to save
    serial: str = ""  # the sheet number printed on the sheet, "?" when it can't be read; "" for sheets without one
    name: list = field(default_factory=list)  # the odds of each letter in the name boxes, as names.read_name gives


def read_page(page: np.ndarray, template: Template) -> PageResult:
    gray = _prepare(page, template.dropout)
    warped = _align(gray, template)
    try:
        aligned, sampled = _lined_up(warped, template)
    except UnreadablePage as shifted:
        # What was found near the marks' places may be something else, such as the dark table around a sheet
        # photographed with room to spare: look for the marks anywhere before giving up.
        try:
            warped = _warp(gray, template, _whole(gray, template, _markers_anywhere(gray, template)))
            aligned, sampled = _lined_up(warped, template)
        except UnreadablePage:
            raise shifted from None
    pixels = [p for p, _ in sampled]
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
        elif grid.kind == "numeric":
            result.answers[grid.first] = _number(result, filled, unclear, f"Q{grid.first}")
        elif grid.kind == "roll_number":
            result.roll_number = "".join(
                _single(result, filled[:, c], unclear[:, c], "0123456789", f"roll number digit {c + 1}")
                for c in range(grid.cols))
            _from_the_left(result, grid.cols)
        else:
            result.set_code = _single(result, filled[0], unclear[0], grid.options, "set code")
    if template.barcode:
        _identify(result, _barcode(warped, template.barcode), any(g.kind == "roll_number" for g in template.grids))
    if template.serial:
        result.serial = _barcode(warped, template.serial) or "?"
    if template.names:
        from .names import read_name  # it reads with this module's scale
        result.name = read_name(aligned, template)
    return result


def _lined_up(warped: np.ndarray, template: Template) -> tuple[np.ndarray, list]:
    """The flattened page and every grid sampled, when the bubbles are where the corner marks put them."""
    aligned = _flatten(warped)
    sampled = [_sample(aligned, g, template.bubble) for g in template.grids]
    if sum(lost for _, lost in sampled) > MAX_LOST_ROWS * sum(g.rows for g in template.grids):
        # the corner marks were found but don't match where the bubbles are printed: reading on would
        # read the whole page shifted
        raise UnreadablePage("the bubbles don't line up with the corner marks (a corner may be cut off or folded)")
    return aligned, sampled


def read_or_reason(page: np.ndarray, template: Template) -> tuple[PageResult | None, str]:
    """The page read, or None and why it can't be read, for pages to be kept either way."""
    try:
        return read_page(page, template), ""
    except UnreadablePage as e:
        return None, f"unreadable: {e}"


def _barcode(page: np.ndarray, area: tuple[float, float, float, float]) -> str:
    """The text of the barcode or QR code in an area of the aligned page, or "" if none can be read."""
    x, y, w, h = (round(v * SCALE) for v in area)
    found = zxingcpp.read_barcodes(np.ascontiguousarray(page[y:y + h, x:x + w]))
    texts = {b.text.strip() for b in found if b.valid and b.text.strip()}
    return texts.pop() if len(texts) == 1 else ""  # two different codes in one area is not a reading


def _identify(result: PageResult, code: str, has_grid: bool):
    """The barcode is the roll number; with a roll number grid too, the two must agree."""
    if not has_grid:
        result.roll_number = code or "?"
        if not code:
            result.flags.append(("roll number", "barcode not readable"))
    elif code and code != result.roll_number and "?" not in result.roll_number:
        result.flags.append(("roll number", f"barcode says {code}"))


def _number(result: PageResult, filled, unclear, where: str) -> str:
    """A numeric answer from its digit columns: the digits filled, read left to right, blank columns on either
    side left out. A column that isn't one clear digit, or a blank column between digits, shows as '?' and is
    flagged, as the number can't be known without a person."""
    columns = ["".join(d for d, f in zip(DIGITS, filled[:, c]) if f) for c in range(filled.shape[1])]
    while columns and not columns[-1]:
        columns.pop()
    while columns and not columns[0]:
        columns.pop(0)
    digits = "".join(c if len(c) == 1 else "?" for c in columns)
    if unclear.any():
        result.flags.append((where, "unclear mark"))
    elif any(len(c) > 1 for c in columns):
        result.flags.append((where, "multiple marks"))
    elif "?" in digits:
        result.flags.append((where, "gap between digits"))
    return digits if "?" in digits or not digits else str(int(digits))


def _from_the_left(result: PageResult, digits: int):
    """A roll number written from the left with the last columns left empty ("195" in a five-digit grid) is
    the number with its leading zeros, 00195. Still flagged, once, for a person to confirm."""
    roll = result.roll_number
    lead = roll.rstrip("?")
    blank = {f"roll number digit {c + 1}" for c in range(len(lead), digits)}
    if not lead or len(lead) == digits or "?" in lead or blank - {w for w, why in result.flags if why == "blank"}:
        return
    result.roll_number = lead.zfill(digits)
    result.flags = [f for f in result.flags if f[0] not in blank]
    result.flags.append(("roll number", f"filled from the left: read as {result.roll_number}"))


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
    """Warp the page so template millimetres map to SCALE pixels each.

    Everything after this works in the template's millimetres, so a sheet printed smaller, larger or on
    other paper reads the same once its four corner marks are found.
    """
    try:
        return _warp(gray, t, _whole(gray, t, _markers_near(gray, t)))
    except UnreadablePage as near:  # printed at another size or on other paper: look further for the marks
        try:
            return _warp(gray, t, _whole(gray, t, _markers_anywhere(gray, t)))
        except UnreadablePage as anywhere:
            raise near if str(near) == CUT_MARK else anywhere  # say what to fix: the cut corner


def _whole(gray: np.ndarray, t: Template, found: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The marks found, unless one is cut off at the scan's edge and found out of line with the others.

    Half a mark still matches, a few millimetres off its centre, and the whole page would then be read
    shifted. A mark at the edge that lines up with the other three (a scan cropped close) is kept.
    """
    src = np.hstack([np.float64(t.markers), np.ones((4, 1))])
    fit, *_ = np.linalg.lstsq(src, np.float64(found), rcond=None)  # the straight (affine) fit of all four
    s = np.sqrt(abs(np.linalg.det(fit[:2])))  # px per mm
    off = np.hypot(*(src @ fit - np.float64(found)).T) / s
    h, w = gray.shape
    edge = [min(x, y, w - x, h - y) / s - t.marker_size / 2 for x, y in found]
    if any(e < CUT_MM for e in edge) and off.max() > MAX_SKEW_MM:
        raise UnreadablePage(CUT_MARK)
    return found


def _warp(gray: np.ndarray, t: Template, found: list[tuple[float, float]]) -> np.ndarray:
    size = (round(t.page[0] * SCALE), round(t.page[1] * SCALE))
    for turn in (0, 2):  # upright, then upside down (markers swap TL<->BR, TR<->BL)
        dst = np.float32(t.markers[turn:] + t.markers[:turn]) * SCALE
        warp = cv2.getPerspectiveTransform(np.float32(found), dst)
        aligned = cv2.warpPerspective(gray, warp, size, flags=cv2.INTER_AREA, borderValue=255)
        if t.orientation is None:
            return aligned  # shortcut: without an orientation mark an upside-down page is not detected
        if _bar_is_there(aligned, t.orientation):
            return aligned
    raise UnreadablePage("orientation mark not found")


def _bar_is_there(aligned: np.ndarray, bar: tuple[float, float, float, float]) -> bool:
    """Whether the orientation bar is printed here: much darker than the paper around it.

    Compared with the paper around it rather than a fixed level, so a dim phone photo of a sheet without
    the bar (another layout) is not taken for one with it.
    """
    x, y, w, h = (round(v * SCALE) for v in bar)
    m = round(3 * SCALE)  # 3 mm of paper all round
    around = aligned[max(y - m, 0):y + h + m, max(x - m, 0):x + w + m]
    paper = np.percentile(around, 90)
    return aligned[y:y + h, x:x + w].mean() < min(128, 0.6 * paper)


def _flatten(aligned: np.ndarray) -> np.ndarray:
    """Divide out uneven lighting (shadows, photocopier fade) so paper is white everywhere."""
    small = cv2.resize(aligned, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)  # lighting changes slowly
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * SCALE, 2 * SCALE))  # 8 mm at full size, wider than any bubble
    paper = cv2.GaussianBlur(cv2.dilate(small, k), (0, 0), SCALE)
    paper = cv2.resize(paper, (aligned.shape[1], aligned.shape[0]), interpolation=cv2.INTER_LINEAR)
    return cv2.divide(aligned, np.maximum(paper, 1), scale=255)


def _markers_anywhere(gray: np.ndarray, t: Template) -> list[tuple[float, float]]:
    """Each mark searched in its quarter of the page at any print size from half to one and a half times,
    first on a small copy, then refined at full size.

    The four marks are printed the same size, so the size is the one that matches all four best: a small
    blob such as a filled bubble can look like one mark at a small size, but not like all four.
    """
    shrink = 4
    small = cv2.resize(gray, None, fx=1 / shrink, fy=1 / shrink, interpolation=cv2.INTER_AREA)
    s = gray.shape[1] / t.page[0]  # px per mm if the sheet filled the page's width
    h, w = small.shape
    corners = [((0 if mx < t.page[0] / 2 else w // 2), (0 if my < t.page[1] / 2 else h // 2)) for mx, my in t.markers]
    best = (MIN_MARKER_SCORE, None, s)
    for k in np.geomspace(0.5, 1.6, 11):
        mark = _marker_image(t.marker_shape, t.marker_size * s * k / shrink)
        half = mark.shape[0] // 2
        scores, spots = [], []
        for x0, y0 in corners:
            roi = small[y0:y0 + h // 2 + h % 2, x0:x0 + w // 2 + w % 2]
            if roi.shape[0] < mark.shape[0] or roi.shape[1] < mark.shape[1]:
                break
            _, m, _, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(roi, mark, cv2.TM_CCOEFF_NORMED))
            scores.append(m)
            spots.append(((lx + x0 + half) * shrink, (ly + y0 + half) * shrink))
        if len(scores) == 4 and min(scores) > best[0] and _scale(spots, t.markers):
            best = (min(scores), spots, _scale(spots, t.markers))
    if best[1] is None:
        raise UnreadablePage("registration mark not found")
    d = t.marker_size * best[2]  # the marks' size in pixels, from how far apart they are
    r = int(d)
    found = []
    for cx, cy in best[1]:
        roi = gray[max(cy - r, 0):cy + r, max(cx - r, 0):cx + r]
        top, spot = -1.0, (cx, cy)
        for f in (0.9, 1.0, 1.1):
            mark = _marker_image(t.marker_shape, d * f)
            if roi.shape[0] < mark.shape[0] or roi.shape[1] < mark.shape[1]:
                continue
            _, m, _, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(roi, mark, cv2.TM_CCOEFF_NORMED))
            if m > top:
                half = mark.shape[0] // 2
                top, spot = m, (lx + max(cx - r, 0) + half, ly + max(cy - r, 0) + half)
        found.append(spot)
    if len(set(found)) < 4:
        raise UnreadablePage("registration marks overlap")
    return found


def _scale(found: list[tuple[float, float]], markers: list[tuple[float, float]]) -> float | None:
    """Pixels per template millimetre if four points make the marks' rectangle: every side the same
    share of its printed length, within 12% (room for tilt, fit-to-page stretch and phone angles).
    None when they don't."""
    ratios = []
    for i in range(4):
        (ax, ay), (bx, by) = found[i], found[(i + 1) % 4]
        (mx, my), (nx, ny) = markers[i], markers[(i + 1) % 4]
        ratios.append(np.hypot(bx - ax, by - ay) / np.hypot(nx - mx, ny - my))
    mean = float(np.mean(ratios))
    return mean if all(abs(r - mean) <= 0.12 * mean for r in ratios) else None


def _markers_near(gray: np.ndarray, t: Template) -> list[tuple[float, float]]:
    """Each mark searched near where the template puts it, assuming the sheet fills the page's width."""
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


def row_shifts(aligned: np.ndarray, grid: Grid, bubble: tuple[float, float]) -> tuple[list[tuple[int, int]], int]:
    """Where each row's printed bubbles were found, as (dx, dy) pixels from the template; and how many rows were
    found only at the edge of the search, or drifted further than MAX_DRIFT_MM, where a page aligned wrong puts
    them."""
    shifts, lost, dx, dy, edge = [], 0, 0, 0, round(SNAP_MM * SCALE) - 1
    for r in range(grid.rows):
        centres = [tuple(round(v * SCALE) for v in grid.centre(r, c)) for c in range(grid.cols)]
        # Each row is searched for where the row above it was found: a curled page drifts a little at a time,
        # further down the page than any one search reaches.
        sx, sy = _row_offset(aligned, [(x + dx, y + dy) for x, y in centres], bubble)
        dx, dy = dx + sx, dy + sy
        lost += max(abs(sx), abs(sy)) >= edge or max(abs(dx), abs(dy)) >= round(MAX_DRIFT_MM * SCALE)
        shifts.append((dx, dy))
    return shifts, lost


def _sample(aligned: np.ndarray, grid: Grid, bubble: tuple[float, float]) -> tuple[np.ndarray, int]:
    """Darkness 0 (paper) to 1 (ink) of the pixels inside each bubble, skipping its printed outline, shape
    (rows, cols, pixels), each row where its bubbles were found; and the rows lost, as `row_shifts` says.
    """
    ax, ay = max(1, int(bubble[0] * SCALE * 0.3)), max(1, int(bubble[1] * SCALE * 0.3))
    mask = np.zeros((2 * ay + 1, 2 * ax + 1), np.uint8)
    cv2.ellipse(mask, (ax, ay), (ax, ay), 0, 0, 360, 1, -1)
    mask = mask.astype(bool)
    out = np.empty((grid.rows, grid.cols, int(mask.sum())))
    shifts, lost = row_shifts(aligned, grid, bubble)
    for r, (dx, dy) in enumerate(shifts):
        for c in range(grid.cols):
            x, y = (round(v * SCALE) for v in grid.centre(r, c))
            out[r, c] = 1 - aligned[y + dy - ay:y + dy + ay + 1, x + dx - ax:x + dx + ax + 1][mask] / 255
    return out, lost


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
    rois = []
    for x, y in centres:
        x0, y0 = x - ring.shape[1] // 2 - reach, y - ring.shape[0] // 2 - reach
        roi = aligned[max(y0, 0):y0 + ring.shape[0] + 2 * reach, max(x0, 0):x0 + ring.shape[1] + 2 * reach]
        if x0 < 0 or y0 < 0 or roi.shape[0] < ring.shape[0] + 2 * reach or roi.shape[1] < ring.shape[1] + 2 * reach:
            continue  # bubble too close to the page edge to search around
        inside = roi[reach + ring.shape[0] // 4:reach + ring.shape[0] * 3 // 4,
                     reach + ring.shape[1] // 4:reach + ring.shape[1] * 3 // 4]
        rois.append((roi, inside.mean()))
    # Marked is darker than the row's lightest bubble, not darker than a fixed level: a letter printed bold
    # inside every bubble makes even empty ones grey.
    lightest = max((m for _, m in rois), default=0)
    offsets = []
    for roi, inside in rois:
        if inside < MARKED * lightest:
            continue
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
