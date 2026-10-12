# OMR

An offline Windows product for checking OMR answer sheets: design or map a
sheet, read filled sheets live from an ADF scanner or from scanned PDFs,
grade them against an answer key, and publish results. A question bank and a
syllabus maker follow in later phases.

## Status

Phase 1 (OMR checking MVP) is being specified. Read these first:

- [Constitution](.specify/memory/constitution.md): the rules every change follows.
- [Phase 1 spec](specs/001-omr-checking-mvp/spec.md): what phase 1 must do and how it is tested.
- [AGENTS.md](AGENTS.md): how to write code here.

## Layout

```
src/omr_core/   reading engine and business logic, no UI (reused by a web edition later)
src/omr_app/    PySide6 desktop shell over omr_core
tests/          pytest suite; tests/fixtures holds real scanned sheets
specs/          one folder per feature: spec, plan, tasks (spec-kit flow)
.specify/       spec-kit memory, including the constitution
```

## Run it

Python 3.11 or newer.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on Linux or macOS: source .venv/bin/activate
pip install -e ".[app,dev]"
pytest                          # core tests
omr                             # start the desktop app
```

The `app` extra pulls in PySide6, and pytwain on Windows for live scanning.
`omr_core` installs and tests on any OS without it.
