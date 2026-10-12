"""Map an existing printed sheet into a template from a scan of it (US5).

The person clicks the four registration marks and draws a box around each
block of bubbles; these functions find the exact mark and bubble positions so
the template matches the print. Positions are millimetres, as in templates.
"""

import cv2
import numpy as np

from .reader import MIN_MARKER_SCORE, SCALE, _marker_image


def marker_at(gray: np.ndarray, x: float, y: float, px_per_mm: float) -> tuple[float, float, float, str] | None:
    """The registration mark nearest a click: centre x, y and size in pixels, and "square" or "ring".

    Tries both mark shapes at sizes from 5 to 15 mm within 10 mm of the click,
    the same matching the reader uses, so broken or faint photocopied marks
    are still found where the reader will find them.
    """
    reach = round(10 * px_per_mm)
    pad = round(8 * px_per_mm)
    padded = cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    cx, cy = round(x) + pad, round(y) + pad
    best = (MIN_MARKER_SCORE, None)
    for shape in ("square", "ring"):
        for d_mm in np.arange(5, 15.5, 0.5):  # smaller shapes match bits of print too well
            mark = _marker_image(shape, d_mm * px_per_mm)
            half = mark.shape[0] // 2
            x0, y0 = max(cx - reach - half, 0), max(cy - reach - half, 0)
            roi = padded[y0:cy + reach + half + 1, x0:cx + reach + half + 1]
            if roi.shape[0] < mark.shape[0] or roi.shape[1] < mark.shape[1]:
                continue
            score = cv2.matchTemplate(roi, mark, cv2.TM_CCOEFF_NORMED)
            _, m, _, (lx, ly) = cv2.minMaxLoc(score)
            if m > best[0]:
                best = (m, (x0 + lx + half - pad, y0 + ly + half - pad, d_mm * px_per_mm, shape))
    return best[1]


def align(gray: np.ndarray, marks_px: list[tuple[float, float]], marks_mm: list[tuple[float, float]],
          page_mm: tuple[float, float]) -> np.ndarray:
    """The scan warped so that template millimetres map to SCALE pixels, as the reader sees it."""
    warp = cv2.getPerspectiveTransform(np.float32(marks_px), np.float32(marks_mm) * SCALE)
    size = (round(page_mm[0] * SCALE), round(page_mm[1] * SCALE))
    return cv2.warpPerspective(gray, warp, size, flags=cv2.INTER_AREA, borderValue=255)


def find_bubbles(aligned: np.ndarray, box_mm: tuple[float, float, float, float]) -> tuple[list[tuple[float, float]],
                                                                                         tuple[float, float]]:
    """Centres of the bubble-shaped outlines inside a box (x0, y0, x1, y1), and the bubbles' median size, in mm."""
    x0, y0, x1, y1 = (max(0, round(v * SCALE)) for v in box_mm)
    roi = aligned[y0:y1, x0:x1]
    if roi.size == 0:
        return [], (0.0, 0.0)
    ink = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 4 * SCALE + 1, 15)
    contours, _ = cv2.findContours(ink, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for c in contours:
        bx, by, bw, bh = cv2.boundingRect(c)
        w, h = bw / SCALE, bh / SCALE
        # Bubbles on real sheets are 2 to 8 mm wide; letters inside them and grid lines are not bubble-sized.
        if not (2 <= w <= 8 and 1.5 <= h <= 6 and 0.5 <= w / h <= 3):
            continue
        # An ellipse fills about 79% of its box; write-in squares and most handwriting don't.
        if not 0.6 <= cv2.contourArea(c) / (bw * bh) <= 0.9:
            continue
        found.append(((x0 + bx + bw / 2) / SCALE, (y0 + by + bh / 2) / SCALE, w, h))
    # An outline gives an outer and an inner contour. Keep one bubble per pair; its size is the middle of
    # the printed line, halfway between the two, which is how templates measure bubbles.
    found.sort(key=lambda b: -b[2] * b[3])
    kept: list[list[float]] = []
    for b in found:
        same = next((k for k in kept if abs(b[0] - k[0]) <= 1 and abs(b[1] - k[1]) <= 1), None)
        if same is None:
            kept.append([*b, b[2], b[3]])
        elif same[4:] == same[2:4]:
            same[4:] = b[2:4]  # the inner outline
    if not kept:
        return [], (0.0, 0.0)
    size = (float(np.median([(k[2] + k[4]) / 2 for k in kept])), float(np.median([(k[3] + k[5]) / 2 for k in kept])))
    return [(k[0], k[1]) for k in kept], size


def _clusters(values: list[float], gap: float) -> list[float]:
    """Means of runs of sorted values closer together than `gap`."""
    runs: list[list[float]] = []
    for v in sorted(values):
        if runs and v - runs[-1][-1] < gap:
            runs[-1].append(v)
        else:
            runs.append([v])
    return [float(np.mean(r)) for r in runs]


def fit_grid(centres: list[tuple[float, float]], size: tuple[float, float]) -> tuple[tuple[float, float],
                                                                                     tuple[float, float], int, int]:
    """origin, pitch, rows and cols of the regular grid the bubble centres sit on.

    Raises ValueError when they don't form a grid.
    """
    if len(centres) < 2:
        raise ValueError("found fewer than 2 bubbles in the box")
    xs = _clusters([c[0] for c in centres], size[0] * 0.6)
    ys = _clusters([c[1] for c in centres], size[1] * 0.6)
    cols, rows = len(xs), len(ys)
    if len(centres) < 0.6 * rows * cols:  # faint or merged outlines on photocopies go missing
        raise ValueError(f"the bubbles don't line up in a grid ({len(centres)} found for {rows} rows x {cols} columns)")
    pitch_x = float(np.median(np.diff(xs))) if cols > 1 else 0.0
    pitch_y = float(np.median(np.diff(ys))) if rows > 1 else 0.0
    # Snap the origin to the spacing so one stray bubble doesn't shift the grid.
    ox = float(np.median([x - i * pitch_x for i, x in enumerate(xs)]))
    oy = float(np.median([y - i * pitch_y for i, y in enumerate(ys)]))
    return (round(ox, 2), round(oy, 2)), (round(pitch_x, 3), round(pitch_y, 3)), rows, cols
