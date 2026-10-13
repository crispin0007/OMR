"""Draw the installer's side panel and corner logo (build.ps1 runs this before Inno Setup).

Written as BMPs at each Windows display scale, as Inno Setup picks the one that fits the screen. They are
build outputs, not kept in the repository.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "wizard"
FONTS = ROOT / "src" / "omr_core" / "fonts"
SCALES = (100, 125, 150, 175, 200, 225, 250)
TOP, BOTTOM = (13, 71, 161), (25, 118, 210)  # the logo's blues


def panel(scale: int) -> Image.Image:
    """The tall image on the welcome and finish pages: logo, name and what it is, on a blue gradient."""
    w, h = round(164 * scale / 100), round(314 * scale / 100)
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        draw.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    icon = Image.open(ROOT / "src" / "omr_app" / "icon.png").convert("RGBA")
    side = round(w * 0.62)
    icon = icon.resize((side, side), Image.LANCZOS)
    img.paste(icon, ((w - side) // 2, round(h * 0.16)), icon)
    name = ImageFont.truetype(str(FONTS / "Poppins-SemiBold.ttf"), round(19 * scale / 100))
    small = ImageFont.truetype(str(FONTS / "Poppins-Regular.ttf"), round(9 * scale / 100))
    y = round(h * 0.16) + side + round(14 * scale / 100)
    for text, font, colour in (("OMR Checker", name, "white"), ("Free, offline OMR software", small, (210, 227, 252)),
                               ("for schools and exams", small, (210, 227, 252))):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((w - (box[2] - box[0])) // 2, y), text, font=font, fill=colour)
        y += box[3] - box[1] + round(8 * scale / 100)
    return img


def corner(scale: int) -> Image.Image:
    """The small logo at the top right of the other pages."""
    side = round(55 * scale / 100)
    img = Image.new("RGB", (side, side), "white")
    icon = Image.open(ROOT / "src" / "omr_app" / "icon.png").convert("RGBA").resize((side, side), Image.LANCZOS)
    img.paste(icon, (0, 0), icon)
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for s in SCALES:
        panel(s).save(OUT / f"panel-{s}.bmp")
        corner(s).save(OUT / f"corner-{s}.bmp")
    print(f"Wizard images in {OUT}")
