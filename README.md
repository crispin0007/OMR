<p align="center"><img src="packaging/logo.png" alt="OMR Checker" width="240"></p>

# OMR Checker

Free, open-source, offline Windows software for checking OMR answer sheets: design or map a
sheet, read filled sheets live from an ADF scanner or from scanned PDFs,
grade them against an answer key, and publish results. A question bank and a
syllabus maker follow in later phases.

## Status

Phase 1 (OMR checking MVP) is being specified. Read these first:

- [Constitution](.specify/memory/constitution.md): the rules every change follows.
- [Phase 1 spec](specs/001-omr-checking-mvp/spec.md): what phase 1 must do and how it is tested.
- [Question bank spec](specs/003-question-bank/spec.md): phase 2, draft.
- [AGENTS.md](AGENTS.md): how to write code here.

## Layout

```
src/omr_core/   reading engine and business logic, no UI (reused by a web edition later)
src/omr_app/    PySide6 desktop shell over omr_core
tests/          pytest suite; tests/fixtures holds real scanned sheets
specs/          one folder per feature: spec, plan, tasks (spec-kit flow)
.specify/       spec-kit memory, including the constitution
```

## Install on Windows

Run `OMR-Setup-<version>.exe` and open OMR Checker from the Start menu; nothing else is needed. To make the
installer from this repository, see [packaging/README.md](packaging/README.md).

## Run it from source

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

The sidebar opens Dashboard, Exams, Map printed sheet, Help and Settings. Until
the first exam exists, Exams shows the steps below. **Help** (F1) repeats them
with the shortcuts: Ctrl+N for a new exam, Ctrl+O to import scans.

1. On **Exams**, **New exam…** sets up the exam step by step. **Start from**
   fills it in from a ready-made layout (JEE Main, NEET or CEE style, or a
   50-question class test) to change as you like. The steps cover its name,
   class, date, time and duration; its subjects or sections and the
   question numbers each covers; options per question (2 to 8, or true or
   false), roll number digits and question paper sets; marks for right,
   wrong (negative marking) and blank answers, per section, with partial
   marking for multi-correct questions; and the sheet's colour, heading,
   logo and instructions. The last step shows a summary and the sheet, and
   **Create exam** makes the exam with its sheet ready to print. For a sheet
   you already print, pick **Use my own printed sheet** and its template
   (see Map printed sheet). Click an exam to open its page.
   The tabs below are all on that page; **All exams** goes back to the list.
2. **Scan** reads sheets as the scanner feeds them. Pick the scanner,
   resolution (200 DPI is right for most sheets) and whether to scan both
   sides (blank backs are skipped), then press **Scan**. Each sheet is read
   and saved the moment it arrives; the counters and the latest sheet update
   as the stack feeds. A jam or double feed stops the run with every earlier
   sheet saved; put the rest back and press Scan again. Scanners are found
   through Windows (WIA). If yours isn't listed, scan with its own software
   into a folder and pick **A folder my scanner software saves into**; each
   file is read as soon as it is saved. **Import scans…** reads PDFs or
   images scanned earlier.
3. **Scanned sheets** has a row per page with its roll number, set and how
   many questions were answered. Highlighted rows have marks to check; click
   a row to see the page and what needs checking.
4. **Answer key** has a row per question with its section and options.
   Click the right option or press its letter, and the next question is
   selected; arrow keys move between questions, Shift+letter or Ctrl+click
   adds a second correct option, `*` makes a bonus question and Space drops
   one. Pick the set at the top for a key per set. **Import CSV…** and
   **Export CSV…** use the columns `set,question,answer` (`set` may be left
   out), and **Paste as text** takes one letter per question (`ABDCA…`), or
   one line per set (`A: ABDC…`). Scores appear as you go. A key shorter than the sheet
   counts only those questions. **Marks and sections** sets marks for
   correct, wrong (e.g. -0.25) and blank answers; **Sections…** gives ranges
   of questions their own name and marks (e.g. Physics 1 to 30, 4 right, -1
   wrong), and results then show a score per section.
5. **Review** lists everything the reader wasn't sure about, unreadable
   pages and repeated roll numbers. Each item shows that part of the sheet;
   click the right answer or press its key (Delete for blank, Space to keep
   the reading). Scores update at once and every change is logged.
   **Students** imports an Excel file with roll number, name and class
   columns; names then show everywhere, roll numbers not on the list go to
   Review, and rows that can't be used are listed, not imported.
   **Results** ranks every sheet with right, wrong and blank counts and its
   percentile, and exports a merit list to Excel (with every answer coloured
   right or wrong, and an item analysis: per question the share right, wrong
   and blank, the most chosen wrong answer and how well it separates strong
   from weak students) or one PDF scorecard per student. **Print sheet**
   saves the exam's sheet as a PDF for A4, Letter, Legal, A3 or A5 paper.
   The sheet reads the same at any print size, scaled or "fit to page", as
   long as all four corner circles are on the paper.
   **Check a printed copy…** reads a scan or phone photo of one printed
   sheet, blank or with a few bubbles filled, and says whether it reads,
   before you print the rest.
   **Exam settings** renames or deletes the exam. **Change sheet…** there
   gives the exam another template, for pages filled on a different sheet,
   and reads every page again with it: imported files from the original
   file, scanned pages from the image kept for them.
   **Dashboard** in the sidebar shows the open exam's sheets read, average
   score, sheets to check, the score spread and recent batches. Click any of
   them to open those sheets.
6. **Map printed sheet** maps a sheet you already print, and is only needed
   for such sheets (New exam makes new ones): it turns a scan of
   an existing sheet into a template. Open a flat scan of the whole page (blank or filled, 150 to 300
   DPI), click the four corner marks, then drag a box around each block of
   bubbles. It finds the bubbles, guesses roll number, set code or questions
   and numbers them; fix anything on the right. **Test on this scan** reads
   the scan with the new template, and **Save template…** puts it in
   `%LOCALAPPDATA%\OMR\templates`, where **Use my own printed sheet** looks
   first.
   Sheets with a separate orientation mark are mapped without it.
   If the sheet prints the roll number as a barcode or QR code, click
   **Box the barcode next** and box it. On a sheet with no roll number
   bubbles the code is the roll number; with both, a page where they
   disagree goes to Review.
7. **Settings** picks Light, Dark or System theme, an accent colour, text size
   and density. The button at the bottom of the sidebar switches light and dark.
9. **Save CSV…** writes every page's score and answers for Excel.

Everything is saved as you work: each page as soon as it is read, and the key
and marks as you type. Exams live in `%LOCALAPPDATA%\OMR\omr.db`; the app
reopens the last exam.

**Back up…** on Exams saves every exam, with its sheets, corrections and
students, in one file. **Restore…** adds the exams in such a file, on the same
PC or a new one; exams already there are left as they are.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[Apache License 2.0](LICENSE). We picked it because it is permissive (anyone,
including schools and companies, can use, change and redistribute the
software) and it includes an explicit patent grant, which protects users and
contributors.

Printed sheets use the Poppins font, under the SIL Open Font License
([src/omr_core/fonts/OFL.txt](src/omr_core/fonts/OFL.txt)).
