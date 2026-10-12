# OMR

Free, open-source, offline Windows software for checking OMR answer sheets: design or map a
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

Python 3.11, 3.12 or 3.13 (64-bit). On Windows, in Command Prompt:

```
cd D:\OMR
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[app,dev]"
pytest
```

On Linux or macOS use `python3 -m venv .venv` and `source .venv/bin/activate`.

### Read sheets

```
omr-read TEMPLATE.json sheets.pdf more.png --csv results.csv
```

`omr-read` takes a template and any number of PDF, PNG, JPG or TIFF files,
prints the roll number, set code and anything that needs review for each
page, and with `--csv` saves every answer to a spreadsheet-ready file.
Templates live in `templates/`.

`omr` opens the desktop window, which is still a placeholder.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[Apache License 2.0](LICENSE). We picked it because it is permissive (anyone,
including schools and companies, can use, change and redistribute the
software) and it includes an explicit patent grant, which protects users and
contributors.
