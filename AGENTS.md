# Working rules

For people and coding agents working in this repo. The
[constitution](.specify/memory/constitution.md) is the higher authority; these
rules are how we apply it day to day. They follow the "smallest complete
change" approach of [ponytail](https://github.com/dietrichgebert/ponytail).

## Before you write

- Read the spec for the feature (`specs/NNN-name/spec.md`) and the code you
  will touch. List every place the change must reach: callers, tests,
  fixtures, templates, the database.
- Check what the change could break for a school: scans or results it could
  lose, sheets it could grade differently.

## The smallest complete change

Take the first option that fully works:

1. Does it need to exist? Skip what the spec does not ask for, and say so.
2. Is it already in `omr_core`? Use it the way the surrounding code does.
3. Is it in the standard library, NumPy or OpenCV? Use that.
4. Otherwise write the minimum code that works.

- Finish every part of the change, including the tests and fixtures it breaks.
- No abstraction, option, config or "for later" code nobody asked for.
- Comment only the why the code cannot show. A known shortcut gets
  `# shortcut: <the limit>, <when to upgrade>`.
- New non-trivial logic (a branch, a loop, a parser, grading, licensing)
  ships with a small test.

## Never cut

- Validation of anything from outside: scanned pages, imported PDFs and
  Excel files, licence files, templates.
- Error handling that prevents losing scanned pages or graded results.
- Scanner calibration: DPI, thresholds, dropout colour.
- Flagging for review: the engine never guesses a mark.

## Boundaries

- `omr_core` never imports PySide6, pytwain, pywin32 or other UI or
  Windows-only modules.
- Every page source (ADF, PDF, image, watched folder) hands a page image to
  the same pipeline; nothing downstream knows where it came from.
- Dependencies must allow closed-source sale: no GPL or AGPL in shipped code.

## Checks

- `pytest` passes locally and in CI (Windows and Linux).
- A change to the reading pipeline reports fixture accuracy before and after.
