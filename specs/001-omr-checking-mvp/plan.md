# Implementation Plan: OMR Checking MVP

**Branch**: `001-omr-checking-mvp` | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

## Summary

Build the reading pipeline in `omr_core` first and prove it on generated and
real scanned sheets, then wrap it in the PySide6 app: PDF import, review
queue, results and export (P1), then live ADF scanning and sheet mapping (P2),
then the designer, student setup and licensing (P3). Grading is already in
`omr_core/grading.py`.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: OpenCV (headless) and NumPy for reading;
pypdfium2 for PDF pages; zxing-cpp for barcodes and QR; SQLAlchemy Core for
storage; openpyxl and ReportLab for exports; PySide6 for the app; pytwain on
Windows for live scanning; cryptography (Ed25519) for licences.

**Storage**: SQLite file per install (`%LOCALAPPDATA%\OMR\omr.db`), WAL mode,
one commit per graded page. Page images saved as PNG next to it. SQLAlchemy
Core (not the ORM) so the phase 2 Network edition can point at PostgreSQL.

**Testing**: pytest. Core tests run on Windows and Linux in CI. Reader
accuracy tests use generated sheets (below) and, once supplied, real scans in
`tests/fixtures`.

**Target Platform**: Windows 10 and 11, 64-bit desktop.

**Project Type**: Desktop app over a UI-free core library.

**Performance Goals**: under 0.3 s per page at 200 DPI on 4 cores; a page
queue with one reader process per core so the ADF never waits.

**Constraints**: fully offline; no GPL or AGPL dependencies; no graded page
lost on crash.

**Scale/Scope**: up to about 5,000 sheets per exam, 200 questions per sheet.

## Constitution Check

| Principle | How this plan meets it |
|---|---|
| I. Offline first | No network calls in phase 1; the licence is checked locally. |
| II. Core has no UI | Pipeline, storage, grading, exports and licence checks in `omr_core`; scanner and screens in `omr_app`. A CI step imports `omr_core` without PySide6 installed. |
| III. One pipeline | Every source produces a grayscale or colour NumPy page and calls `read_page(page, template)`. |
| IV. Accuracy over guessing | Bubble decision has a grey zone that flags, never picks. Corrections go through one function that writes the audit log. |
| V. Tested against real sheets | Generated-sheet tests now; real fixture set gates the reader before release. |
| VI. Smallest complete change | Few modules, no plugin system, no ORM, no config files beyond the template JSON. |

## Project Structure

### Documentation

```text
specs/001-omr-checking-mvp/
├── spec.md
├── plan.md      # this file
└── tasks.md
```

### Source Code

```text
src/omr_core/
├── grading.py      # done: score, rank
├── template.py     # load and validate template JSON
├── reader.py       # prepare, align, identify, read bubbles, decide
├── sources.py      # PDF and image files to pages
├── store.py        # SQLite schema and queries, audit log
├── export.py       # Excel merit list, PDF scorecards
└── licence.py      # machine ID, request code, verify signed licence

src/omr_app/
├── __main__.py     # main window, exam list
├── scanner.py      # pytwain live ADF, page by page
├── review.py       # review queue on the sheet image
└── designer.py     # map existing sheets, design new ones

tests/
├── sheets.py       # renders filled sheets from a template for tests
├── fixtures/       # real scans with hand-checked answers
└── test_*.py
```

## Design Decisions

### Template format

One JSON file per template, the only contract between designer and reader:
page size in mm, registration mark centres, optional timing marks, dropout
colour, and a list of fields. Each field is a grid with an origin, row and
column pitch, bubble size, rows, columns, and a kind (`questions`,
`roll_number`, `set_code`) or a rectangle (`barcode`, `image_clip`). Mapped
and designed sheets save the same format, versioned with a `version` key.

### Reading a page

1. **Prepare**: for a red dropout template keep the red channel, else
   convert to grayscale.
2. **Align**: find the four registration marks (contours of the expected
   size and squareness near each corner), detect a page rotated 180 degrees,
   and warp the page to template coordinates. If timing marks exist, snap
   each grid row to the nearest detected mark.
3. **Identify**: read barcode or QR with zxing-cpp; read roll number and set
   code grids as single-answer columns.
4. **Read bubbles**: mean darkness inside each bubble's inner circle.
5. **Decide**: split that sheet's darkness values into empty and filled
   levels (Otsu on the sheet's own values), then mark each bubble filled,
   empty, or grey zone. Grey zone, more than one mark on a single-answer
   question, or marks not found all become review flags with a reason.

Output is a plain `PageResult` (roll number, set code, answers as strings,
flags, confidence), which `grading.score` already accepts.

### Live scanning

pytwain in native transfer mode, one page per callback, pushed onto a queue
read by worker processes. Each page is saved and committed before the next
UI update. Jams and double feeds come back as TWAIN errors and pause the run.
First task is a spike on two or three real scanners; if pytwain cannot give
pages one by one, a small C# helper writes pages to a watched folder and the
watched-folder source takes over.

### Generated test sheets

`tests/sheets.py` draws a sheet from a template, fills chosen bubbles with
varied darkness, and adds skew, noise and blur. It gives exact expected
answers, so reader tests run in CI before any real scans exist.

## Risks

- **pytwain page-by-page transfer** on real drivers (spike first, C# helper
  fallback).
- **Accuracy on real sheets** is unknown until sample scans arrive.
- **Nuitka build size and antivirus false positives**: test a signed build
  early in phase 1, not at the end.
