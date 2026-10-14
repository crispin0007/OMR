"""Turn files into page images for the reader (Constitution III: one pipeline)."""

from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium

PDF_DPI = 200
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def read_pages(path: str | Path, only: int | None = None) -> Iterator[np.ndarray]:
    """Yield each page of a PDF or image file as a BGR image; `only` yields just that page (from 0) of a PDF.

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
            for page in pdf if only is None else [pdf[only]]:
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


def page_count(path: str | Path) -> int | None:
    """Pages in a PDF, or None for an image file or a PDF that won't open (reading it says why)."""
    if Path(path).suffix.lower() != ".pdf":
        return None
    try:
        pdf = pdfium.PdfDocument(path)
    except pdfium.PdfiumError:
        return None
    try:
        return len(pdf)
    finally:
        pdf.close()


def is_blank(page: np.ndarray, ink_share: float = 0.003) -> bool:
    """True for a page with almost no ink, such as the empty back of a sheet in a duplex scan.

    A printed answer sheet has registration marks and bubble outlines, far more than 0.3% ink.
    """
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY) if page.ndim == 3 else page
    small = cv2.resize(gray, (0, 0), fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    paper = float(np.percentile(small, 90))
    return float((small < paper - 80).mean()) < ink_share


def ready_files(folder: str | Path, known: set[str], sizes: dict[str, int]) -> list[Path]:
    """New scan files in a folder that the scanner has finished writing, oldest first.

    A file counts as finished when its size is the same as at the previous call, so call this
    on a timer and pass the same `sizes` each time. `known` holds files already read.
    """
    out = []
    for path in sorted(Path(folder).iterdir(), key=lambda p: p.stat().st_mtime):
        if path.suffix.lower() not in IMAGE_TYPES | {".pdf"} or str(path) in known or not path.is_file():
            continue
        size = path.stat().st_size
        if size and sizes.get(str(path)) == size:
            out.append(path)
        sizes[str(path)] = size
    return out
