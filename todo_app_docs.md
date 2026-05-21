# Architecture Decision Record
## App — TODO App
**Task Management Group | Document 1 of 5**
**Status: Accepted**

---

## Context

The TODO App is a session-scoped Django 5 + HTMX task manager. It is intentionally more advanced than a basic CRUD list: it supports multiple lists, subtasks, soft delete and restore, manual ordering, filtering, search, recurrence templates, spawned occurrences, CSV/JSON export, task history, toasts, dark mode, keyboard shortcuts, SortableJS drag ordering, and timezone-aware due dates.

The application deliberately avoids user accounts. The browser session is the ownership boundary, which keeps the project focused on Django modeling, middleware, service functions, custom managers, signals, HTMX partials, and recurrence logic instead of authentication.

The decision was to build a Django monolith with thin views, service-layer orchestration, model/queryset helpers, signal-based audit history, and server-rendered HTMX UI.

---

## Decisions

### Decision 1 — Session-key scoping instead of user accounts

**Chosen:** Every visitor receives a Django session key. Lists are scoped by `TaskList.session_key`, and all task/list/event queries use that session boundary.

**Rejected:** Full Django auth accounts, login/logout, user profiles, or global shared task lists.

**Reason:** The app is an academic task-management project. Accounts would add a large authentication and privacy surface that is not required to demonstrate task-list architecture. Session scoping still forces the code to respect ownership boundaries while keeping setup simple.

---

### Decision 2 — Task lists as first-class containers

**Chosen:** Use `TaskList` as a model with `name`, `session_key`, timestamps, and a uniqueness rule for `(session_key, name)`.

**Rejected:** A single implicit list for every visitor.

**Reason:** Multiple lists make the app closer to real task software and give the sidebar, list counts, list deletion/rename, and exports meaningful behavior.

---

### Decision 3 — Soft delete with a custom manager

**Chosen:** Default `Task.objects` hides rows where `deleted_at` is set. `Task.objects.all_with_deleted()` exposes all rows and `deleted_only()` exposes deleted rows.

**Rejected:** Permanent deletion as the normal task removal behavior.

**Reason:** The app supports restore and audit history. Soft delete lets the UI remove tasks while still allowing recovery, export, and historical event references.

---

### Decision 4 — Two-level subtasks

**Chosen:** A top-level task can have subtasks. A subtask cannot have children.

**Rejected:** Unlimited nested subtasks.

**Reason:** Unlimited nesting complicates validation, ordering, drag-and-drop, export, templates, and accessibility. Two levels are enough to demonstrate parent/child task modeling while keeping the UI manageable.

---

### Decision 5 — Services own mutations

**Chosen:** `tasks/services.py` owns create, update, toggle, soft delete, restore, reorder, recurrence set/clear, occurrence spawning, next-due-date calculation, and export.

**Rejected:** Putting all business logic in views or model methods.

**Reason:** Views should handle HTTP, forms, redirects, and HTMX response selection. Services express domain intent and are easy to test directly.

---

### Decision 6 — Signals for implicit events, services for intent events

**Chosen:** Model signals create audit events for created, updated, completed, reopened, soft-deleted, and restored tasks. Services create intent-bearing events for reorder and spawned occurrences.

**Rejected:** Putting all event creation in views, or relying only on signals.

**Reason:** Signals reliably catch model changes. Some operations, such as reorder and recurrence spawning, have higher-level intent that is best recorded by the service that performed them.

---

### Decision 7 — Deduplicate noisy audit events

**Chosen:** Toggle/delete/restore operations emit meaningful lifecycle events instead of also emitting redundant generic update events for the same changed fields.

**Rejected:** Recording both `completed` and generic `updated` for one toggle.

**Reason:** History should be understandable. A user wants to see "completed" or "reopened," not duplicate events caused by the implementation details of `status`, `completed_at`, or `deleted_at`.

---

### Decision 8 — Recurrence templates with spawned occurrences

**Chosen:** A recurring task stores a `Recurrence`. Completing a recurring task computes the next due date and creates a new open task linked through `spawned_from`.

**Rejected:** Mutating the same task's due date forever or pre-generating many future tasks.

