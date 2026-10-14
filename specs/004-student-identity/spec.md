# Feature Specification: One student across exams

**Feature Branch**: `004-student-identity`

**Created**: 2026-10-14

**Status**: Draft

**Input**: The institute's students change from exam to exam, and so do
their roll numbers: a student can sit as 105 in one mock and 212 in the next.
Results, progress, series ranks and messages must still follow the same
person.

## The model

- **Student ID.** Every student in the Student directory has one permanent
  ID: the institute's registration or admission number when it has one,
  else one the app gives (S0001, S0002, …). Name, class, batch, email and
  phone belong to the ID. The directory's existing roll numbers become
  their students' IDs, so nothing already saved changes meaning.
- **Roll number per exam.** An exam's student list says which roll number
  each student sits under in that exam, and links each row to a directory
  student. The sheet's roll number finds the row; the row gives the person.
- **Without a list row.** An institute says once, in the directory, whether
  roll numbers change from exam to exam. When they don't (the default), a
  roll number read that isn't on the exam's list is the directory student
  with that ID, as before. When they do, it is nobody until the list, a
  confirmed name reading or a typed name says who it is. App-given IDs start
  with a letter, so they never collide with a sheet's roll number.

## User Scenarios

### US1 - Import an exam's roll list (P1)

The coordinator imports an Excel list for one exam: roll number and name,
and a Student ID column when they have one. Each row is linked:

1. by its Student ID, when the file has one (a new ID is added to the
   directory);
2. else by name, when exactly one directory student has it (ignoring case
   and spacing), using the phone number to choose between namesakes;
3. else it is a new student, added to the directory with an app-given ID.

Rows whose name fits several directory students are left unlinked and
listed; the Student ID cell on the exam's Students tab links them by hand.
The import says how many rows were linked, added and left.

### US2 - Lists from a batch or another exam (P2)

"Use a batch" and "Use the list of another exam" keep each student's link.
A batch's roll numbers are its students' IDs; a list imported afterwards
replaces them.

### US3 - Names on sheets (P1)

A sheet whose roll number has no student shows the directory student its
handwriting fits (name reading), among everyone in the directory. Confirming
it, or typing a name over the sheet's name, puts that roll number on the
exam's list linked to that student: an exact directory name links to it, a
new name adds a new student. Correcting a name only renames the directory
student when they have sat no other exam.

### US4 - Following a student (P1)

Progress, attendance, exams taken, the series merit list and the contact
used for sending results all follow the Student ID, so one student sitting
under different roll numbers is one row, shown with their latest roll
number.

## Edge cases

- Changing a student's ID in the directory carries every exam's links.
- Removing a student from the directory keeps exam lists and results; their
  rows show as not linked.
- Backups and restore carry the links.

## Out of scope

- Merging two directory students into one (later, if asked).
- Guessing a link from anything but the ID, an exact name, or a confirmed
  name reading.
