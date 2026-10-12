"""Make the app icon (src/omr_app/icon.png and packaging/omr.ico) from the logo. Run again after changing it.

The icon is the logo's mark without the wordmark, on a white rounded square so it shows on dark taskbars too.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def mark(logo: Image.Image, size: int = 256) -> Image.Image:
    grey = np.asarray(logo.convert("L"))
    words = int(grey.shape[0] * 0.70)  # the wordmark sits in the bottom 30%
    ys, xs = np.nonzero(grey[:words] < 235)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    side = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    crop = logo.convert("RGB").crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2))
    inner = round(size * 0.86)
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(icon).rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill="white")
    icon.paste(crop.resize((inner, inner), Image.LANCZOS), ((size - inner) // 2,) * 2)
    return icon


if __name__ == "__main__":
    icon = mark(Image.open(ROOT / "packaging" / "logo.png"))
    icon.save(ROOT / "src" / "omr_app" / "icon.png", optimize=True)
    icon.save(ROOT / "packaging" / "omr.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
