# Feature Specification: App Look, Dashboard and Settings

**Feature Branch**: `002-dashboard-ui`

**Created**: 2026-10-12

**Status**: Draft

**Input**: The app should feel modern and fully interactive: a card-based
dashboard, light and dark themes, and the user's own colours and display
preferences. Style is our own; no layouts, text or assets are copied from
other products.

## User Scenarios & Testing

### User Story 1 - See the state of checking at a glance (P1)

A coordinator opens the app and sees how many sheets were read, the average
score, how many sheets need checking, how scores are spread, and the recent
batches. Clicking any of these opens the sheets behind it.

**Independent Test**: Read a batch of generated sheets; the dashboard tiles,
ring and score chart match the Check sheets table, and clicking "To check"
shows only the sheets with review items.

### User Story 2 - Light, dark and own colours (P1)

A user picks Light, Dark or System (the Windows setting), an accent colour
from presets or a colour picker, a font size and a density. Every screen
changes at once and the choice is kept the next time the app opens.

**Independent Test**: Pick Dark, a custom accent and Large text, restart the
app; it opens with the same choices.

## Requirements

- **UI-001**: A sidebar opens Dashboard, Check sheets, Results and Settings.
  Question Bank and Syllabus show as later phases and can't be opened yet.
- **UI-002**: Dashboard: tiles for sheets read, average score, sheets to
  check and batches; a ring of sheets read cleanly against sheets to check; a
  score distribution chart; recent batches. Tiles, ring and batches are
  clickable and open the matching sheets.
- **UI-003**: Results lists sheets by score with rank and percentile (ties
  share a rank); double-clicking a row opens that sheet.
- **UI-004**: Every colour comes from one set of colour tokens, with a light
  and a dark set. Theme is System (default), Light or Dark.
- **UI-005**: Settings: theme, accent colour (presets or any colour), font
  size (Small, Normal, Large) and density (Compact, Comfortable), applied at
  once and saved between runs.
- **UI-006**: Charts are drawn with Qt itself; no new dependency.
- **UI-007**: Screens stay in `omr_app`; numbers come from `omr_core`
  (grading, rank).

## Out of Scope Here

- Keeping exams and results between runs (001 T005 and T012b). Until then the
  dashboard covers the sheets read since the app opened.
- Translations (001 FR-019).