**Reason:** Spawned occurrences preserve completed history, avoid unbounded future rows, and keep recurrence behavior observable through audit events.

---

### Decision 9 — Visitor timezone cookie

**Chosen:** Browser JavaScript writes an IANA timezone cookie, and `VisitorTimezoneMiddleware` activates that timezone for each request.

**Rejected:** Server timezone only.

**Reason:** Due-date filters and recurrence should use the visitor's local day, especially around "today," "upcoming," overdue, and daylight-saving transitions.

---

### Decision 10 — HTMX partials and out-of-band swaps

**Chosen:** HTMX requests return task rows, task groups, form partials, sidebar-count OOB fragments, empty-state OOB fragments, and toast triggers.

**Rejected:** Full-page refresh after every task action or a JavaScript SPA.

**Reason:** A task manager benefits from fast inline updates. HTMX keeps server-rendered HTML as the source of truth while making the app feel interactive.

---

### Decision 11 — CDN frontend assets for demo scope

**Chosen:** Tailwind CSS, HTMX, SortableJS, and Lucide are loaded through CDNs; local JS handles theme, toggles, keyboard shortcuts, recurrence form visibility, focus restoration, and toasts.

**Rejected:** A compiled frontend build pipeline.

**Reason:** This is acceptable for an academic/demo app and avoids a Node build step. The known trade-off is that serious production deployment should self-host or compile these assets and add a stricter CSP.

---

## Consequences

**Positive:**
- The app demonstrates real task-management behavior without account complexity.
- Session scoping still enforces an ownership boundary.
- Soft delete supports recovery and audit history.
- Recurrence and spawned occurrences demonstrate time-based domain logic.
- Services keep complex mutations testable.
- QuerySets keep filtering, ordering, and active counts expressive.
- Signals provide consistent audit history.
- HTMX partials keep the UI responsive without a frontend framework.

**Negative / Trade-offs:**
- Losing the browser session can make tasks unreachable through the UI.
- CDN assets are not ideal for production.
- Recurrence is useful but not a full RRULE engine.
- Subtasks are intentionally limited to two levels.
- No sharing, authentication, or cross-device persistence.
- Production requires `DATABASE_URL`; there is no SQLite fallback in production.

---

## Alternatives Not Explored

- Account-based persistent TODO app.
- Multi-user sharing or team lists.
- Full calendar recurrence/RRULE support.
- Unlimited task nesting.
- API-first backend.
- Background jobs for recurrence generation.
- Compiled frontend bundle.

---

*Constitution reference: Article 1, Article 3.4, Article 4, Article 6, and Article 7.*

---


# Technical Design Document
## App — TODO App
**Task Management Group | Document 2 of 5**

---

## Overview

TODO App is a Django 5 + HTMX task manager. It provides session-scoped task lists, task/subtask CRUD, soft delete and restore, filtering, search, ordering, recurrence, spawned occurrences, audit history, CSV/JSON export, keyboard shortcuts, toasts, dark mode, and drag ordering.

**Project package:** `config`  
**Primary app:** `tasks`  
**Local settings:** `config.settings.dev`  
**Production settings:** `config.settings.prod`  
**Ownership model:** session key  
**Local database:** SQLite default  
**Production database:** `DATABASE_URL` through `django-environ`

---

## Data Flow

### First visit

```text
GET /
  → SessionKeyMiddleware creates session if needed
  → home()
  → ensure_default_list(session_key)
  → redirect /lists/<inbox_id>/
```

### Create task

```text
POST /lists/<list_id>/tasks/
  → create_task_view()
  → _list_or_404() enforces session ownership
  → TaskForm validation
  → services.create_task()
  → Task post_save signal emits CREATED event
  → HTMX task group partial + sidebar count OOB + toast
```

### Toggle recurring task

```text
POST /tasks/<task_id>/toggle/
  → services.toggle_task()
  → status/completed_at update
  → signal emits COMPLETED or REOPENED
  → spawn_next_occurrence()
  → compute_next_due_date()
  → create spawned open occurrence
  → TaskEvent(SPAWNED)
```

### Export

