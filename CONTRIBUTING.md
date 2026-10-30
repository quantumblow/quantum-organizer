# Contributing

- Python 3.12; `pip install -e ../quantum-locator && pip install -e ".[dev]"`.
- Every change: a failing test first (`pytest`), then the implementation, then a commit.
- Rules that decide filenames or directories live in `docs/rules/naming.md` — change the document and
  the golden cases in `tests/fixtures/naming_cases.json` together with the code.
- `make lint` (ruff + mypy) and `make test` must pass before a PR.
- Do not write state into user media directories: plans, history and caches belong in `QORG_STATE_DIR`.

## CI and the private upstream repo

`quantum-organizer` depends on `quantumblow/quantum-locator`, which is private. GitHub Actions
cannot clone another private repository with the default `GITHUB_TOKEN`, so both workflows read a
secret named `LOCATOR_REPO_TOKEN`:

- fine-grained PAT, `Contents: Read` on `quantumblow/quantum-locator` only.
- Add it under Settings → Secrets and variables → Actions.

Once `quantum-locator` is on PyPI (or made public) the checkout step and this secret can be dropped.
