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

### Desktop app

```
omr
```

1. **Choose template…** picks the sheet layout (`templates/test-100.json` is
   loaded by default).
2. **Open sheets…** reads PDFs or images. Each page gets a row with its roll
   number, set and how many questions were answered. Yellow rows have marks
   to check; click a row to see the page and what needs checking.
3. Type the answer key in the box: one letter per question (`ABDCA…`), or one
   line per set (`A: ABDC…`). Scores appear as you type. Set marks for
   correct, wrong (e.g. -0.25) and blank answers.
4. **Save CSV…** writes every page's score and answers for Excel.

Results aren't saved between runs yet.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[Apache License 2.0](LICENSE). We picked it because it is permissive (anyone,
including schools and companies, can use, change and redistribute the
software) and it includes an explicit patent grant, which protects users and
contributors.