```text
GET /lists/<id>/export.csv or export.json
  → _export()
  → services.export_tasks(task_list, fmt)
  → all_with_deleted()
  → flat CSV or nested JSON
  → attachment response
```

---

## Module-Level Structure

```text
TODO-App/
  manage.py
  config/
    settings/base.py
    settings/dev.py
    settings/prod.py
    urls.py
    wsgi.py
    asgi.py
  tasks/
    admin.py
    apps.py
    forms.py
    middleware.py
    models.py
    services.py
    signals.py
    urls.py
    views.py
    management/commands/seed.py
    tests.py
    tests_e2e.py
  templates/
    base.html
    tasks/
      list_detail.html
      lists.html
      events.html
      partials/
  static/tasks/
    app.js
    theme-helpers.js
    toggle-helpers.js
    *.test.js
  docs/adr/
  requirements.txt
  pyproject.toml
  Makefile
```

---

## Module Dependency Graph

```text
config.urls
  ├── django admin
  └── tasks.urls

config.settings.base
  ├── django-environ
  ├── django-htmx
  ├── tasks.middleware.SessionKeyMiddleware
  └── tasks.middleware.VisitorTimezoneMiddleware

tasks.apps.TasksConfig
  └── imports tasks.signals in ready()

tasks.urls
  └── tasks.views

tasks.views
  ├── tasks.forms
  ├── tasks.models
  ├── tasks.services
  ├── HTMX response helpers
  └── templates/partials

tasks.services
  ├── tasks.models
  ├── transaction.atomic
  ├── recurrence helpers
  └── csv/json export helpers

tasks.signals
  ├── pre_save old-value snapshot
  ├── post_save diff
  └── TaskEvent creation
```

---

## Core Data Structures

### `TaskList`

Represents a list of tasks for one browser session.

Fields:
- `name`
- `session_key`
- `created_at`
- `updated_at`

Rules:
- unique `(session_key, name)`
- ordered by `name`

Query helpers:
- `for_session(session_key)`
- `with_active_task_counts()`

---

### `Task`

Represents a top-level task or subtask.

Fields:
- `task_list`
- `parent`
- `title`
- `notes`
- `due_date`
- `status`
- `priority`
- `order`
- `recurrence`
- `spawned_from`
- `completed_at`
- `deleted_at`
- timestamps

Statuses:
- `open`
- `done`

Priorities:
- `low`
- `medium`
- `high`

Validation:
- subtasks cannot have children
- subtasks must share the same list as their parent
- subtasks cannot be recurrence templates
- tasks with children cannot become subtasks

---

### `Recurrence`

Represents a recurrence rule attached to a top-level task.

Fields:
- `frequency`
- `interval`
- `weekday_mask`
- `day_of_month`
- `end_date`
- `created_at`

Frequencies:
- daily
- weekly
- monthly

Validation:
- interval at least 1
- weekday mask between 1 and 127
- day of month between 1 and 31

---

### `TaskEvent`

Audit log entry.

Fields:
- `task`
- `task_list`
- `session_key`
- `action`
- `changes`
- `created_at`

Actions:
- created
- updated
- completed
- reopened
- soft_deleted
- restored
- reordered
- spawned

---

### `ExportResult`

```python
@dataclass(frozen=True)
class ExportResult:
    filename: str
    content_type: str
    body: str
```

Used by CSV/JSON export views.

---

## Function and Class Reference

### `SessionKeyMiddleware`

Creates a session key for visitors that do not already have one.

---

### `VisitorTimezoneMiddleware`

Reads the `timezone` cookie, activates the requested `ZoneInfo`, ignores invalid zones, and deactivates timezone after the response.

---

### `ensure_default_list(session_key)`

Gets or creates the session's default `Inbox` list.

---

### `next_order(task_list, parent=None)`

Returns the next manual order integer for top-level tasks or subtasks.

---

### `create_task(...)`

Creates a trimmed task in a list or under a parent.

---

### `update_task(task, ...)`

Updates editable task fields: title, notes, due date, and priority.

---

### `toggle_task(task)`

Completes an open task or reopens a done task. When completing a recurring task, it may spawn the next occurrence.

---

### `soft_delete_task(task)`

Sets `deleted_at` on the task and its active children.

---

