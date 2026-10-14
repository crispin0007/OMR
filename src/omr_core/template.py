"""Sheet templates: the one contract between the sheet designer and the reader.

A template is a JSON file. All positions are millimetres from the page's
top-left corner, measured on the printed sheet:

    {
      "name": "...", "version": 1,
      "page_mm": [210, 297],
      "markers": {"shape": "square" | "ring", "size_mm": 8,
                  "centres_mm": [[x, y], ...]},          # TL, TR, BR, BL
      "orientation_mm": [x, y, w, h],                   # optional: an area always printed black
      "barcode_mm": [x, y, w, h],                       # optional: a barcode or QR code holding the roll number
      "serial_mm": [x, y, w, h],                        # optional: a barcode with the sheet's own printed number
      "name_boxes_mm": [[[x, y, w, h], ...], ...],        # optional: the name's letter boxes, word by word
      "bubble_mm": [w, h],
      "dropout": "red",                                 # optional: drop pink or red print
      "grids": [{"kind": "questions", "first": 1, "options": "ABCD",
                 "origin_mm": [x, y], "pitch_mm": [dx, dy], "rows": 50, "cols": 4}, ...]
    }

Grid kinds: "questions" (one row per question, one column per option),
"roll_number" (one column per digit, rows are 0 to 9), "set_code"
(one row, one column per set) and "numeric" (one question answered with a
number: one column per digit, rows are 0 to 9; `first` is its question number). `origin_mm` is the centre of the top-left bubble.
A sheet can identify the student by a roll number grid, a barcode, or both.
"""

import json
from dataclasses import dataclass
from pathlib import Path

KINDS = ("questions", "roll_number", "set_code", "numeric")
DIGITS = "0123456789"


@dataclass(frozen=True)
class Grid:
    kind: str
    origin: tuple[float, float]
    pitch: tuple[float, float]
    rows: int
    cols: int
    options: str = ""
    first: int = 1
    multi: bool = False

    def centre(self, row: int, col: int) -> tuple[float, float]:
        return self.origin[0] + col * self.pitch[0], self.origin[1] + row * self.pitch[1]

    def numbers(self) -> list[int]:
        """The question numbers this grid answers."""
        return list(range(self.first, self.first + self.rows)) if self.kind == "questions" else \
            [self.first] if self.kind == "numeric" else []


@dataclass(frozen=True)
class Template:
    name: str
    page: tuple[float, float]
    marker_shape: str
    marker_size: float
    markers: tuple[tuple[float, float], ...]
    bubble: tuple[float, float]
    grids: tuple[Grid, ...]
    orientation: tuple[float, float, float, float] | None = None
    dropout: str | None = None
    barcode: tuple[float, float, float, float] | None = None
    serial: tuple[float, float, float, float] | None = None
    names: tuple[tuple[tuple[float, float, float, float], ...], ...] = ()  # letter boxes, word by word

    def questions(self) -> list[int]:
        """Every question number on the sheet, in order."""
        return sorted(q for g in self.grids for q in g.numbers())

    def grid_for(self, q: int) -> Grid | None:
        return next((g for g in self.grids if q in g.numbers()), None)

    def answer_options(self) -> list[str]:
        """What each question, in order, is answered with: its option letters, or DIGITS for a number."""
        return [DIGITS if g.kind == "numeric" else g.options for g in map(self.grid_for, self.questions())]


def load(path: str | Path) -> Template:
    return parse(json.loads(Path(path).read_text(encoding="utf-8")))


