# ADR 0009: Dual notification channels (messages vs toasts)

## Status

Accepted

## Context

The app uses two feedback mechanisms:

- **Django messages** for full-page redirects (list rename, list create without HTMX)
- **`HX-Trigger: showToast`** for HTMX partial responses where no full page reload occurs

## Decision

Keep both channels rather than forcing one mechanism everywhere.

- Redirect-based flows render the messages block in `base.html`.
- HTMX mutations return toast triggers so feedback appears without swapping the entire layout.

## Consequences

- Slightly dual-path, but each channel matches its transport (full document vs partial).
- Tests assert both: message text after `follow=True` redirects, and `HX-Trigger` on HTMX POSTs.