### `restore_task(task)`

Clears `deleted_at`. If restoring a top-level task, it restores children deleted in the same delete operation.

---

### `reorder_tasks(task_list, ordered_ids, parent=None)`

Validates that all IDs belong to the current scope, writes order values, and emits a `REORDERED` event.

---

### `set_recurrence(task, ...)`

Creates or updates recurrence rule data for a top-level task.

---

### `clear_recurrence(task)`

Removes recurrence from the task and deletes unused recurrence rows.

---

### `spawn_next_occurrence(task)`

Finds the template, computes the next due date, avoids duplicate open occurrences, creates the next task, and emits `SPAWNED`.

---

### `compute_next_due_date(base_due, recurrence)`

Computes the next daily, weekly, or monthly occurrence. Monthly recurrence clamps day 31 to the last day of shorter months and respects `end_date`.

---

### `export_tasks(task_list, fmt)`

Exports all tasks in the list, including deleted tasks. CSV is flat. JSON nests subtasks.

---

## View Reference

### `home`

Ensures the default Inbox exists and redirects to its detail page.

### `lists_view`

Renders list management or creates a new list. HTMX creation returns the sidebar partial and toast.

### `list_detail`

Renders list detail. Supports `view`, `status`, `priority`, `sort`, `q`, and `show_deleted`. HTMX returns only the task-list partial.

### `create_task_view`

Creates a top-level task and returns a task-group partial for HTMX.

### `update_task_view`

Updates a task and returns the correct row partial.

### `toggle_task_view`

Completes or reopens task. Top-level tasks return a group partial; subtasks return a subtask row partial.

### `delete_task_view`

Soft deletes task and returns an empty body plus OOB updates for HTMX.

### `restore_task_view`

Restores soft-deleted task and returns the appropriate partial.

### `create_subtask_view`

Creates a subtask under a top-level parent. Rejects subtasks of subtasks.

### `reorder_list_tasks` / `reorder_subtasks`

Persist manual ordering and return HTTP 204 on success.

### `set_recurrence_view` / `clear_recurrence_view`

Manage recurrence. Subtasks cannot recur.

### `events_view`

Displays paginated audit history scoped to the current session.

---

## State Management

State lives in:
- Django session key
- `TaskList`
- `Task`
- `Recurrence`
- `TaskEvent`
- browser `timezone` cookie
- browser theme cookie
- generated export responses

No user account state exists.

---

## Error Handling Strategy

- `_list_or_404()` and `_task_or_404()` enforce session ownership.
- Duplicate list names are caught through `IntegrityError`.
- Normal invalid task forms return 400.
- HTMX invalid forms return 422 partials.
- Reorder out-of-scope IDs return 400.
- Subtasks of subtasks return 404.
- Recurrence on subtasks returns 400.
- Production settings fail if `DATABASE_URL` is unavailable.

---

## External Dependencies

Runtime:
- Django
- django-environ
- django-htmx
- psycopg

Development/testing:
- pytest
- pytest-django
- pytest-cov
- pytest-playwright
- Playwright
- Ruff
- Black

Frontend CDNs:
- Tailwind CSS
- HTMX
- SortableJS
- Lucide

---

## Concurrency Model

The app is synchronous Django. Services use `transaction.atomic()` around important mutations such as create/update/toggle/delete/restore/reorder/recurrence. There are no async views, background workers, websockets, or task queues.

---

## Known Limitations

- Session-only ownership.
- No account recovery or cross-device sync.
- No collaboration.
- No full RRULE recurrence language.
- No compiled frontend pipeline.
- CDN dependency for frontend libraries.
- Subtasks limited to two levels.
- No persistent server-side export files.

---

## Design Patterns Used

- Django MVT
- Service layer
- Custom managers/querysets
- Soft delete
- Signal-based audit trail
- Intent events from services
- HTMX partial rendering
- Out-of-band swaps
- Session-scoped ownership
- Timezone middleware
- Seed command

---

## Verification Summary

Tests cover soft delete, subtask depth, toggle complete/reopen, recurrence spawning, reorder scope, audit events, HTMX partials, sidebar OOB counts, timezone middleware, exports, restore behavior, DST recurrence, event filters/pagination, duplicate list names, recurrence forms, invalid reorder, JavaScript helpers, and Playwright E2E flows.

