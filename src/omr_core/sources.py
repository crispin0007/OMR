"""Turn files into page images for the reader (Constitution III: one pipeline)."""

from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium

PDF_DPI = 200
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def read_pages(path: str | Path) -> Iterator[np.ndarray]:
    """Yield each page of a PDF or image file as a BGR image.

    Raises ValueError for a file that can't be opened (corrupt, password
    protected, unsupported) so the caller can report it and carry on with the
    rest of the batch.
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            pdf = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as e:
            raise ValueError(f"{path.name}: can't open PDF ({e})") from e
        try:
            for page in pdf:
                rgb = page.render(scale=PDF_DPI / 72, rev_byteorder=True).to_numpy()
                yield cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR if rgb.shape[2] == 4 else cv2.COLOR_RGB2BGR)
        finally:
            pdf.close()
    elif ext in IMAGE_TYPES:
        # imdecode, not imread: imread can't open non-ASCII paths on Windows.
        ok, pages = cv2.imdecodemulti(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        if not ok or not pages:
            raise ValueError(f"{path.name}: can't read image")
        yield from pages
    else:
        raise ValueError(f"{path.name}: unsupported file type {ext or '(none)'}")
