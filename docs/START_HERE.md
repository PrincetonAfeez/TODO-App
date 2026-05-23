# Start here (evaluators)

This document is the fastest path to review the To-Do app. Read it first, then
follow the links below for depth.

## What this is

A session-scoped Django 5 + HTMX task manager (no login). Domain logic lives in
`tasks/services.py`; HTMX/filter/OOB orchestration lives in `tasks/views.py`.
Behavioral contract: [`docs/edge-cases.md`](edge-cases.md).

## Quick start (5 minutes)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/ — you get an Inbox list immediately (session key
from cookie). Optional demo data:

```bash
python manage.py seed
```

By default, seed attaches data to session key `seed-session`. To load demo data
into **your current browser session** (after visiting the app once):

```bash
python manage.py seed --latest-session
python manage.py seed --latest-session --force   # replace existing demo rows
```

Or target a specific key:

```bash
python manage.py seed --session-key your-session-key-here
```

## Automated checks (what CI runs)

| Check | Command |
| --- | --- |
| Lint | `python -m ruff check .` |
| Format | `python -m black --check config tasks` |
| JS helpers | `node --test static/tasks/toggle-helpers.test.js static/tasks/theme-helpers.test.js` |
| Types | `python -m mypy tasks/models.py tasks/services.py tasks/views.py` |
| Unit tests + coverage | `python -m pytest -m "not e2e" --cov=tasks --cov-fail-under=90` |
| E2E + accessibility | `python -m playwright install chromium && python -m pytest -m e2e` |

Or use `make lint`, `make test`, `make typecheck`, `make cov`, `make e2e`.

## Where to look

| Topic | Location |
| --- | --- |
| Behavioral contract + test map | [`docs/edge-cases.md`](edge-cases.md) |
| Setup & architecture | [`README.md`](../README.md) |
| Accessibility | [`docs/accessibility.md`](accessibility.md) |
| Architecture decisions | [`docs/adr/`](adr/) (9 ADRs) |
| DB schema | [`Schema/`](../Schema/) + `tasks/test_schema_reference.py` |
| Services / domain logic | `tasks/services.py` |
| Models / querysets | `tasks/models.py` |
| HTMX views | `tasks/views.py` |
| Unit tests | `tasks/tests.py`, `tasks/test_full_coverage.py` |
| Property tests (recurrence) | `tasks/test_recurrence_hypothesis.py` |
| Browser + axe tests | `tasks/tests_e2e.py`, `tasks/tests_a11y_e2e.py` (includes dark-mode scan) |
| Extended reference (optional) | [`todo_app_docs.md`](../todo_app_docs.md) — long-form TDD; see banner there |

## Review checklist

1. **Session scoping** — lists and tasks are isolated by `session_key` (ADR 0001).
2. **Soft delete** — default manager hides deleted rows; restore/export paths exist (ADR 0002).
3. **Recurrence** — templates spawn occurrences on complete; date math in `compute_next_due_date` (ADR 0004); Hypothesis tests in `test_recurrence_hypothesis.py`.
4. **HTMX** — partial swaps under `templates/tasks/partials/`; create returns
   `_task_list.html`; toggle/delete/restore use `_task_group.html` (ADR 0006).
   Filter OOB updates documented in `edge-cases.md`.
5. **Audit trail** — `/events/` shows `TaskEvent` rows; dedup rules in ADR 0007.
6. **Quality gates** — CI enforces ruff, black, mypy (models/services/views), ≥90% coverage on `tasks/`, Playwright smoke tests, axe scans (static pages plus dynamic UI states).

## Type checking scope

mypy runs on `tasks/models.py`, `tasks/services.py`, and `tasks/views.py`.
Forms remain covered by integration and E2E tests.

## Coverage note

Coverage is measured on application code under `tasks/` (tests and migrations
omitted). The threshold is enforced in CI via `--cov-fail-under=90`.

## Questions?

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for local workflow conventions.
