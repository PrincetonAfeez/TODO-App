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
make lint      # ruff + black --check
make test      # pytest (unit + integration)
make js-test   # Node tests for static helpers
make e2e       # Playwright smoke tests (requires Chromium)
make cov       # optional coverage report
```

## Conventions

- Business logic belongs in `tasks/services.py`; views orchestrate only.
- HTMX partials live under `templates/tasks/partials/` with a leading underscore.
- Architectural decisions get an ADR in `docs/adr/`.
- Match existing formatting: `black` line length 88, `ruff` with Django rules enabled.

## Tests

- Prefer pytest-django tests in `tasks/tests.py` for models, services, signals, and views.
- Browser smoke tests live in `tasks/tests_e2e.py` and are marked `@pytest.mark.e2e`.
- Pure JS helpers in `static/tasks/` have Node tests (`*.test.js`) run via `make js-test`.
