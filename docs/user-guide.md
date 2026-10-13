# OMR Checker user guide

Everything the desktop app does, screen by screen. The [README](../README.md) has the overview, screenshots and install steps.

## The app, step by step

The sidebar opens Dashboard, Exams, Templates, Map printed sheet, Help and Settings. Until
the first exam exists, Exams shows the steps below. **Help** (F1) repeats them
with the shortcuts: Ctrl+N for a new exam, Ctrl+O to import scans.

1. On **Exams**, **New exam…** sets up the exam step by step. **Start from**
   fills it in from a ready-made layout to change as you like: the question
   pattern and marking of national exams in Nepal (MECEE-BL/CEE, KUUMAT,
   CMAT, IOE, Lok Sewa practice), India (NEET, JEE Main, UPSC prelims and
   CSAT, NDA, CTET, KCET, SSC, bank prelims, RRB NTPC, CUET), Bangladesh
   (BCS), Pakistan (MDCAT) and Turkey (YKS TYT), or a 50-question class
   test. These are this app's own sheets laid out to each exam's pattern,
   not the official answer sheets. **Templates** lists them with a preview:
   change one and save it under your own name (it then shows under Start
   from), or put a built-in's values back with Reset to default. Your own
   templates can be renamed, duplicated and deleted; the built-ins never
   change. The steps cover its name,
   class, date, time and duration; its subjects or sections, the question
   numbers each covers and whether it is answered with options or with a
   number (up to 6 digits, e.g. JEE numeric questions, which get a box of
   digit bubbles each at the foot of the sheet); options per question (2 to 8, or true or
   false, with options shown as A–D, a–d or 1–4), roll number digits and question paper sets; marks for right,
   wrong (negative marking) and blank answers, per section, with partial
   marking for multi-correct questions; and the sheet's colour, bubble
   shape (pill, oval, circle, rounded or rectangle), heading, logo and
   instructions, and whether every sheet gets its own sheet number. The last step shows a summary and the sheet, and
   **Create exam** makes the exam with its sheet ready to print. For a sheet
   you already print, pick **Use my own printed sheet** and its template
   (see Map printed sheet). Click an exam to open its page.
   The tabs below are all on that page; **All exams** goes back to the list.
2. **Scan** reads sheets as the scanner feeds them. Pick the scanner,
   resolution (200 DPI is right for most sheets) and whether to scan both
   sides (blank backs are skipped), then press **Start scanning** (also at the top of the exam page and on the Dashboard). Each sheet is read
   and saved the moment it arrives, and shown live: the sheet with every
   filled bubble ringed (green right, red wrong, blue before the key is in)
   and anything to check boxed in orange, its roll number, set and score, a
   growing list of the sheets read (click one to see it again), and running
   counts of sheets read, to check, repeated roll numbers and sheets a
   minute. **Pause** holds the feeder after the current page; **Resume**
   carries on. **Import scans…** (Ctrl+O) and a watched folder show the same
   live view, a page at a time. A jam or double feed stops the run with every earlier
   sheet saved; put the rest back and press Start scanning again. Scanners are found
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
   one line per set (`A: ABDC…`). On a numeric question, type the number (or
   click it); in pasted text a number's digits go together (`ABC42D`), and an
   answer is right when it is the same number (042 is 42). **Read from a filled sheet…** takes the key
   from a master sheet filled with the right answers: its set code picks the
   set, and any unclear or doubled mark is left for you to click. Scores appear as you go. A key shorter than the sheet
   counts only those questions. **Marks and sections** sets marks for
   correct, wrong (type the marks taken off, e.g. 0.25) and blank answers; **Sections…** gives ranges
   of questions their own name and marks (e.g. Physics 1 to 30, 4 right, -1
   wrong), and results then show a score per section. **Topics…** gives questions a topic
   each (`1-10: Kinematics`, one line per topic); every scorecard then shows
   the student's share right per topic, and the merit list gets a Topics
   sheet with a row per student and one for everyone.
5. **Review** lists everything the reader wasn't sure about, unreadable
   pages and repeated roll numbers. Each item shows that part of the sheet;
   click the right answer or press its key (Delete for blank, Space to keep
   the reading). A numeric answer with a doubtful digit or a gap between
   digits is typed in. Scores update at once and every change is logged.
   **Students** imports an Excel file with roll number, name and class
   columns; names then show everywhere, roll numbers not on the list go to
   Review, and rows that can't be used are listed, not imported.
   It also marks who is absent (on the list, no sheet read); **Show only
   absent** and **Save absent list…** give that list as a CSV.
   **Use the list of another exam…** copies a list already imported.
   **Results** ranks every sheet with right, wrong and blank counts and its
   percentile, and exports a merit list to Excel (with every answer coloured
   right or wrong, and an item analysis: per question the share right, wrong
   and blank, the most chosen wrong answer and how well it separates strong
   from weak students) or one PDF scorecard per student. **Print sheet**
   prints the exam's sheet (**Print…**) or saves it as a PDF (**Save as
   PDF…**) for A4, Letter, Legal, A3 or A5 paper; Templates has the same two
   buttons for a blank sheet of any template. A sheet with sheet numbers
   prints as many copies as you ask for, numbered from where you choose with
   an optional prefix (A-0001, A-0002…). Each number is printed as text and
   as a barcode, read back when the sheet is scanned and shown on Scanned
   sheets, Results, the CSV and the Excel merit list; numbers on more than
   one page, numbers missing between the lowest and highest scanned, and
   numbers that can't be read are listed above the scanned sheets.
   The sheet reads the same at any print size, scaled or "fit to page", as
   long as all four corner circles are on the paper.
   **Check a printed copy…** reads a scan or phone photo of one printed
   sheet, blank or with a few bubbles filled, and says whether it reads,
   before you print the rest.
   **Written marks** is for an exam with a written (subjective) part: set what
   it is out of, then type each student's marks. They add to the sheet's score
   for the rank, and results and scorecards show both parts.
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
   and numbers them; fix anything on the right (a second block of digit
   columns is taken as a numeric answer). **Test on this scan** reads
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

**Test series**: give exams the same test series name (in New exam, or on
Exam settings) and each new exam in it starts with the series' student list.
**Test series…** on Exams ranks students on their total score over the
series, with each test's score (absent when they have no sheet), the tests
taken and their average percentage, and saves it to Excel.

**Back up…** on Exams saves every exam, with its sheets, corrections and
students, in one file. **Restore…** adds the exams in such a file, on the same
PC or a new one; exams already there are left as they are.

## Read sheets from the command line

```
omr-read TEMPLATE.json sheets.pdf more.png --csv results.csv
```

`omr-read` takes a template and any number of PDF, PNG, JPG or TIFF files,
prints the roll number, set code and anything that needs review for each
page, and with `--csv` saves every answer to a spreadsheet-ready file.
Templates live in `templates/`.
