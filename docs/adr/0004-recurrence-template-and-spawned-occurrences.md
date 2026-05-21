# ADR 0004: Recurrence template plus spawned occurrences

## Status

Accepted

## Decision

A recurring source task owns a `Recurrence`. Completing that task, or one of its
spawned occurrences, creates the next concrete occurrence until the rule ends.
Occurrences point back to the source through `spawned_from` and do not carry
their own recurrence.

### Recurrence deletion and template removal

The spec asked whether deleting a template should null its `Recurrence` or
cascade-delete it. The app uses a split policy:

| Event | Behavior |
| --- | --- |
| User clears recurrence (`clear_recurrence`) | `task.recurrence` is set to `NULL`; the `Recurrence` row is deleted when no template still references it. |
| `Recurrence` row deleted in DB | `Task.recurrence` uses `on_delete=SET_NULL`, so templates keep their row but lose the rule link. |
| Template soft-deleted | `recurrence_id` is kept so restore brings back the rule; `spawn_next_occurrence` checks `deleted_at` and stops spawning. |
| Template hard-deleted (e.g. list cascade) | The task row is removed; orphan `Recurrence` rows may remain unless they were garbage-collected earlier. |

We did **not** cascade-delete `Recurrence` when a template task is removed.
Explicit `clear_recurrence()` owns garbage collection. Soft delete preserves
the link for restore. Hard delete orphans are an accepted tradeoff for this
demo scope.

## Consequences

Completed occurrences remain queryable history. The app avoids virtual rows,
which keeps exports, ordering, and audit behavior straightforward.
Soft-deleted templates cannot spawn new occurrences until restored.
