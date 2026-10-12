import json
from pathlib import Path

import pytest

from omr_core.reader import read_page
from omr_core.sources import read_pages
from omr_core.template import load

ROOT = Path(__file__).parent
CASES = [(d, name) for d in sorted((ROOT / "fixtures").glob("*/")) if (d / "expected.json").exists()
         for name in json.loads((d / "expected.json").read_text())["sheets"]]


@pytest.mark.skipif(not CASES, reason="no real sheet fixtures in tests/fixtures")
@pytest.mark.parametrize("folder, name", CASES)
def test_real_sheet_has_no_silent_errors(folder, name):
    spec = json.loads((folder / "expected.json").read_text())
    template = load(next(p for p in (folder / spec["template"], ROOT.parent / "templates" / spec["template"]) if p.exists()))
    want = spec["sheets"][name]
    for page in read_pages(folder / name):
        r = read_page(page, template)
        flagged = {where for where, _ in r.flags}
        wrong = [q for q, got in r.answers.items() if got != want["answers"].get(str(q), "") and f"Q{q}" not in flagged]
        assert wrong == [], f"wrong and not flagged: {wrong}"
        assert r.roll_number in (want["roll_number"],) or any(w.startswith("roll") for w in flagged)
        assert r.set_code in (want["set_code"],) or "set code" in flagged
