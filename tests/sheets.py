"""Draw filled sheets from a template, with known answers, for reader tests."""

import cv2
import numpy as np
import zxingcpp

from omr_core.template import Template

INK = {"pen": 25, "pencil": 110}


def draw(t: Template, marks: dict[tuple[int, int, int], str], dpi: int = 200, print_bgr=(110, 110, 110),
         barcode: str = "", qr: bool = False) -> np.ndarray:
    """A clean, upright page. `marks` maps (grid index, row, col) to "pen", "pencil" or "half".

    `barcode` is printed as Code 128 (or a QR code) filling the template's barcode area.
    """
    s = dpi / 25.4
    page = np.full((round(t.page[1] * s), round(t.page[0] * s), 3), 255, np.uint8)
    p = lambda x, y: (round(x * s), round(y * s))
    for mx, my in t.markers:
        h = t.marker_size / 2
        cv2.rectangle(page, p(mx - h, my - h), p(mx + h, my + h), (0, 0, 0), -1)
    if t.orientation:
        x, y, w, h = t.orientation
        cv2.rectangle(page, p(x, y), p(x + w, y + h), (0, 0, 0), -1)
    if barcode:
        x, y, w, h = t.barcode
        fmt = zxingcpp.BarcodeFormat.QRCode if qr else zxingcpp.BarcodeFormat.Code128
        code = np.array(zxingcpp.write_barcode_to_image(zxingcpp.create_barcode(barcode, fmt), scale=1))
        (x0, y0), (x1, y1) = p(x, y), p(x + (h if qr else w), y + h)
        page[y0:y1, x0:x1] = cv2.resize(code, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)[..., None]
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


def photo(page: np.ndarray, tilt: float = 0.06, dim: float = 0.55, width: int = 1100, quality: int = 45,
          seed: int = 0) -> np.ndarray:
    """What a phone photo sent over a chat app looks like: taken at an angle, dim and unevenly lit, shrunk and
    JPEG-compressed."""
    h, w = page.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[w * tilt, h * tilt / 2], [w * (1 - tilt / 3), 0], [w, h], [0, h * (1 - tilt / 4)]])
    out = cv2.warpPerspective(page, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=(90, 90, 90))
    light = np.linspace(1.0, dim, w)[None, :, None] * np.linspace(1.0, 0.85, h)[:, None, None]  # a shadow
    rng = np.random.default_rng(seed)
    out = np.clip(out * light + rng.normal(0, 4, out.shape), 0, 255).astype(np.uint8)
    out = cv2.resize(out, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
    return cv2.imdecode(cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, quality])[1], cv2.IMREAD_COLOR)


