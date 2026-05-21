# ADR 0002: Soft delete via custom manager

## Status

Accepted

## Decision

`Task.objects` hides rows where `deleted_at` is set. `all_with_deleted()` and
`deleted_only()` are explicit escape hatches for restore screens, exports, and
audit-sensitive workflows.

## Consequences

Default application queries stay safe, while administrative paths can opt in to
deleted rows. Reorder and restore code must be deliberate about which manager it
uses.

