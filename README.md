# To-Do

A session-scoped Django 5 + HTMX task manager built from `To-Do App.txt`.
It uses SQLite for development, keeps views thin, puts orchestration in
`tasks/services.py`, and records task history through model signals plus
intent-bearing service events.

## Setup

First-time clone:

**PowerShell (Windows)**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
```

**Bash / macOS / Linux**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/python manage.py migrate
```

## Run

Activate the project virtualenv first. Examples below use `.venv` in the repo root.

**PowerShell (Windows)**

```powershell
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver
```

**Bash / macOS / Linux**

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

Useful commands (PowerShell paths shown; on Bash replace with `.venv/bin/python`):

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m pytest --cov=tasks --cov-report=term-missing
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m black --check config tasks
node --test static/tasks/toggle-helpers.test.js static/tasks/theme-helpers.test.js
make e2e
.\.venv\Scripts\python manage.py seed
.\.venv\Scripts\python manage.py seed --force
```

`make run`, `make test`, `make cov`, `make lint`, `make migrate`, and `make seed`
work on any shell with `make` installed (uses `python` from your `PATH`; activate
the venv first or set `PYTHON=.venv/bin/python` / `PYTHON=.venv/Scripts/python`).

Demo data is seeded under session key `seed-session` (overdue, deleted,
recurring, and completed tasks with audit events). Use `seed --force` to reset.

## Production

Copy `.env.example` to `.env` for local overrides. WSGI/ASGI load `.env`
automatically when present, so production can set
`DJANGO_SETTINGS_MODULE=config.settings.prod` there. Development uses SQLite
by default (`config/settings/dev.py`). Production settings
(`config/settings/prod.py`) require a `DATABASE_URL` environment variable —
there is no SQLite fallback. The repo still defaults to `dev` when neither
`.env` nor the process environment sets `DJANGO_SETTINGS_MODULE`.

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
$env:DATABASE_URL = "postgres://USER:PASSWORD@HOST:5432/DBNAME"
$env:SECRET_KEY = "change-me"
.\.venv\Scripts\python manage.py migrate
```

Use `psycopg` (already in `requirements.txt`) for PostgreSQL 16+. Set
`DJANGO_SETTINGS_MODULE=config.settings.prod` on your WSGI/ASGI host.

## Architecture

```mermaid
flowchart LR
    Browser["Browser: HTMX + SortableJS"] --> Views["Django views"]
    Views --> Services["tasks/services.py"]
    Views --> QuerySets["Managers and QuerySets"]
    Services --> Models["TaskList, Task, Recurrence"]
    QuerySets --> Models
    Models --> Signals["Task signals"]
    Signals --> Events["TaskEvent audit log"]
    Services --> Events
    Models --> DB[("SQLite dev / PostgreSQL via DATABASE_URL in prod")]
    Events --> DB
```

## ER Diagram

```mermaid
erDiagram
    TASK_LIST ||--o{ TASK : owns
    TASK ||--o{ TASK : has_subtasks
    RECURRENCE ||--o{ TASK : templates
    TASK ||--o{ TASK : spawns
    TASK_LIST ||--o{ TASK_EVENT : filters
    TASK ||--o{ TASK_EVENT : records

    TASK_LIST {
      bigint id
      string name
      string session_key
      datetime created_at
      datetime updated_at
    }

    TASK {
      bigint id
      bigint task_list_id
      bigint parent_id
      string title
      text notes
      string status
      string priority
      int order
      bigint recurrence_id
      bigint spawned_from_id
      datetime due_date
      datetime completed_at
      datetime created_at
      datetime updated_at
      datetime deleted_at
    }

    RECURRENCE {
      bigint id
      string frequency
      int interval
      int weekday_mask
      int day_of_month
      date end_date
      datetime created_at
    }

    TASK_EVENT {
      bigint id
      bigint task_id
      bigint task_list_id
      string session_key
      string action
      json changes
      datetime created_at
    }
```

## Scope Covered

- Session-key scoped lists, no auth.
- Soft delete through the default task manager, with `all_with_deleted()`.
- Task CRUD, subtasks, manual ordering, filtering, CSV and JSON export.
- Daily, weekly, and monthly recurrence rules with spawned occurrences.
- Audit events from signals for implicit model changes and services for reorder/spawn.
- Tailwind UI with HTMX partials, dark mode, toasts, SortableJS, and keyboard shortcuts.
- ADRs in `docs/adr/` documenting the main architectural decisions.

## Design tradeoffs

| Topic | Choice | Why |
| --- | --- | --- |
| Scoping | Session key, no auth | Keeps focus on Django patterns without login flows; documented in ADR 0001. |
| Delete | Soft delete + custom manager | Tasks stay recoverable and auditable; default queryset stays simple. |
| Audit | Signals for diffs, services for intent | Saves capture most edits; reorder/spawn record one meaningful event (ADR 0003). |
| Audit noise | Suppress redundant `updated` events | Toggle/delete/restore emit one lifecycle event, not two (ADR 0007). |
| HTMX targets | `_task_group.html` for parent mutations | Refreshes row + subtasks in one swap (ADR 0006). |
| Sidebar counts | `annotate(Count)` + HTMX OOB | Counts open tasks only; avoids N+1 and keeps badges fresh (ADR 0008). |
| Timezone | Visitor cookie + middleware | Due dates and recurrence math follow the browser zone without user accounts. |
| Notifications | Messages for redirects, toasts for HTMX | Each transport gets appropriate feedback; see ADR 0009. |
| CSS | Tailwind CDN | Fast to ship for an academic demo; no Node build step. Acceptable tradeoff until a compiled pipeline is needed. |
| Database | SQLite dev, PostgreSQL prod | Dev defaults to SQLite; prod requires `DATABASE_URL` (see Production). |

## ADRs

| ADR | Topic |
| --- | --- |
| 0001 | Session-key scoping instead of auth |
| 0002 | Soft delete via custom manager |
| 0003 | Signals for implicit events, services for intent |
| 0004 | Recurrence template + spawned occurrences |
| 0005 | Subtask depth capped at two levels |
| 0006 | Task group partial for top-level mutations |
| 0007 | Audit event deduplication |
| 0008 | Annotated sidebar task counts |
| 0009 | Dual notification channels (messages vs toasts) |

