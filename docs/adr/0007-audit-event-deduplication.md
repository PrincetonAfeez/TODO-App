# ADR 0007: Deduplicate status and delete audit events

## Status

Accepted

## Context

ADR 0003 assigns implicit lifecycle events to signals. A naive diff on save
emits `updated` whenever tracked fields change, then also emits
`completed`, `reopened`, `soft_deleted`, or `restored` when those same
fields flip. Toggling a task therefore produced two events for one user
action, which cluttered the `/events/` log without adding meaning.

## Decision

Signals still compute a full field diff, but suppress `updated` for fields
already represented by a specific lifecycle event:

- `completed` / `reopened` cover `status` and `completed_at`
- `soft_deleted` / `restored` cover `deleted_at`

`updated` is emitted only when non-covered fields change, or when covered
fields change without triggering a lifecycle event.

## Consequences

- Toggle, delete, and restore produce one primary audit event each.
- Edits that change title and status in the same save can still emit both
  `updated` (title) and `completed` (status).
- The events log stays readable while preserving granular diffs for real edits.
