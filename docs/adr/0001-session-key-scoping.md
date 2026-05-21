# ADR 0001: Session-key scoping instead of auth

## Status

Accepted

## Decision

Task lists are owned by `session_key`. The app creates a session key for every
visitor and all list/task queries are scoped through that key.

## Consequences

The app stays lightweight and demonstrates Django session middleware without
account management. Data is browser-session-bound rather than portable across
devices.

