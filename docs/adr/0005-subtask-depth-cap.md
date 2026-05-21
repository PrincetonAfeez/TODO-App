# ADR 0005: Subtask depth capped at two levels

## Status

Accepted

## Decision

Tasks can have direct children, but subtasks cannot have children of their own.
The model enforces this in `clean()`, and services route all creation through
normal model validation.

## Consequences

The UI and ordering rules stay simple. Completing a parent does not complete
children automatically, so users retain explicit control over each item.

