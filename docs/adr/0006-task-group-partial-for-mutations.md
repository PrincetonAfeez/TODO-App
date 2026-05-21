# ADR 0006: Task group partial for top-level mutations

## Status

Accepted

## Context

The original spec returned `_task_row.html` from create, toggle, and delete
responses. Top-level tasks also own an inline subtask list, subtask creation
form, and SortableJS container. Swapping only the row left those siblings stale
or required extra OOB updates after every mutation.

## Decision

Top-level HTMX mutations return `_task_group.html`, which wraps the row,
subtask list, and subtask form in one `<article>`. Subtask mutations return
`_subtask_row.html`. Edit save returns `_task_row.html` or `_subtask_row.html`
because only the row is swapped. See ADR 0006 and section 6 of `To-Do App.txt`.

## Consequences

- One swap refreshes the parent row and all of its children UI.
- Delete responses can replace the entire group with an empty body, removing
  the task and its subtask chrome in one step.
- `To-Do App.txt` section 6 documents the actual partial contract per endpoint.
