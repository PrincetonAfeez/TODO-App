# Model Summary

## TaskList

Stores a user's session-scoped list of tasks.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | bigint | Primary key |
| `name` | varchar(120) | List name |
| `session_key` | varchar(80) | Browser session scope; indexed |
| `created_at` | timestamp | Created automatically |
| `updated_at` | timestamp | Updated automatically |

Constraints:

- Unique list name per session: `(session_key, name)` — `session_key` alone is not unique

## Recurrence

Stores recurrence rules for template tasks.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | bigint | Primary key |
| `frequency` | varchar(12) | `daily`, `weekly`, or `monthly` |
| `interval` | positive integer | Defaults to `1` |
| `weekday_mask` | small integer | Optional weekly mask, 1-127 |
| `day_of_month` | small integer | Optional monthly day, 1-31 |
| `end_date` | date | Optional recurrence end date |
| `created_at` | timestamp | Created automatically |

Validation rules enforced in Django (`Recurrence.clean`), not as database CHECK constraints:

- `interval` must be at least 1 (form also caps weekly interval at 52).
- `weekday_mask` must fit 1–127 when set.
- `day_of_month` must be 1–31 when set.

No database indexes on this table (matches migration `0001_initial`).

## Task

Stores top-level tasks and subtasks. Tasks are soft-deleted with `deleted_at`.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | bigint | Primary key |
| `task_list_id` | bigint | Required FK to `TaskList` |
| `parent_id` | bigint | Optional self-FK for subtasks |
| `title` | varchar(255) | Required task title |
| `notes` | text | Optional details |
| `due_date` | timestamp | Optional due date/time |
| `status` | varchar(8) | `open` or `done`; defaults to `open` |
| `priority` | varchar(8) | `low`, `medium`, or `high`; defaults to `medium` |
| `order` | positive integer | Manual ordering value |
| `recurrence_id` | bigint | Optional FK to `Recurrence`; null on delete |
| `spawned_from_id` | bigint | Optional self-FK for recurrence-generated tasks; null on delete |
| `completed_at` | timestamp | Optional completion time |
| `created_at` | timestamp | Created automatically |
| `updated_at` | timestamp | Updated automatically |
| `deleted_at` | timestamp | Optional soft-delete time |

Database CHECK constraints (PostgreSQL reference schema only):

- `task_status_valid`: `status IN ('open', 'done')`
- `task_priority_valid`: `priority IN ('low', 'medium', 'high')`

Indexes (match migration `0001_initial`):

- `task_list_id`, `parent_id`, `status`, `due_date`, `deleted_at`
- composite `(task_list_id, parent_id, order)`

Validation rules enforced in Django (`Task.clean`):

- Subtasks cannot have their own subtasks.
- Subtasks must belong to the same task list as their parent.
- Subtasks cannot be recurrence templates.
- A task with children cannot become a subtask.

## TaskEvent

Stores audit history for task lifecycle and service events.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | bigint | Primary key |
| `task_id` | bigint | Optional FK to `Task`; null on delete |
| `task_list_id` | bigint | Optional FK to `TaskList`; null on delete |
| `session_key` | varchar(80) | Browser session scope; indexed |
| `action` | varchar(20) | Audit event action |
| `changes` | json/jsonb | Structured changes payload |
| `created_at` | timestamp | Created automatically; indexed |

Indexes: `session_key`, `created_at`, plus implicit FK indexes on `task_id` and `task_list_id`.

`action` values are validated by `TaskEventAction` choices in Python, not a database CHECK.

Actions:

- `created`
- `updated`
- `completed`
- `reopened`
- `soft_deleted`
- `restored`
- `reordered`
- `spawned`

## Relationships

- `TaskList` owns many `Task` records.
- `Task` can own child `Task` records as subtasks.
- `Recurrence` can be attached to many template `Task` records.
- A generated `Task` can point back to the template task through `spawned_from`.
- `TaskEvent` can reference both the task and task list involved in an event.

## Application behavior (not in SQL)

List views filter through `TaskQuerySet.apply_list_filters()`:

- `view=today|upcoming|overdue` — open tasks only; status query param ignored.
- `view=all` — optional `status`, `priority`, search, and sort filters apply.
- Default manager hides soft-deleted rows unless `show_deleted=1`.

CSV export (`services.CSV_COLUMNS`) includes full recurrence fields
(`recurrence_interval`, `recurrence_weekday_mask`, `recurrence_day_of_month`,
`recurrence_end_date`) alongside `recurrence_frequency`. Export views apply the
same list filters as the detail page. JSON nodes include `parent_id` and
`task_list_id` on every task (top-level and nested subtasks).

See [`docs/edge-cases.md`](../docs/edge-cases.md) for the full invariant catalog.
