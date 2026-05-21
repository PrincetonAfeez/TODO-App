# ADR 0003: Signals for implicit events, services for intent events

## Status

Accepted

## Decision

Model signals emit created, updated, completed, reopened, soft-deleted, and
restored events. The service layer emits reordered and spawned events because
those actions carry request-level intent that a single model diff cannot infer.

## Consequences

Audit capture is hard to bypass for normal saves, while higher-order actions
still record a meaningful event instead of a noisy event per row.

