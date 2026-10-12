"""omr-read: read filled sheets from files and print or save what was read.

    omr-read TEMPLATE FILE [FILE ...] [--csv results.csv]
"""

import argparse
import csv
import sys

from .reader import UnreadablePage, read_page
from .sources import read_pages
from .template import load


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="omr-read", description="Read filled OMR sheets from PDF or image files.")
    p.add_argument("template", help="sheet template (.json)")
    p.add_argument("files", nargs="+", help="PDF, PNG, JPG or TIFF files")
    p.add_argument("--csv", help="also save one row per page to this CSV file")
    args = p.parse_args(argv)
    try:
        template = load(args.template)
    except (OSError, ValueError) as e:
        print(f"can't use template: {e}", file=sys.stderr)
        return 2
    questions = sorted(g.first + r for g in template.grids if g.kind == "questions" for r in range(g.rows))
    rows, failed = [], 0
    for path in args.files:
        try:
            pages = list(read_pages(path))
        except (OSError, ValueError) as e:
            print(f"{path}: {e}", file=sys.stderr)
            failed += 1
            continue
        for n, page in enumerate(pages, 1):
            try:
                r = read_page(page, template)
            except UnreadablePage as e:
                print(f"{path} page {n}: UNREADABLE ({e})")
                rows.append([path, n, "", "", *[""] * len(questions), f"unreadable: {e}"])
                failed += 1
                continue
            answered = sum(1 for q in questions if r.answers[q])
            print(f"{path} page {n}: roll {r.roll_number}  set {r.set_code}  answered {answered}/{len(questions)}  "
                  f"flags {len(r.flags)}")
            for where, why in r.flags:
                print(f"    review {where}: {why}")
            rows.append([path, n, r.roll_number, r.set_code, *(r.answers[q] for q in questions),
                         "; ".join(f"{w}: {y}" for w, y in r.flags)])
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["file", "page", "roll_number", "set_code", *(f"Q{q}" for q in questions), "flags"])
            w.writerows(rows)
        print(f"saved {len(rows)} rows to {args.csv}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
