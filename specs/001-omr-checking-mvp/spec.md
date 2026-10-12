# Feature Specification: OMR Checking MVP

**Feature Branch**: `001-omr-checking-mvp`

**Created**: 2026-10-12

**Status**: Draft

**Input**: Phase 1 of the OMR Checker Management System plan: an offline
Windows product that designs answer sheets, reads filled sheets live from an
ADF scanner or from scanned PDFs, grades them against an answer key, and
publishes results. It must be good enough to sell on its own.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Grade a stack of scanned sheets (Priority: P1)

An exam coordinator has an exam, an answer key typed in by hand, and a PDF of
scanned filled sheets. They import the PDF, the system reads every sheet,
grades it, and shows each student's score.

**Why this priority**: This is the core job a buyer pays for. Everything else
(live scanning, designer, licensing) builds on a reader and grader that work.

**Independent Test**: Import a fixture PDF of 50 filled sheets for a known
template and answer key; every score matches the hand-checked score.

**Acceptance Scenarios**:

1. **Given** an exam with a template and an answer key for set A, **When** the
   coordinator imports a PDF of filled set A sheets, **Then** each sheet shows
   roll number, set code, marked answers and score.
2. **Given** a sheet scanned up to 5 degrees skewed or upside down, **When**
   it is read, **Then** it is straightened and read the same as a straight scan.
3. **Given** a marking scheme of +4 correct, -1 wrong, 0 blank, **When**
   sheets are graded, **Then** scores follow that scheme exactly.
4. **Given** sheets of sets A, B, C and D mixed in one PDF, **When** they are
   read, **Then** each sheet is graded against its own set's key.

---

### User Story 2 - Review flagged answers (Priority: P1)

After reading, an operator opens a review queue that lists only the problem
items: blank or multiple answers where the scheme forbids them, half fills,
ticks, low confidence bubbles, unreadable or duplicate roll numbers. They see
the sheet image with marks overlaid, fix the item, and the score updates.

**Why this priority**: The engine never guesses (Constitution IV), so results
cannot be published until flagged items are resolved.

**Independent Test**: Import a fixture set with known problem sheets; every
problem appears in the queue, nothing else does, and a correction changes the
score and adds an audit log entry.

**Acceptance Scenarios**:

1. **Given** a sheet where question 12 has two bubbles filled, **When** it is
   read, **Then** question 12 appears in the review queue on that sheet's image.
2. **Given** a flagged item, **When** the operator picks an answer, **Then**
   the score is recalculated and the change is logged with who, when, before
   and after.
3. **Given** two sheets with the same roll number, **When** reading finishes,
   **Then** both are flagged as duplicates.

---

### User Story 3 - Publish results (Priority: P1)

The coordinator views results for an exam: score, rank, percentile, and per
question correct, wrong or blank. They export a merit list to Excel and
scorecards to PDF.

**Why this priority**: Results are the output the institute hands out; without
export the product is not usable.

**Independent Test**: For a graded fixture exam, the exported Excel merit list
matches the on-screen ranks, and each PDF scorecard matches its student's
responses.

**Acceptance Scenarios**:

1. **Given** a graded exam, **When** the coordinator exports the merit list,
   **Then** an Excel file lists every student with roll number, name, score,
   rank and percentile, with ties ranked equally.
2. **Given** a corrected answer key, **When** the coordinator re-grades,
   **Then** all scores and ranks update without rescanning.
3. **Given** a question marked as dropped or bonus, **When** re-graded,
   **Then** every student gets its marks per the scheme.

---

### User Story 4 - Scan live from an ADF scanner (Priority: P2)

An operator picks a scanner profile, loads a stack in the ADF, and presses
Scan. Each page is read and graded the moment it arrives, and the screen
shows counters (scanned, read, flagged), the latest sheet with marks overlaid,
and its score while the stack is still feeding.

**Why this priority**: Live grading is our main edge over Addmen, but it
depends on the reader from Story 1 and on scanner hardware tests.

**Independent Test**: On each supported scanner, scan 100 fixture sheets at
the scanner's rated speed; every sheet is graded before the next arrives and
results match the PDF import of the same sheets.

**Acceptance Scenarios**:

1. **Given** a TWAIN ADF scanner and a profile of 200 DPI grayscale duplex,
   **When** the operator scans 100 sheets, **Then** results appear page by page
   during the run, not after it.