def reprint(page: np.ndarray, paper_mm: tuple[float, float], scale: float, stretch: float = 1.0,
            dpi: int = 200) -> np.ndarray:
    """An A4 page (rendered at 200 DPI) printed at another scale, centred on other paper, and scanned at `dpi`;
    `stretch` widens it alone, as some printers' "fit to page" does."""
    k = dpi / 200 * scale
    img = cv2.resize(page, (round(page.shape[1] * k * stretch), round(page.shape[0] * k)), interpolation=cv2.INTER_AREA)
    w, h = round(paper_mm[0] / 25.4 * dpi), round(paper_mm[1] / 25.4 * dpi)
    out = np.full((h, w, 3), 255, np.uint8)
    y0, x0 = (h - img.shape[0]) // 2, (w - img.shape[1]) // 2
    img = img[max(-y0, 0):, max(-x0, 0):][:h, :w]  # a sheet a pixel larger than the paper loses that pixel
    y0, x0 = max(y0, 0), max(x0, 0)
    out[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img
    return out


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
        elif g.kind == "numeric":  # a number in the leftmost columns, or blank
            digits = [int(d) for d in rng.integers(10, size=int(rng.integers(g.cols + 1)))]
            for c, d in enumerate(digits):
                marks[gi, d, c] = "pen"
            answers[g.first] = str(int("".join(map(str, digits)))) if digits else ""
        else:
            c = int(rng.integers(g.cols))
            marks[gi, 0, c] = "pen"
            set_code = g.options[c]
    return marks, answers, roll, set_code


def fill(page: np.ndarray, t: Template, marks: dict[tuple[int, int, int], str], dpi: int = 200) -> np.ndarray:
    """Fill bubbles on an already printed page, such as a rendered sheet PDF."""
    s = dpi / 25.4
    out = page.copy()
    axes = (round(t.bubble[0] / 2 * s), round(t.bubble[1] / 2 * s))
    for (gi, r, c), style in marks.items():
        x, y = t.grids[gi].centre(r, c)
        start = 90 if style == "half" else 0  # half: the left half filled
        cv2.ellipse(out, (round(x * s), round(y * s)), axes, 0, start, start + (180 if style == "half" else 360),
                    (INK["pen" if style == "half" else style],) * 3, -1)
    return out


def camera(page: np.ndarray, t: Template, size: tuple[int, int] = (1080, 1440), scale: float = 1.0,
           shift: tuple[float, float] = (0, 0), turn: float = 0, keystone: float = 0, blur: float = 0,
           shake: float = 0, light: float = 1.0, shadow: float = 0, glare: float = 0, noise: float = 3,
           quality: int = 70, table=(60, 70, 80), seed: int = 0) -> np.ndarray:
    """A phone camera's video frame of a sheet on a table, placed where the phone page's targets put it (the page
    fitted in 86% of the frame) and then off it as a hand holds it: `scale` times that size, moved by `shift`
    (a share of the frame), turned `turn` degrees, `keystone` narrower at the top (the phone tipped), out of
    focus (`blur`, px), shaken sideways (`shake`, px), lit at `light` with a `shadow` across one side (0 to 1,
    the share of light lost), a `glare` spot (0 to 1) and sensor noise, then compressed as video is."""
    W, H = size
    h, w = page.shape[:2]
    k = min(0.86 * W / t.page[0], 0.86 * H / t.page[1]) * scale  # px per mm, as the page's guide() fits it
    sw, sh = t.page[0] * k, t.page[1] * k
    corners = np.float64([[-sw / 2, -sh / 2], [sw / 2, -sh / 2], [sw / 2, sh / 2], [-sw / 2, sh / 2]])
    corners[:2, 0] *= 1 - keystone
    a = np.radians(turn)
    corners = corners @ np.float64([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]])
    corners += (W / 2 + shift[0] * W, H / 2 + shift[1] * H)
    m = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
    rng = np.random.default_rng(seed)
    out = np.empty((H, W, 3), np.float32)
    out[:] = table
    out += rng.normal(0, 6, (H, W, 1))  # the table's grain
    sheet = cv2.warpPerspective(page, m, (W, H), flags=cv2.INTER_AREA)
    inside = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (W, H))[..., None] / 255.0
    out = out * (1 - inside) + sheet * 0.92 * inside
    if blur:
        out = cv2.GaussianBlur(out, (0, 0), blur)
    if shake:
        kernel = np.zeros((1, int(shake) * 2 + 1), np.float32)
        kernel[:] = 1 / kernel.size
        out = cv2.filter2D(out, -1, kernel)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    lit = light * (1 - shadow * np.clip((xx / W - 0.3) / 0.5, 0, 1))  # darker towards the right
    out = out * lit[..., None]
    if glare:
        spot = np.exp(-(((xx - 0.62 * W) / (0.12 * W)) ** 2 + ((yy - 0.3 * H) / (0.08 * H)) ** 2))
        out = out + glare * 255 * spot[..., None]
    out = np.clip(out + rng.normal(0, noise, out.shape), 0, 255).astype(np.uint8)
    return cv2.imdecode(cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, quality])[1], cv2.IMREAD_COLOR)
