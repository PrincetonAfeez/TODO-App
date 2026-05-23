# Contributing

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
```

Copy `.env.example` to `.env` when you need local overrides.

## Checks before opening a PR

```powershell
make lint      # ruff + black --check + mypy (models/services)
make test      # pytest (unit + integration)
make typecheck # mypy on tasks/models.py and tasks/services.py
make js-test   # Node tests for static helpers
make e2e       # Playwright smoke + axe accessibility tests
make cov       # pytest with --cov-fail-under=90 on tasks/
```

## Conventions

- Business logic belongs in `tasks/services.py`; views orchestrate only.
- HTMX partials live under `templates/tasks/partials/` with a leading underscore.
- Architectural decisions get an ADR in `docs/adr/`.
- Match existing formatting: `black` line length 88, `ruff` with Django rules enabled.

## Documentation

When changing behavior, update code and docs together:

1. **`docs/edge-cases.md`** — behavioral invariants + test links (canonical for behavior).
2. **`docs/adr/`** — architectural decisions when the *why* changes.
3. **`README.md`** / **`docs/START_HERE.md`** — setup, CI, and evaluator path.
4. **`todo_app_docs.md`** — optional long-form reference; banner points to START_HERE.

Spec source remains **`To-Do App.txt`** (may lag; edge-cases tracks implemented behavior).

## Tests

- Prefer pytest-django tests in `tasks/tests.py` for models, services, signals, and views.
- Browser smoke tests live in `tasks/tests_e2e.py` and are marked `@pytest.mark.e2e`.
- axe accessibility scans live in `tasks/tests_a11y_e2e.py` (same marker).
- Property-based recurrence tests live in `tasks/test_recurrence_hypothesis.py`.
- Pure JS helpers in `static/tasks/` have Node tests (`*.test.js`) run via `make js-test`.
