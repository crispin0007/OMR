# Contributing

Thanks for helping. This is a free, offline OMR checker for schools,
colleges and exam bodies, licensed under [Apache-2.0](LICENSE).

## Before you start

- Read the [constitution](.specify/memory/constitution.md) and
  [AGENTS.md](AGENTS.md). They are short and every pull request is checked
  against them.
- For anything bigger than a bug fix, open an issue first. New features start
  as a spec in `specs/NNN-name/spec.md`.

## Making a change

```
pip install -e ".[app,dev]"
pytest
```

- Keep each pull request to one change, with tests for any new logic.
- If you touch the reading pipeline, report accuracy on `tests/fixtures`
  before and after.
- Follow the clean-room rule in AGENTS.md: no code or layouts copied from
  other OMR products or from incompatibly licensed projects.

## Sample sheets

Real scanned sheets make the reader better. You can contribute blank and
filled scans of your sheets to `tests/fixtures`, but only sheets you have the
right to share. Remove or blur student names, photos and signatures first.

## Licence of contributions

By submitting a pull request you agree your contribution is licensed under
Apache-2.0, as section 5 of the licence describes.
