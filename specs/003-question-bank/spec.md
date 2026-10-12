# Feature Specification: Question Bank

**Feature Branch**: `003-question-bank`

**Created**: 2026-10-12

**Status**: Draft

**Input**: Phase 2 of the OMR Checker Management System plan. Teachers keep
their questions in one place, sorted by subject, chapter and topic, build
question papers from them, and get the answer keys straight into an exam,
so nobody types a key by hand. The bank is optional: exams for papers typed
or printed outside the app keep working exactly as in phase 1, with a typed
or imported answer key. Results flow back so each question shows how
students did on it. Offline, on the same PC and database as phase 1.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Set up the syllabus tree (Priority: P1)

A coordinator creates the subjects their institute teaches, each with its
chapters and each chapter's topics, for example Class 10 Science, then
Chapter 3 Metals and Non-metals, then the topic Reactivity series. They can
type the tree, or import it from an Excel sheet with subject, chapter and
topic columns.

**Why this priority**: Every question is filed under a topic, and papers are
built by choosing topics, so the tree comes first.

**Independent Test**: Import a fixture Excel file with 3 subjects, 20 chapters
and 120 topics; the tree on screen matches the file row for row, and rows
that can't be used are listed with their row numbers.

**Acceptance Scenarios**:

1. **Given** an empty bank, **When** the coordinator adds a subject, a chapter
   under it and a topic under that, **Then** the tree shows them in that order
   and they survive closing the app.
2. **Given** a topic, **When** it is renamed or dragged to another chapter,
   **Then** every question filed under it moves with it.
3. **Given** a topic that still has questions, **When** someone deletes it,
   **Then** the app refuses and says how many questions to move first.
4. **Given** an Excel file whose rows repeat a subject or chapter, **When** it
   is imported, **Then** each subject and chapter appears once, and nothing
   already in the tree is duplicated.

---

### User Story 2 - Add questions to the bank (Priority: P1)

A teacher picks a topic and adds a question: the question text, an optional
picture (a diagram or a formula photographed or cropped from a scan), the
options, the correct answer, an optional explanation, a difficulty (easy,
medium, hard) and where it came from (book, past paper and year). They can
also import many questions at once from an Excel sheet.

**Why this priority**: A paper can only be as good as the questions in the
bank, and most institutes already have hundreds in Excel or Word.

**Independent Test**: Import a fixture Excel file of 200 questions across 10
topics; each question's text, options, answer, difficulty and topic match the
file, and bad rows are listed, not imported.

**Acceptance Scenarios**:

1. **Given** a topic, **When** the teacher adds a single-answer MCQ with 4
   options and answer C, **Then** it is listed under that topic with its
   difficulty and source.
