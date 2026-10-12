# OMR Constitution

The rules every change to this repository must follow. Specs, plans and code
reviews check against this file; where they disagree, this file wins.

## Core Principles

### I. Offline First (NON-NEGOTIABLE)

The software is used by schools, colleges, coaching centres and exam bodies
that may have no reliable internet. Every Phase 1 feature must work on a
Windows PC with the network unplugged. Online
features (update checks, SMS and email alerts) are optional extras that fail
quietly and never block a workflow.

### II. Core Has No UI

All reading, grading, data and business logic lives in the `omr_core`
package. `omr_core` must not import PySide6, pytwain, pywin32 or anything else
tied to a screen or to Windows. The desktop app (`omr_app`) is a thin shell
that calls the core. This keeps the core testable on any OS and lets a
FastAPI web edition wrap it later without a rewrite.

### III. One Reading Pipeline

Live ADF scans, PDF imports, image files and watched-folder files all become
the same page image and go through the same pipeline: prepare, align,
identify, read bubbles, decide, grade. A sheet must give the same result
whichever way it arrived. Source-specific code stops at "here is a page".

### IV. Accuracy Over Guessing

A wrong mark costs a student a result, so the engine never guesses. Blank,
multiple, half-filled, ticked or low-confidence answers are flagged for an
operator, never silently resolved. Every manual correction is written to the
audit log with who, when, before and after. Release targets: at least 99.9%
bubble accuracy on flat scans and under 0.3 seconds per page on an ordinary PC.

### V. Tested Against Real Sheets

Grading rules, the bubble decision and every parser ship with tests. The
reading pipeline is tested on a fixture set of real scanned sheets (blank and
filled, from more than one scanner) checked into `tests/fixtures`. A change
that lowers accuracy on that set does not merge. Hardware calibration
(DPI, thresholds, dropout colour) is never cut to save code.

### VI. Smallest Complete Change

Write only what the task needs, and finish all of it. No abstraction, option,
config or "for later" code nobody asked for; prefer the standard library and
already-installed dependencies; never add a dependency for a few lines. Never
cut validation at trust boundaries (scanned input, imported files,
templates), error handling that prevents data loss, security, or accessibility.
See `AGENTS.md` for the working rules.

## Product Constraints

- **Platform:** Windows 10 and 11, 64-bit. Python 3.11+, PySide6 for the
  desktop shell, OpenCV and NumPy for reading, WIA (built into Windows) for
  scanners, with a watched folder for scanners without a WIA driver, pypdfium2 for PDF import, SQLite for storage.
- **Open source:** the project is free and open source under the Apache
  License 2.0. Every dependency in the shipped app must be compatible with
  it: no GPL or AGPL libraries (for example PyMuPDF). PySide6 is used under
  LGPL with normal dynamic linking.
- **Clean room:** no code, sheet layouts or assets copied from closed
  products (such as Addmen) or from projects under incompatible licences.
- **Data stays local:** student data never leaves the PC or the institute's
  local network unless the user sends it.
- **No data loss:** a crash, a paper jam or a power cut mid-scan must not lose
  pages already scanned or results already graded.

## Development Workflow

- Work follows the spec-kit flow: spec (`specs/NNN-name/spec.md`), then plan,
  then tasks, then code. A spec says what and why; a plan says how.
- Every change goes through a pull request; `main` stays releasable.
- CI runs the core tests on Windows and Linux for every pull request.
- A pull request that touches the reading pipeline states its accuracy on the
  fixture set before and after.

## Governance

This constitution supersedes other conventions in the repository. Amending it
needs a pull request that states the change, the reason, and what existing
specs or code must change with it. Versioning: MAJOR for a removed or
redefined principle, MINOR for a new principle or section, PATCH for wording.

**Version**: 1.1.0 | **Ratified**: 2026-10-12 | **Last Amended**: 2026-10-12
