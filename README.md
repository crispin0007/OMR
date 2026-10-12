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

The sidebar opens Dashboard, Exams, Check sheets, Review, Results, Sheet
designer and Settings.

1. On **Exams**, **New exam…** asks for a name and the sheet template
   (`templates/test-100.json` by default). Double-click an exam to open it.
   **Import students…** reads an Excel file with roll number, name and
   class columns; names then show everywhere, roll numbers not on the list
   go to Review, and rows that can't be used are listed, not imported.
2. On **Check sheets**, **Open sheets…** reads PDFs or images. Each page gets
   a row with its roll number, set and how many questions were answered.
   Highlighted rows have marks to check; click a row to see the page and
   what needs checking.
3. Type the answer key in the box: one letter per question (`ABDCA…`), or one
   line per set (`A: ABDC…`). Scores appear as you type. Set marks for
   correct, wrong (e.g. -0.25) and blank answers.
4. **Review** lists everything the reader wasn't sure about, unreadable
   pages and repeated roll numbers. Each item shows that part of the sheet;
   click the right answer or press its key (Delete for blank, Space to keep
   the reading). Scores update at once and every change is logged.
5. **Dashboard** shows sheets read, average score, sheets to check, the score
   spread and recent batches. Click any of them to open those sheets.
   **Results** ranks every sheet with right, wrong and blank counts and its
   percentile, and exports a merit list to Excel (with every answer coloured
   right or wrong) or one PDF scorecard per student.
6. **Sheet designer** turns a scan of a sheet you already print into a
   template. Open a flat scan of the whole page (blank or filled, 150 to 300
   DPI), click the four corner marks, then drag a box around each block of
   bubbles. It finds the bubbles, guesses roll number, set code or questions
   and numbers them; fix anything on the right. **Test on this scan** reads
   the scan with the new template, and **Save template…** puts it in
   `%LOCALAPPDATA%\OMR\templates`, where **New exam…** looks first.
   Sheets with a separate orientation mark are mapped without it.
   If the sheet prints the roll number as a barcode or QR code, click
   **Box the barcode next** and box it. On a sheet with no roll number
   bubbles the code is the roll number; with both, a page where they
   disagree goes to Review.
7. **Settings** picks Light, Dark or System theme, an accent colour, text size
   and density. The button at the bottom of the sidebar switches light and dark.
8. **Save CSV…** writes every page's score and answers for Excel.

Everything is saved as you work: each page as soon as it is read, and the key
and marks as you type. Exams live in `%LOCALAPPDATA%\OMR\omr.db`; the app
reopens the last exam.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[Apache License 2.0](LICENSE). We picked it because it is permissive (anyone,
including schools and companies, can use, change and redistribute the
software) and it includes an explicit patent grant, which protects users and
contributors.