2. **Given** question types single answer, more than one correct answer,
   true or false, and a number answer (for example 12.5), **When** each is
   saved, **Then** its answer is checked against its type (a true/false
   question can't have answer C).
3. **Given** a new question whose text matches one already in the bank,
   **When** it is saved or imported, **Then** the app shows the existing one
   and asks whether to keep both.
4. **Given** a question with "All of the above" as the last option, **When**
   the teacher locks its option order, **Then** shuffled papers never move
   that option.
5. **Given** a question already used in a paper, **When** it is edited,
   **Then** the paper keeps the version it was printed with.

---

### User Story 3 - Build a paper and its exam from the bank (Priority: P1)

A teacher builds a paper: sections (for example Physics 30 questions, 4 marks
right, -1 wrong), and for each section the topics to draw from and how many
easy, medium and hard questions to take, or questions picked by hand. The
app fills the paper, the teacher swaps any question they don't like, then
generates sets A to D with questions and options shuffled. It prints each
set's question paper as a PDF and creates the exam in the checking app with
the sheet template, the sections and every set's answer key already filled
in.

**Why this priority**: This is what joins the bank to checking: no key is
typed by hand, so no key typo can mis-grade a whole class.

**Independent Test**: Build a 100-question paper with 4 sets from a fixture
bank; grade generated filled sheets for each set; every score matches the
score worked out from the bank's own answers.

**Acceptance Scenarios**:

1. **Given** a section asking for 10 easy, 15 medium and 5 hard questions
   from three topics, **When** the paper is filled, **Then** it has exactly
   those counts from those topics, with no question twice.
2. **Given** a topic with fewer questions than asked for, **When** the paper
   is filled, **Then** the app says which topic is short and by how many
   instead of filling the gap from elsewhere.
3. **Given** a finished paper, **When** sets A to D are generated, **Then**
   each set has the same questions in a different order, options are shuffled
   except where locked, and each set's key follows its own order.
4. **Given** generated sets, **When** the teacher creates the exam, **Then**
   the Check sheets page shows the keys for sets A to D and the paper's
   sections and marks, ready for scanning.
5. **Given** a paper longer than the chosen sheet has questions, **When** the
   exam is created, **Then** the app refuses and names a sheet that fits.

---

### User Story 4 - See how each question did (Priority: P2)

After an exam is checked, each question in the bank shows how often it was
answered right, the most chosen wrong option, and how well it separated
strong from weak students, from every exam it appeared in. The teacher sees
questions that are much easier or harder than their label, and questions
that strong students get wrong (often a wrong key or a badly worded
question). Each student's result shows their score per chapter and topic.

**Why this priority**: It turns the item analysis phase 1 already makes into
a better bank, but papers can be built without it.

**Independent Test**: Grade generated sheets for a paper built from the bank;
each question's stored share right matches the exam's item analysis, and a
question used in two exams shows the combined figures.

**Acceptance Scenarios**:

1. **Given** a graded exam built from the bank, **When** results are saved,
   **Then** every question in it gains that exam's share right, wrong and
   blank and its discrimination.
2. **Given** a question labelled easy that fewer than 30% answered right,
   **When** the teacher opens its topic, **Then** it is marked for a second
   look.
3. **Given** a graded exam, **When** a student's scorecard is printed,
   **Then** it shows their marks per chapter and topic of the paper.

---

### User Story 5 - Move a bank between PCs (Priority: P3)

A coordinator exports a subject, or the whole bank, to one file and imports
it on another PC, for example to share questions between branches. Nothing
goes through the internet.

**Independent Test**: Export a fixture bank with pictures, import it into an
empty install; every subject, topic, question, picture and statistic matches.

**Acceptance Scenarios**:

1. **Given** an export of one subject, **When** it is imported into a bank
   that already has that subject, **Then** new topics and questions are added,
   matching ones are not duplicated, and the import lists what it skipped.

### Edge Cases

- Questions in scripts other than English (for example Devanagari) must show
  and print correctly. [NEEDS CLARIFICATION: which languages will questions
  be written in? This decides how the PDF papers are made.]
- Formulas and chemical equations: typed with simple notation (x^2, H_2O)
  and shown as superscript and subscript, or added as a picture. [NEEDS
  CLARIFICATION: is that enough, or do teachers need a full maths editor?]
- Word files: most banks today live in Word. [NEEDS CLARIFICATION: import
  questions from Word in this phase, or Excel only?]
- A picture too large or not an image is refused with the reason.
- Two people editing the bank on two PCs at once is not supported in this
  phase (one PC per install, as in phase 1).
- A question deleted from the bank stays in the papers and exams that used it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST keep a syllabus tree of subjects, chapters and
  topics, editable on screen and importable from Excel, and file every
  question under exactly one topic.
- **FR-002**: System MUST store questions of four types (single answer,
  more than one correct answer, true or false, number answer) with text,
  optional picture, options, answer, optional explanation, difficulty and
  source, and validate the answer against the type.
- **FR-003**: System MUST import questions from Excel, listing every row it
  can't use with the reason, and warn about likely duplicates.
- **FR-004**: System MUST build papers in sections, each with its own marks,
  from topic and difficulty counts or hand-picked questions, and report a
  short topic instead of filling from elsewhere.
- **FR-005**: System MUST generate up to 8 sets by shuffling question order
  and unlocked options, and derive each set's answer key from the bank.
- **FR-006**: System MUST print each set's question paper and a teacher's key
  as PDF, offline.
- **FR-007**: System MUST create the checking exam from a paper: sheet
  template, sections and marks, and every set's key, using the phase 1 exam
  store, and refuse a sheet with too few questions.
- **FR-008**: System MUST keep a snapshot of each question as printed in each
  paper, so later edits don't change past papers or their results.
- **FR-009**: System MUST record each question's results per exam (share
  right, wrong, blank, most chosen wrong option, discrimination) and show the
  combined figures in the bank.
- **FR-010**: System MUST show students' marks per chapter and topic for
  exams built from the bank.
- **FR-011**: System MUST export and import a subject or the whole bank as a
  single file, without duplicating what is already there.
- **FR-012**: System MUST keep checking independent of the bank: creating an
  exam, entering or importing its key, scanning, grading and results MUST work
  with an empty bank, and an exam built from the bank MUST be graded the same
  way as one with a typed key.

### Key Entities

- **Syllabus node**: a subject, chapter or topic, with its parent and its
  place among its siblings.
- **Question**: type, text, picture, options (with a locked flag), answer,
  explanation, difficulty, source, topic, and when it was added and changed.
- **Paper**: name, sections (name, marks, rules or picked questions), the
  question snapshots it uses, and its sets.
- **Paper set**: set code, question order, option order per question, and the
  answer key that follows from them.
- **Question result**: one exam's figures for one question.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A teacher builds a 100-question, 4-set paper from an existing
  bank and has the exam ready to scan in under 10 minutes.
- **SC-002**: Zero answer keys typed by hand for exams built from the bank;
  every graded score matches the bank's answers.
- **SC-003**: Importing 1,000 questions from Excel takes under 30 seconds and
  lists every unusable row.
- **SC-004**: Every question used in a graded exam shows that exam's figures
  as soon as results are saved.
- **SC-005**: With no subjects or questions in the bank, every phase 1 test
  and workflow passes unchanged.

## Assumptions

- Same PC and SQLite database as phase 1; the bank adds its own tables.
- PDF papers use ReportLab, already used for scorecards.
- Pictures are stored in the database, like page images in phase 1.
- Question papers are printed on A4.
- Syllabus maker (phase 3) will reuse this syllabus tree.
- Nothing is copied from other question bank products; layouts and wording
  are our own.
