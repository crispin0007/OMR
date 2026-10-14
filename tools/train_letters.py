"""Train the letter reader for the name boxes (src/omr_core/letters.npz) from handwriting fonts.

    python tools/train_letters.py FONT_DIR [FONT_DIR ...]

Each FONT_DIR holds .ttf, .otf or .woff font files under an open licence (SIL OFL or Apache), for example the
handwriting families of the @fontsource npm packages (`npm pack @fontsource/patrick-hand`, unpacked). The fonts
the shipped weights were trained on are listed in tools/letter-fonts.txt. Every
capital letter of every font is drawn many times in a name box, turned, shifted, thickened and blurred like a
pen on a scan, then cut out exactly as the reader cuts a real box. Students' sheets are never used.

Needs scikit-learn and Pillow, for training only; the app reads the weights with NumPy.
"""

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from sklearn.neural_network import MLPClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from omr_core.names import LETTERS, MODEL, features, normalise
from omr_core.reader import SCALE

BOX_W, BOX_H = round(4.67 * SCALE), round(5.5 * SCALE)  # a name box on the sheet, in aligned pixels
MARGIN = SCALE
EACH = 80  # drawings of each letter in each font
HIDDEN = 512


def box_with(letter: str, font_path: Path, rng: np.random.Generator) -> np.ndarray:
    h, w = BOX_H + 2 * MARGIN, BOX_W + 2 * MARGIN
    size = int(rng.uniform(0.8, 1.25) * BOX_H * 1.3)
    font = ImageFont.truetype(str(font_path), size)
    canvas = Image.new("L", (3 * w, 3 * h), 255)
    ImageDraw.Draw(canvas).text((1.5 * w, 1.5 * h), letter, font=font, fill=0, anchor="mm")
    glyph = np.array(canvas)
    ys, xs = np.nonzero(glyph < 128)
    if not len(xs):
        return None
    glyph = glyph[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    # Scale the letter to the box's height, as people fill the box, sometimes a little over.
    target = rng.uniform(0.55, 0.95) * BOX_H
    k = target / glyph.shape[0]
    glyph = cv2.resize(glyph, (max(1, int(glyph.shape[1] * k * rng.uniform(0.8, 1.2))), max(1, int(target))),
                       interpolation=cv2.INTER_AREA)
    if glyph.shape[1] > BOX_W * 1.3:
        glyph = cv2.resize(glyph, (int(BOX_W * 1.3), glyph.shape[0]), interpolation=cv2.INTER_AREA)
    angle = rng.uniform(-10, 10)
    shear = rng.uniform(-0.2, 0.2)
    gh, gw = glyph.shape
    m = cv2.getRotationMatrix2D((gw / 2, gh / 2), angle, 1.0)
    m[0, 1] += shear
    pad = cv2.copyMakeBorder(glyph, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    m[:, 2] += 10
    glyph = cv2.warpAffine(pad, m, (gw + 20, gh + 20), borderValue=255)
    # A hand isn't a font: bend the strokes a little, smoothly.
    gh, gw = glyph.shape
    flow = [cv2.GaussianBlur(rng.uniform(-1, 1, (gh, gw)).astype(np.float32), (0, 0), 6) * 40 for _ in range(2)]
    gx, gy = np.meshgrid(np.arange(gw, dtype=np.float32), np.arange(gh, dtype=np.float32))
    glyph = cv2.remap(glyph, gx + flow[0], gy + flow[1], cv2.INTER_LINEAR, borderValue=255)
    pen = rng.integers(-1, 2)
    if pen > 0:
        glyph = cv2.erode(glyph, np.ones((2, 2), np.uint8))
    elif pen < 0 and min(glyph.shape) > 20:
        glyph = cv2.dilate(glyph, np.ones((2, 2), np.uint8))
    page = np.full((h, w), 255, np.uint8)
    cx = w // 2 + int(rng.normal(0, BOX_W * 0.08))
    cy = h // 2 + int(rng.normal(0, BOX_H * 0.06))
    y0, x0 = cy - glyph.shape[0] // 2, cx - glyph.shape[1] // 2
    gy0, gx0 = max(0, -y0), max(0, -x0)
    y0, x0 = max(0, y0), max(0, x0)
    part = glyph[gy0:gy0 + h - y0, gx0:gx0 + w - x0]
    page[y0:y0 + part.shape[0], x0:x0 + part.shape[1]] = np.minimum(page[y0:y0 + part.shape[0],
                                                                         x0:x0 + part.shape[1]], part)
    line = int(rng.integers(1, 3))
    cv2.rectangle(page, (MARGIN, MARGIN), (MARGIN + BOX_W, MARGIN + BOX_H), int(rng.integers(0, 90)), line)
    if rng.random() < 0.5:  # the neighbouring boxes' sides
        cv2.line(page, (0, MARGIN), (w, MARGIN), 40, line)
        cv2.line(page, (0, MARGIN + BOX_H), (w, MARGIN + BOX_H), 40, line)
    page = cv2.GaussianBlur(page, (0, 0), rng.uniform(0.3, 1.0))
    noise = rng.normal(0, rng.uniform(0, 8), page.shape)
    return np.clip(page + noise, 0, 255).astype(np.uint8)


def main(dirs: list[str]):
    fonts = [p for d in dirs for p in Path(d).rglob("*") if p.suffix.lower() in (".ttf", ".otf", ".woff")]
    print(f"{len(fonts)} fonts")
    rng = np.random.default_rng(1)
    xs, ys = [], []
    for f in fonts:
        for i, letter in enumerate(LETTERS):
            for _ in range(EACH):
                page = box_with(letter, f, rng)
                if page is None:
                    continue
                m = normalise(page, MARGIN)
                if m is not None:
                    xs.append(m)
                    ys.append(i)
    x = features(np.array(xs))
    y = np.array(ys)
    mean, std = x.mean(0), x.std(0) + 1e-6
    net = MLPClassifier((HIDDEN,), alpha=1e-3, max_iter=60, early_stopping=True, random_state=1, verbose=True)
    net.fit((x - mean) / std, y)
    np.savez_compressed(MODEL, mean=mean.astype(np.float32), std=std.astype(np.float32),
                        w1=net.coefs_[0].astype(np.float16), b1=net.intercepts_[0].astype(np.float32),
                        w2=net.coefs_[1].astype(np.float16), b2=net.intercepts_[1].astype(np.float32))
    print(f"{len(y)} letters, held-out accuracy {net.best_validation_score_:.3f}, saved {MODEL}")


if __name__ == "__main__":
    main(sys.argv[1:])