---

*Constitution reference: Article 4, Article 6, Article 7, and Article 8.*

---


# Interface Design Specification
## App — TODO App
**Task Management Group | Document 3 of 5**

---

## Public Web Interface

| Method | Path | View | Success Status | Description |
|---|---|---|---:|---|
| `GET` | `/` | `home` | 302 | Create/get Inbox and redirect |
| `GET`/`POST` | `/lists/` | `lists_view` | 200/302 | List index/create |
| `GET` | `/lists/<id>/` | `list_detail` | 200 | Task list page or partial |
| `POST` | `/lists/<id>/rename/` | `rename_list` | 302 | Rename list |
| `POST` | `/lists/<id>/delete/` | `delete_list` | 302 | Delete list |
| `POST` | `/lists/<id>/tasks/` | `create_task_view` | 200/400/422 | Create task |
| `POST` | `/lists/<id>/reorder/` | `reorder_list_tasks` | 204/400 | Reorder top-level tasks |
| `GET` | `/lists/<id>/export.csv` | `export_csv` | 200 | CSV export |
| `GET` | `/lists/<id>/export.json` | `export_json` | 200 | JSON export |
| `GET` | `/tasks/<id>/edit/` | `edit_task` | 200 | Edit form partial |
| `GET` | `/tasks/<id>/row/` | `task_row` | 200 | Row partial |
| `POST` | `/tasks/<id>/` | `update_task_view` | 200/400/422 | Update task |
| `POST` | `/tasks/<id>/toggle/` | `toggle_task_view` | 200 | Complete/reopen |
| `POST` | `/tasks/<id>/delete/` | `delete_task_view` | 200/302 | Soft delete |
| `POST` | `/tasks/<id>/restore/` | `restore_task_view` | 200 | Restore |
| `POST` | `/tasks/<id>/subtasks/` | `create_subtask_view` | 200/400/404/422 | Create subtask |
| `POST` | `/tasks/<id>/reorder-subtasks/` | `reorder_subtasks` | 204/400 | Reorder subtasks |
| `POST` | `/tasks/<id>/recurrence/` | `set_recurrence_view` | 200/400/422 | Set recurrence |
| `POST` | `/tasks/<id>/recurrence/clear/` | `clear_recurrence_view` | 200 | Clear recurrence |
| `GET` | `/events/` | `events_view` | 200 | Audit events |
| any | `/admin/` | Django admin | varies | Admin |

---

## Invocation Syntax

### Local run

```powershell
.\\.venv\\Scripts\\python manage.py migrate
.\\.venv\\Scripts\\python manage.py runserver
```

### Test

```powershell
.\\.venv\\Scripts\\python -m pytest
```

### Coverage

```powershell
.\\.venv\\Scripts\\python -m pytest --cov=tasks --cov-report=term-missing
```

### Lint and format

```powershell
.\\.venv\\Scripts\\python -m ruff check .
.\\.venv\\Scripts\\python -m black --check config tasks
```

### JavaScript tests

```bash
node --test static/tasks/toggle-helpers.test.js static/tasks/theme-helpers.test.js
```

### E2E

```bash
make e2e
```

### Seed

```powershell
.\\.venv\\Scripts\\python manage.py seed
.\\.venv\\Scripts\\python manage.py seed --force
```

---

## Input Contract

### Task list form

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Trimmed; unique within session |

### Task form

| Field | Type | Required | Notes |
|---|---|---|---|
| `title` | string | Yes | Trimmed |
| `notes` | text | No | Optional |
| `due_date` | datetime | No | `YYYY-MM-DDTHH:MM` or `YYYY-MM-DD HH:MM` |
| `priority` | choice | Yes | `low`, `medium`, `high` |

### Recurrence form

| Field | Type | Required | Notes |
|---|---|---|---|
| `frequency` | choice | Yes | `daily`, `weekly`, `monthly` |
| `interval` | integer | Yes | Minimum 1 |
| `weekdays` | list | Weekly only | Bit values 1,2,4,8,16,32,64 |
| `day_of_month` | integer | Monthly only | 1 through 31 |
| `end_date` | date | No | Optional cutoff |