def parse(d: dict) -> Template:
    """Build a Template from parsed JSON, rejecting anything the reader can't use."""
    if d.get("version") != 1:
        raise ValueError(f"unsupported template version {d.get('version')!r}")
    w, h = _pair(d, "page_mm")
    m = d.get("markers") or {}
    centres = tuple(_point(p, "markers.centres_mm") for p in m.get("centres_mm", []))
    if len(centres) != 4:
        raise ValueError("markers.centres_mm needs 4 points: top-left, top-right, bottom-right, bottom-left")
    if m.get("shape") not in ("square", "ring"):
        raise ValueError("markers.shape must be 'square' or 'ring'")
    if d.get("dropout") not in (None, "red"):
        raise ValueError("dropout must be 'red' or absent")
    t = Template(
        name=str(d.get("name", "")),
        page=(w, h),
        marker_shape=m["shape"],
        marker_size=_positive(m.get("size_mm"), "markers.size_mm"),
        markers=centres,
        bubble=_pair(d, "bubble_mm"),
        grids=tuple(_grid(g) for g in d.get("grids", [])),
        orientation=tuple(_number(v, "orientation_mm") for v in d["orientation_mm"]) if "orientation_mm" in d else None,
        dropout=d.get("dropout"),
        barcode=_area(d["barcode_mm"], "barcode_mm", (w, h)) if "barcode_mm" in d else None,
        serial=_area(d["serial_mm"], "serial_mm", (w, h)) if "serial_mm" in d else None,
        names=tuple(tuple(_area(b, "name_boxes_mm", (w, h)) for b in word) for word in _name_boxes(d)),
    )
    kinds = [g.kind for g in t.grids]
    if "questions" not in kinds and "numeric" not in kinds:
        raise ValueError("template has no questions grid")
    for k in ("roll_number", "set_code"):
        if kinds.count(k) > 1:
            raise ValueError(f"template has more than one {k} grid")
    numbers = [q for g in t.grids for q in g.numbers()]
    if len(numbers) != len(set(numbers)):
        raise ValueError("question numbers overlap between grids")
    for x, y in [*t.markers, *(g.centre(r, c) for g in t.grids for r in (0, g.rows - 1) for c in (0, g.cols - 1))]:
        if not (0 <= x <= w and 0 <= y <= h):
            raise ValueError(f"point ({x}, {y}) mm is outside the page")
    return t


def _name_boxes(d: dict) -> list:
    if "name_boxes_mm" in d:
        boxes = d["name_boxes_mm"]
        if not isinstance(boxes, list) or not all(isinstance(word, list) for word in boxes):
            raise ValueError("name_boxes_mm must be a list of words, each a list of [x, y, w, h]")
        return boxes
    if "print" in d:  # a sheet made here before the boxes were written down: they were always in the same place
        from .sheet import name_boxes
        return name_boxes()
    return []


def _grid(g: dict) -> Grid:
    kind = g.get("kind")
    if kind not in KINDS:
        raise ValueError(f"grid kind must be one of {KINDS}, got {kind!r}")
    rows, cols = int(g.get("rows", 0)), int(g.get("cols", 0))
    if rows < 1 or cols < 1:
        raise ValueError(f"{kind} grid needs rows and cols of at least 1")
    options = str(g.get("options", ""))
    if kind in ("roll_number", "numeric") and rows != 10:
        raise ValueError(f"{kind} grid needs 10 rows (digits 0 to 9)")
    if kind == "set_code" and rows != 1:
        raise ValueError("set_code grid needs 1 row")
    if kind not in ("roll_number", "numeric") and len(options) != cols:
        raise ValueError(f"{kind} grid has {cols} columns but options {options!r}")
    return Grid(kind, _pair(g, "origin_mm"), _pair(g, "pitch_mm", positive=False), rows, cols,
                options, int(g.get("first", 1)), bool(g.get("multi", False)))


def _area(v, name: str, page: tuple[float, float]) -> tuple[float, float, float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        raise ValueError(f"{name} must be [x, y, w, h]")
    x, y, w, h = (_number(n, name) for n in v)
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > page[0] or y + h > page[1]:
        raise ValueError(f"{name} must be an area on the page")
    return x, y, w, h


def _number(v, name) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{name} must be a number, got {v!r}")
    return float(v)


def _positive(v, name) -> float:
    v = _number(v, name)
    if v <= 0:
        raise ValueError(f"{name} must be positive")
    return v


def _point(p, name) -> tuple[float, float]:
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise ValueError(f"{name} must be [x, y]")
    return _number(p[0], name), _number(p[1], name)


def _pair(d: dict, key: str, positive: bool = True) -> tuple[float, float]:
    x, y = _point(d.get(key), key)
    if positive and (x <= 0 or y <= 0) or x < 0 or y < 0:
        raise ValueError(f"{key} must be {'positive' if positive else 'non-negative'}")
    return x, y
