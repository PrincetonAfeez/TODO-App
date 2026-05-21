# ADR 0010: Row lock for order assignment

## Status

Accepted

## Decision

`next_order()` calls `_lock_order_scope()`, which uses `select_for_update()` on
the parent `TaskList` or subtask parent `Task` before reading `Max("order")`.

## Consequences

- PostgreSQL (production) serializes concurrent creates/reorders on the same
  scope and prevents duplicate `order` values under race.
- SQLite (local dev and CI unit tests) ignores `select_for_update()`; Django
  logs a warning but does not error. Reorder concurrency bugs will not appear
  in SQLite-only runs — use PostgreSQL or explicit concurrency tests when
  validating this path.