---

## Query Parameter Contract

### List detail

```text
/lists/<id>/?view=<view>&status=<status>&priority=<priority>&sort=<sort>&q=<query>&show_deleted=1
```

Accepted:
- `view`: `all`, `today`, `upcoming`, `overdue`
- `status`: `open`, `done`
- `priority`: `low`, `medium`, `high`
- `sort`: `manual`, `due_date`, `priority`, `created_at`
- `q`: title substring
- `show_deleted`: `1`

### Events

```text
/events/?action=<action>&list=<list_id>&page=<page>
```

---

## HTMX Contract

HTMX responses may include:
- `HX-Trigger` for `showToast`
- out-of-band sidebar count fragments
- out-of-band empty-state fragments
- task row/group partials
- HTTP 204 for reorder success
- HTTP 422 for invalid form partials

Reorder body:
```text
order=<id1>,<id2>,<id3>
```

---

## Output Contract

### CSV export

Content type:
```text
text/csv
```

Columns:
- id
- parent_id
- title
- status
- priority
- due_date
- deleted_at
- created_at

### JSON export

Content type:
```text
application/json
```

Shape:
```json
[
  {
    "id": 1,
    "title": "Parent",
    "notes": "",
    "status": "open",
    "priority": "medium",
    "due_date": null,
    "deleted_at": null,
    "subtasks": []
  }
]
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | operational | `config.settings.dev` or `config.settings.prod` |
| `SECRET_KEY` | production | Django secret |
| `DEBUG` | no | Debug flag |
| `ALLOWED_HOSTS` | production | Allowed hosts |
| `DATABASE_URL` | production | Production DB URL |

---

## Configuration Files

- `.env`: optional local environment file
- `requirements.txt`: runtime and test dependencies
- `pyproject.toml`: Black, Ruff, pytest, coverage config
- `Makefile`: common commands

---

## Side Effects

| Operation | Side Effect |
|---|---|
| first request | creates session |
| home | creates Inbox if missing |
| create task | inserts task and audit event |
| toggle | updates status, audit event, possible recurrence spawn |
| soft delete | sets `deleted_at` |
| restore | clears `deleted_at` |
| reorder | updates order and emits event |
| export | streams CSV/JSON |
| seed | creates demo data under `seed-session` |

---

## Usage Examples

### Create demo data

```powershell
python manage.py seed --force
```

### Export

```text
/lists/<id>/export.csv
/lists/<id>/export.json
```

### Filter overdue high-priority tasks

```text
/lists/<id>/?view=overdue&priority=high
```

### Show deleted tasks

```text
/lists/<id>/?show_deleted=1
```

### View completed events

```text
/events/?action=completed
```

---

## Public Python Interfaces

- `services.ensure_default_list`
- `services.create_task`
- `services.update_task`
- `services.toggle_task`
- `services.soft_delete_task`
- `services.restore_task`
- `services.reorder_tasks`
- `services.set_recurrence`
- `services.clear_recurrence`
- `services.spawn_next_occurrence`
- `services.compute_next_due_date`
- `services.export_tasks`
- `Task.objects.all_with_deleted()`
- `TaskList.objects.with_active_task_counts()`
- `VisitorTimezoneMiddleware`

---

*Constitution reference: Article 4, Article 6, and Article 8.*

---


# Runbook
## App — TODO App
**Task Management Group | Document 4 of 5**

---

## Requirements

- Python 3.12 tooling target
- Django 5
- SQLite local database
- PostgreSQL-compatible `DATABASE_URL` for production
- Node.js for JS helper tests
- Playwright/Chromium for E2E tests
- Browser JavaScript for HTMX and SortableJS behavior

---

## Installation

```powershell
python -m venv .venv
.\\.venv\\Scripts\\python -m pip install -r requirements.txt
.\\.venv\\Scripts\\python manage.py migrate
.\\.venv\\Scripts\\python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

---

## Configuration

### Development

Default:
```text
config.settings.dev
```

Behavior:
- DEBUG true
- SQLite fallback
- console email backend
- local/testserver allowed hosts

