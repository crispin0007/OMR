# Real sheet fixtures

Each folder here is one set of real scanned sheets with hand-checked answers.
`tests/test_fixtures.py` reads every sheet and fails on any answer that is
wrong without being flagged for review. It skips when there are no folders.

```
tests/fixtures/<name>/
  expected.json
  <scans: .png, .jpg, .tif or .pdf>
```

`expected.json`:

```json
{
  "template": "sample-200q.json",
  "sheets": {
    "scan-01.png": {"roll_number": "12345", "set_code": "A",
                    "answers": {"1": "A", "4": "B"}}
  }
}
```

`template` names a file in the folder itself or in `templates/`. Questions missing from `answers` are
expected blank.

Folders named `private-*` are git-ignored: use them for sheets you can test
with but not publish.

Only add sheets you have the right to publish, with names, photos and
signatures blurred (see CONTRIBUTING.md).