2. **Given** a paper jam or double feed reported by the driver, **When** it
   happens, **Then** the run pauses, keeps every page already scanned, and
   tells the operator which sheet to feed again.
3. **Given** blank back sides in a duplex run, **When** they arrive, **Then**
   they are skipped and not counted as sheets.
4. **Given** the scan is interrupted by a crash or power cut, **When** the app
   restarts, **Then** every page graded before the stop is still there.

---

### User Story 5 - Map an existing pre-printed sheet (Priority: P2)

A buyer already has printed sheets (for example the Medical Education
Commission sample: 200 questions A to D in four columns, a 5 digit roll number
grid, set code A to D, timing marks, barcode, pink print). They load a flat
scan of a blank sheet, mark its registration marks, draw a box over each
bubble grid with its rows and columns, and save a template.

**Why this priority**: Most buyers have sheets already printed; supporting
them removes the biggest switching cost. Needed before the first sale.

**Independent Test**: Map the sample sheet from a blank scan, then read 20
filled scans of it with 100% bubble accuracy.

**Acceptance Scenarios**:

1. **Given** a blank scan, **When** the user draws a question grid box and
   says 50 rows by 4 options, **Then** the designer snaps the grid to the
   printed bubbles.
2. **Given** a pink sheet with dropout colour set to red, **When** filled
   sheets are read, **Then** the print is ignored and only pen marks count.

---

### User Story 6 - Design and print a new sheet (Priority: P3)

A user designs a sheet from blocks (question grid, roll number grid, set code,
name boxes, barcode or QR, logo, instructions), picks page size, and prints it
to PDF. The template is saved automatically.

**Why this priority**: Useful for buyers with no sheets yet, but mapping
existing sheets (Story 5) covers the first customers.

**Independent Test**: Design a 100 question sheet, print the PDF, fill and
scan 20 copies, and read them with 100% bubble accuracy.

**Acceptance Scenarios**:

1. **Given** a new design with a 100 question grid, **When** printed to PDF,
   **Then** the PDF includes registration and timing marks and the saved
   template matches the printed positions.

---

### User Story 7 - Set up institute and students (Priority: P3)

An admin sets up the institute, academic year, classes and sections, imports
students from Excel, and adds users with roles (admin, teacher, operator).

**Why this priority**: Results need student names, but Stories 1 to 3 can
work from roll numbers alone at first.

**Independent Test**: Import an Excel file of 500 students; graded sheets
show the matching names by roll number.

**Acceptance Scenarios**:

1. **Given** an Excel file with roll number, name and class columns, **When**
   imported, **Then** students are created and rows with missing or duplicate
   roll numbers are reported, not imported.
2. **Given** an operator user, **When** they log in, **Then** they can scan and
   review but not change answer keys.

---

### User Story 8 - Activate an offline licence (Priority: P3)

A buyer installs the app; it runs as a trial (limited days or sheet count,
watermarked reports). To activate, the app shows a request code; the seller
returns a signed licence file; the app checks it locally on every start.

**Why this priority**: Required to sell, but not to prove the reader works.

**Independent Test**: A licence signed for this machine activates the app
offline; the same file on another machine, or an edited file, is rejected.

**Acceptance Scenarios**:

1. **Given** a licence file signed for another machine ID, **When** loaded,
   **Then** it is rejected with a clear message.
2. **Given** a trial past its limit, **When** the user grades sheets, **Then**
   results are still viewable but exports are watermarked.

### Edge Cases

- A sheet whose registration marks are torn, folded or covered: flagged as
  unreadable with the image kept, never graded from a guess.
- A page scanned at the wrong DPI or in colour when the profile says
  grayscale: rescaled and read, or flagged if marks cannot be found.
- A sheet from a different template in the same batch: flagged, not graded.
- An answer key missing for the sheet's set code: sheet held as "no key" and
  graded when the key is added.
- A roll number not in the student list: graded and flagged as unknown student.
- A PDF that is password protected or corrupt: rejected with a message, other
  files in the batch continue.
- Light pencil marks and dark pen marks on the same sheet: both read, because
  fill is judged against that sheet's own empty and filled levels.
- Disk full during a scan run: the run stops safely with pages so far kept.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST run fully offline on Windows 10 and 11, 64-bit.
- **FR-002**: System MUST import PDF, TIFF, JPG and PNG files, single or
  multi-page, rendering PDF pages at 200 DPI.
- **FR-003**: System MUST watch a chosen folder and read each new file as it
  appears.