### Production

Set:
```text
DJANGO_SETTINGS_MODULE=config.settings.prod
DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/DBNAME
SECRET_KEY=<strong-secret>
ALLOWED_HOSTS=<hostnames>
```

Production behavior:
- DEBUG false
- secure cookies
- SSL redirect
- JSON console logs
- no SQLite fallback

---

## Running Tests and Checks

```powershell
python -m pytest
python -m pytest --cov=tasks --cov-report=term-missing
python -m ruff check .
python -m black --check config tasks
node --test static/tasks/toggle-helpers.test.js static/tasks/theme-helpers.test.js
make e2e
```

---

## Standard Operating Procedures

### Create a task

1. Open the Inbox list.
2. Type a title in "New task."
3. Click Add.
4. Confirm the task row appears and the sidebar count updates.

### Edit a task

1. Click edit.
2. Change title, notes, due date, or priority.
3. Save.
4. Confirm the updated row appears.

### Complete or reopen

1. Toggle the checkbox.
2. Confirm visual completed/open state.
3. Confirm event history records the lifecycle event.

### Create a subtask

1. Use the subtask input under a parent task.
2. Add subtask.
3. Confirm count updates from `0/1` to `1/1` as it is completed.

### Soft delete and restore

1. Delete a task.
2. Enable Show deleted.
3. Click Restore.

### Reorder

Drag tasks or subtasks. SortableJS posts the new ID order. Reload to verify persistence.

### Add recurrence

1. Open recurrence controls.
2. Select daily, weekly, or monthly.
3. Save.
4. Complete the task.
5. Confirm next occurrence appears if allowed.

### Export

Open:
```text
/lists/<id>/export.csv
/lists/<id>/export.json
```

### Seed

```powershell
python manage.py seed
python manage.py seed --force
```

---

## Health Checks

| Check | Healthy Result |
|---|---|
| `GET /` | Redirects to list detail |
| `GET /lists/<id>/` | HTTP 200 list UI |
| HTMX task create | HTTP 200 partial + toast/OOB |
| `GET /events/` | HTTP 200 events page |
| CSV export | HTTP 200 attachment |
| JSON export | HTTP 200 JSON attachment |

---

## Expected Output Samples

### Seed

```text
Seeded demo data for session 'seed-session' (... active tasks, overdue/deleted/recurring/completed examples, audit events).
```

### Reorder success

```text
HTTP 204
```

### Invalid reorder

```text
HTTP 400
Task ids outside reorder scope: [...]
```

### Invalid recurrence

```text
HTTP 422
```

---

## Known Failure Modes

### New empty Inbox appears

**Trigger:** New browser session or cleared cookies.

**Resolution:** This is expected for a session-scoped app.

### Duplicate list name

**Trigger:** Creating a list with the same name in the same session.

**Resolution:** Use another list name.

### Task disappears after delete

**Trigger:** Soft delete hides it from the default manager.

**Resolution:** Enable Show deleted and restore it.

### Recurrence save fails

**Trigger:** Weekly recurrence without weekdays, monthly recurrence without day of month, or recurrence attempted on subtask.

**Resolution:** Provide required fields and use top-level tasks only.

### Reorder returns 400

**Trigger:** Posted task IDs are outside the list/parent scope.

**Resolution:** Reorder only visible tasks in the current scope.

### Production startup fails

**Trigger:** Missing `DATABASE_URL`.

**Resolution:** Set a production database URL.

### UI behavior breaks

**Trigger:** CDN assets blocked.

**Resolution:** Self-host or compile frontend assets for production.

---

## Troubleshooting Decision Tree

```text
App will not start
  ├── Missing dependencies?
  │     └── pip install -r requirements.txt
  ├── Database unmigrated?
  │     └── python manage.py migrate
  ├── Production DATABASE_URL missing?
  │     └── set DATABASE_URL
  └── Wrong settings?
        └── use config.settings.dev locally

Task missing
  ├── New session?
  │     └── check session cookie
  ├── Soft-deleted?
  │     └── enable show_deleted
  ├── Hidden by filters?
  │     └── clear filters
  └── Different list?
        └── check selected list

HTMX not working
  ├── htmx CDN blocked?
  ├── CSRF cookie/header issue?
  ├── 422 form error?
  └── SortableJS CDN blocked?
```

