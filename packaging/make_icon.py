"""Draw the app icon (src/omr_app/icon.png and packaging/omr.ico). Run again after changing it."""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen

ROOT = Path(__file__).resolve().parents[1]


def draw(size: int = 256) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#7c5cff"))
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(56 * s, 36 * s, 144 * s, 184 * s), 14 * s, 14 * s)
    for row, filled in enumerate((1, 3, 0, 2)):  # one answer marked in each row
        for col in range(4):
            box = QRectF((74 + col * 31) * s, (62 + row * 38) * s, 22 * s, 16 * s)
            if col == filled:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#2b2250"))
            else:
                p.setPen(QPen(QColor("#7c5cff"), 3 * s))
                p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box, 8 * s, 8 * s)
    p.end()
    return image


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    image = draw()
    image.save(str(ROOT / "src" / "omr_app" / "icon.png"))
    image.save(str(ROOT / "packaging" / "omr.ico"))