- **FR-004**: System MUST drive TWAIN ADF scanners page by page, with WIA as a
  fallback, in simplex or duplex at 150 to 300 DPI.
- **FR-005**: System MUST send every page, whatever its source, through one
  reading pipeline: prepare, align, identify, read, decide, grade.
- **FR-006**: System MUST correct skew and rotation using registration marks,
  and lock bubble rows using timing marks when the template has them.
- **FR-007**: System MUST support software colour dropout (keep the red
  channel) for pink or red printed sheets.
- **FR-008**: System MUST read roll number grids, set code bubbles, and
  barcodes or QR codes.
- **FR-009**: System MUST mark each answer filled, blank or multiple, and flag
  half fills, ticks and low-confidence bubbles for review instead of deciding.
- **FR-010**: System MUST support answer keys per paper set (A to D or more)
  for MCQ single answer, multi-correct, and true/false.
- **FR-011**: System MUST support marking schemes with per-question marks,
  negative marks, decimal marks, and bonus or dropped questions.
- **FR-012**: System MUST re-grade an exam after a key or scheme change
  without rescanning.
- **FR-013**: System MUST provide a review queue showing each flagged item on
  its sheet image, and log every manual change with user, time, before and
  after.
- **FR-014**: System MUST compute score, rank (ties equal) and percentile per
  exam, and export a merit list to Excel and scorecards to PDF.
- **FR-015**: System MUST save each page and its result as soon as it is
  graded, so a crash loses no graded pages.
- **FR-016**: System MUST let users map an existing sheet from a blank scan
  and design a new sheet from blocks, both saving the same template format.
- **FR-017**: System MUST import students from Excel and support users with
  admin, teacher and operator roles.
- **FR-018**: System MUST run as a trial until activated with a licence file
  signed for the PC's machine ID, verified locally on every start.
- **FR-019**: Numerical answers and matrix match questions are [NEEDS
  CLARIFICATION: in the plan's feature list for phase 1, but neither sample
  sheet uses them; include in phase 1 or move to phase 2?]
- **FR-020**: Interface language is [NEEDS CLARIFICATION: English only, or
  also Nepali or Hindi for reports?]

### Key Entities

- **Institute, AcademicYear, Class, Section, Student, User**: who sits exams
  and who runs the software.
- **SheetTemplate**: page size, registration and timing marks, field layout
  (question grids, roll number, set code, barcode, image clips), dropout
  colour, version.
- **Exam**: name, date, classes, the template used, and its paper sets.
- **AnswerKey and MarkingScheme**: per set, the correct options and marks for
  each question, negative marks, bonus and dropped questions.
- **ScannerProfile**: device, DPI, colour mode, duplex, dropout colour.
- **ScanSession / ScanBatch**: one live ADF run or one import; pages
  received, read, flagged.
- **SheetScan**: page image, roll number and set code read, confidence,
  status (graded, flagged, unreadable, duplicate).
- **Response**: question number, marked options, confidence, manually
  corrected flag.
- **Result**: score, rank, percentile per student per exam.
- **AuditLog**: who changed what, when, before and after.
- **Licence**: edition, machine ID, expiry, sheet quota, signature.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: At least 99.9% of bubbles read correctly on the fixture set of
  flat and ADF scans, with every remaining error caught by the review queue.
- **SC-002**: A page is read and graded in under 0.3 seconds on an ordinary
  PC (4 cores, 8 GB RAM), so a 60 page per minute scanner never waits.
- **SC-003**: A coordinator new to the product can go from a PDF of 100
  scanned sheets to an exported merit list in under 15 minutes.
- **SC-004**: Live scanning works page by page on at least three ADF scanner
  brands, listed in a published compatibility list.
- **SC-005**: Zero graded pages lost when the app is killed mid-run.

## Assumptions

- First customers have flat scans from ADF or flatbed scanners; phone photos
  are out of scope until phase 4.
- Answer keys are typed in by hand in phase 1; keys generated from papers
  arrive with the question bank in phase 2.
- One PC per install in phase 1; several PCs sharing a database is phase 2.
- Per-topic analytics, SMS and email alerts, ICR and OCR are later phases.
- A flat 200 DPI scan of a blank sample sheet and 10 to 20 filled ones will be
  provided to build the first template and fixture set.
- Live TWAIN scanning from Python is the main technical risk; if pytwain
  cannot deliver pages one by one on real scanners, a small C# helper feeds
  pages to the app and nothing else changes.
