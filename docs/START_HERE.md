# Start here (evaluators)

This document is the fastest path to review the To-Do app. Read it first, then
follow the links below for depth.

## What this is

A session-scoped Django 5 + HTMX task manager (no login). Business logic lives in
`tasks/services.py`; views are thin; audit events come from signals and
service calls. Spec source: [`To-Do App.txt`](../To-Do%20App.txt).

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

Seed uses session key `seed-session`; open the app in a browser that has that
cookie or re-seed after visiting once.

## Automated checks (what CI runs)

| Check | Command |
| --- | --- |
| Lint | `python -m ruff check .` |
| Format | `python -m black --check config tasks` |
| JS helpers | `node --test static/tasks/toggle-helpers.test.js static/tasks/theme-helpers.test.js` |
| Types | `python -m mypy tasks/services.py tasks/models.py` |
| Unit tests + coverage | `python -m pytest -m "not e2e" --cov=tasks --cov-fail-under=90` |
| E2E + accessibility | `python -m playwright install chromium && python -m pytest -m e2e` |

Or use `make lint`, `make test`, `make typecheck`, `make cov`, `make e2e`.

## Where to look

| Topic | Location |
| --- | --- |
| Requirements spec | [`To-Do App.txt`](../To-Do%20App.txt) |
| Setup & architecture | [`README.md`](../README.md) |
| Edge cases + test map | [`docs/edge-cases.md`](edge-cases.md) |
| Accessibility | [`docs/accessibility.md`](accessibility.md) |
| Architecture decisions | [`docs/adr/`](adr/) (9 ADRs) |
| DB schema | [`Schema/`](../Schema/) + `tasks/test_schema_reference.py` |
| Services / domain logic | `tasks/services.py` |
| Models / querysets | `tasks/models.py` |
| HTMX views | `tasks/views.py` |
| Unit tests | `tasks/tests.py`, `tasks/test_full_coverage.py` |
| Property tests (recurrence) | `tasks/test_recurrence_hypothesis.py` |
| Browser + axe tests | `tasks/tests_e2e.py`, `tasks/tests_a11y_e2e.py` |
| Extended reference (optional) | [`todo_app_docs.md`](../todo_app_docs.md) — long-form TDD; see banner there |

## Review checklist

1. **Session scoping** — lists and tasks are isolated by `session_key` (ADR 0001).
2. **Soft delete** — default manager hides deleted rows; restore/export paths exist (ADR 0002).
3. **Recurrence** — templates spawn occurrences on complete; date math in `compute_next_due_date` (ADR 0004); Hypothesis tests in `test_recurrence_hypothesis.py`.
4. **HTMX** — partial swaps under `templates/tasks/partials/`; create returns
   `_task_list.html`; toggle/delete/restore use `_task_group.html` (ADR 0006).
   Filter OOB updates documented in `edge-cases.md`.
5. **Audit trail** — `/events/` shows `TaskEvent` rows; dedup rules in ADR 0007.
6. **Quality gates** — CI enforces ruff, black, mypy (models/services), ≥90% coverage on `tasks/`, Playwright smoke tests, axe on three pages.

## Coverage note

Coverage is measured on application code under `tasks/` (tests and migrations
omitted). The threshold is enforced in CI via `--cov-fail-under=90`.

## Questions?

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for local workflow conventions.
