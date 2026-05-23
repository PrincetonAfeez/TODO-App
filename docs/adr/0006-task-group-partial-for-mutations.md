# ADR 0006: Task group partial for top-level mutations

## Status

Accepted (amended: create-task HTMX contract)

## Context

The original spec returned `_task_row.html` from create, toggle, and delete
responses. Top-level tasks also own an inline subtask list, subtask creation
form, and SortableJS container. Swapping only the row left those siblings stale
or required extra OOB updates after every mutation.

Filter changes and create-after-filter exposed another problem: swapping a single
`_task_group.html` inside `#task-list-frame` could nest duplicate list chrome or
leave filter controls out of sync with the URL.

## Decision

**Toggle, delete, and restore** on top-level tasks return `_task_group.html`,
which wraps the row, subtask list, and subtask form in one `<article>`.

**Create task** (HTMX) returns `_task_list.html` into `#task-list-frame`, plus
OOB swaps for `#new-task-form` and filter controls (`_filter_status_select.html`)
when needed. This matches the form's fixed `hx-target` and keeps one list frame
after filtered views.

Subtask mutations return `_subtask_row.html`. Edit save returns `_task_row.html`
or `_subtask_row.html` because only the row is swapped.

## Consequences

- Toggle/delete/restore refresh the parent row and all child UI in one swap.
- Create refreshes the full visible list scope and avoids duplicate frame ids.
- Delete responses can return an empty body (removing the swapped target) plus
  OOB empty-state inserts when the last task is removed.
- See `docs/edge-cases.md` for the full HTMX contract and linked tests.
