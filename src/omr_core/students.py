"""Read a student list from Excel: roll number, name and class (US7, FR-017).

The header row can be anywhere near the top; columns are found by their
header ("roll", "name", "class" or "section"). Every row that can't be used
is reported with its row number instead of being imported.
"""

from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook


@dataclass(frozen=True)
class Student:
    roll_number: str
    name: str
    class_name: str = ""


def read_students(path: str | Path, digits: int) -> tuple[list[Student], list[str]]:
    """Students from the first sheet, and one line per skipped row saying why.

    `digits` is how many digits the sheet's roll number has; Excel drops leading
    zeros from numbers, so numeric roll numbers are padded back to that length.
    Raises ValueError when the file can't be opened or has no roll and name columns.
    """
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # openpyxl raises many types for files that aren't Excel workbooks
        raise ValueError(f"can't open {Path(path).name} as an Excel file: {e}") from e
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    wb.close()
    for h, header in enumerate(rows[:20]):
        names = [str(c or "").strip().lower() for c in header]
        roll = next((i for i, n in enumerate(names) if "roll" in n or "symbol" in n), None)
        name = next((i for i, n in enumerate(names) if "name" in n), None)
        cls = next((i for i, n in enumerate(names) if "class" in n or "section" in n), None)
        if roll is not None and name is not None:
            break
    else:
        raise ValueError("no header row with a roll number column and a name column in the first 20 rows")

    students, problems, seen = [], [], {}
    for n, row in enumerate(rows[h + 1:], start=h + 2):
        cell = lambda i: row[i] if i is not None and i < len(row) else None
        raw, who = cell(roll), str(cell(name) or "").strip()
        if raw is None and not who:
            continue  # empty row
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        number = str(raw).zfill(digits) if isinstance(raw, int) else str(raw or "").strip()
        if not number:
            problems.append(f"row {n}: no roll number")
        elif not number.isdigit() or len(number) != digits:
            problems.append(f"row {n}: roll number {number!r} isn't {digits} digits")
        elif not who:
            problems.append(f"row {n}: no name for roll number {number}")
        elif number in seen:
            problems.append(f"row {n}: roll number {number} is also on row {seen[number]}")
        else:
            seen[number] = n
            students.append(Student(number, who, str(cell(cls) or "").strip()))
    return students, problems
