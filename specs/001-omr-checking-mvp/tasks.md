# Tasks: OMR Checking MVP

**Input**: [spec.md](spec.md), [plan.md](plan.md)

Format: `[ID] [P?] [Story] Description`. `[P]` can run in parallel with the
task before it.

## Phase 1: Setup

- [x] T001 Repo skeleton, CI on Windows and Linux, grading and ranking in `src/omr_core/grading.py`
- [ ] T002 Add a CI step that imports `omr_core` without PySide6 installed (Constitution II)

## Phase 2: Foundations

- [ ] T003 Template JSON format and validation in `src/omr_core/template.py`, with a template for a 100 question test sheet
- [ ] T004 [P] Generated test sheets in `tests/sheets.py` (fills, skew, noise, 180 degree rotation)
- [ ] T005 SQLite schema and audit log in `src/omr_core/store.py`; one commit per graded page
- [ ] T006 [P] Spike: pytwain page-by-page transfer on 2 to 3 real ADF scanners; record results in `specs/001-omr-checking-mvp/research.md`

## Phase 3: US1 Grade a stack of scanned sheets (P1) 🎯 MVP

- [ ] T007 [US1] Prepare and align in `src/omr_core/reader.py`: dropout, registration marks, rotation, warp
- [ ] T008 [US1] Read and decide: bubble darkness, per-sheet levels, flags with reasons
- [ ] T009 [US1] Roll number, set code, barcode and QR
- [ ] T010 [US1] PDF and image sources in `src/omr_core/sources.py` (pypdfium2, 200 DPI)
- [ ] T011 [US1] Reader tests on generated sheets: 100% accuracy, under 0.3 s per page
- [ ] T012 [US1] App: create exam, type answer key and marking scheme, import PDF, show scores

## Phase 4: US2 Review flagged answers (P1)

- [ ] T013 [US2] Correction function in `store.py` that re-grades and writes the audit log
- [ ] T014 [US2] Review queue screen in `src/omr_app/review.py`, sheet image with overlay
- [ ] T015 [US2] Duplicate roll number and unknown student flags

## Phase 5: US3 Publish results (P1)

- [ ] T016 [US3] Re-grade an exam after a key or scheme change
- [ ] T017 [US3] Excel merit list and PDF scorecards in `src/omr_core/export.py`
- [ ] T018 [US3] Results screen with rank and percentile

**Checkpoint**: P1 done. Test end to end on the real fixture set before going on.

## Phase 6: US4 Live ADF scanning (P2)

- [ ] T019 [US4] Scanner profiles and live run in `src/omr_app/scanner.py`, using the T006 spike
- [ ] T020 [US4] Worker processes reading from the page queue; live counters and latest sheet
- [ ] T021 [US4] Jam and double feed pause, blank back sides skipped, crash recovery test
- [ ] T022 [P] [US4] Watched folder source

## Phase 7: US5 Map an existing sheet (P2)

- [ ] T023 [US5] Designer: load blank scan, click registration marks, draw grids that snap to bubbles
- [ ] T024 [US5] Template for the Medical Education Commission sheet; test on its real filled scans

## Phase 8: US6 and US7 (P3)

- [ ] T025 [US6] Design new sheets from blocks and print to PDF
- [ ] T026 [P] [US7] Institute, classes and users with roles; student import from Excel

## Phase 9: Release

- [ ] T027 Nuitka build and Inno Setup installer; check against common antivirus
- [ ] T028 Accuracy and speed report on real scans from three scanner brands; compatibility list