---

## Dependency Failure Handling

### Python

```powershell
python -m pip install -r requirements.txt
```

### Playwright

```powershell
python -m playwright install chromium
python -m pytest tasks/tests_e2e.py -m e2e
```

### Node

```bash
node --test static/tasks/toggle-helpers.test.js static/tasks/theme-helpers.test.js
```

### PostgreSQL

Check `DATABASE_URL`, migrations, and psycopg installation.

---

## Recovery Procedures

### Reset local DB

```powershell
Remove-Item db.sqlite3
python manage.py migrate
python manage.py seed --force
```

### Restore a task

Enable Show deleted and click Restore.

### Clear bad filters

Open:
```text
/lists/<id>/
```

### Fix recurrence

Clear recurrence and save a new rule.

### Lost session

There is no account-based recovery. Continue in the same browser session or reseed demo data.

---

## Logging Reference

Development logs are human-readable console logs. Production switches console formatting to JSON. Domain history lives primarily in `TaskEvent`, not log files.

---

## Maintenance Notes

- Keep session ownership checks on every list/task lookup.
- Add tests before changing recurrence logic.
- Keep soft delete behavior consistent across UI and exports.
- Preserve audit event deduplication.
- Self-host frontend dependencies before serious production deployment.
- Review timezone logic whenever due-date behavior changes.
- Run JS and E2E tests after frontend partial changes.

---

*Constitution reference: Article 6, Article 5, and Article 8.*

---


# Lessons Learned
## App — TODO App
**Task Management Group | Document 5 of 5**

---

## Why This Design Was Chosen

A TODO app is familiar, but this implementation uses that familiar surface to practice deeper Django architecture. The app demonstrates task ownership, service-layer mutations, soft delete, recurring tasks, audit events, custom querysets, HTMX partial responses, out-of-band swaps, timezone middleware, exports, and browser tests.

The session-scoped model was chosen because it forces ownership-aware queries without introducing the weight of authentication. The service layer was chosen because create/update/toggle/delete/reorder/recurrence/export behavior is easier to test and maintain outside views.

---

## What Was Intentionally Omitted

- User accounts
- Cross-device sync
- Sharing and collaboration
- Unlimited nested subtasks
- Full RRULE recurrence
- Background jobs
- API-first design
- Compiled frontend asset pipeline
- Permanent server-side export storage

---

## Biggest Weakness

The biggest weakness is durability. Because data is session-scoped, a user who loses the session can lose access to their lists through the UI. That is acceptable for an academic demo, but a real task manager would need accounts or another durable identity model.

The second weakness is frontend production readiness. Tailwind, HTMX, SortableJS, and Lucide are CDN-loaded. A production version should compile or self-host these assets and add CSP hardening.

---

## Scaling Considerations

**If accounts are added:**
- replace session key ownership with user ownership
- migrate session data carefully
- update all list/task/event queries
- add account deletion and privacy flows

**If recurrence expands:**
- consider RRULE compatibility
- add recurrence preview
- decide whether occurrences spawn on completion or by scheduler

**If task volume grows:**
- review indexes
- paginate events
- consider pagination/virtualization for task lists
- optimize active-count queries

**If deployment matures:**
- self-host frontend assets
- add CSP
- add health checks
- add backup/restore documentation

---

## What the Next Refactor Would Be

1. Self-host or compile frontend assets.
2. Add account migration path.
3. Add task import to complement export.
4. Add recurrence preview before saving.
5. Add task-specific event detail view.
6. Add production deployment files for a specific host.

---

## What This Project Taught

- A simple product concept can still teach real architecture.
- Session scoping is a useful middle ground before authentication.
- Services make domain intent clearer than view-only logic.
- Signals are useful for audit logs, but intent events belong in services.
- HTMX partials require clear response contracts.
- Timezone handling matters in due-date apps.
- Tests define behavior for soft delete, recurrence, sorting, exports, events, and UI interactions.

---

*Constitution v2.0 checklist: This document satisfies Article 5, Article 6, and Article 7 for TODO App.*
