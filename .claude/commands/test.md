---
description: Run the tests and quality gates relevant to the current changes
argument-hint: [path | pattern | all]
---

Run the relevant tests and quality gates for the current work. Follow these steps.

## 1. Determine scope

Arguments given: `$ARGUMENTS`

- If `$ARGUMENTS` is empty: inspect `git status` and run the full gate set whenever `src/` or
  `tests/` changed.
- If `$ARGUMENTS` is `all`: run the full gate set.
- Otherwise treat `$ARGUMENTS` as a path or pattern: target it directly, e.g.
  `poetry run pytest tests/test_event_bus.py -q`. Still run the full gate set (ruff, mypy) even
  when scoped to one test file — this repo is small enough that scoping the lint/type gates buys
  nothing.

## 2. Run commands

From the repo root:
- `poetry run pytest tests -q` — targeted path when scoped, e.g.
  `poetry run pytest tests/test_event_bus.py -q`
- `poetry run ruff check src tests scripts`
- `poetry run ruff format --check src tests scripts`
- `poetry run mypy src`
- `poetry run lint-imports`
- `python3 scripts/check_plan_refs.py`

For a full run, use `poetry run pytest tests -q --cov=src` so the coverage floor is checked as in CI.

Only if hardware-driver files changed (`src/devices/rfid_evdev.py`, `src/devices/scanner_serial.py`):
mention that `poetry install --with hardware` is needed to type-check/import them for real (mypy
still passes without it, via `ignore_missing_imports`, but a manual import smoke-check does not).

## 3. Report honestly

- Report failures verbatim, including file:line from the tool output. Do not paraphrase or
  summarize away a stack trace.
- No hedging like "mostly passing" or "just a couple of flaky failures" — state the pass/fail count
  and list every failure.
- Never "fix" a failing test by changing the test itself to make it pass — if a test looks wrong,
  flag it explicitly and ask before touching it. This is a hard project rule.
- If a gate could not run (e.g. dependencies not installed), say
  so plainly instead of skipping silently.
