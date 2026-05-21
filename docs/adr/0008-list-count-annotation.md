# ADR 0008: Annotate sidebar task counts

## Status

Accepted

## Context

The sidebar renders a task count beside every list. A per-row `@property`
on `TaskList` issued one `COUNT(*)` query per list, which is an N+1 pattern
on every page that includes the sidebar.

## Decision

Add `TaskListQuerySet.with_active_task_counts()` using
`annotate(Count("tasks", filter=Q(tasks__deleted_at__isnull=True, tasks__status=open)))`
and use it in `_lists_for_request`. HTMX OOB sidebar updates still call a single
open-task count query for the affected list only.

## Consequences

- List pages load open-task counts in one query regardless of list count.
- Completed tasks are excluded; the lists page label "open item(s)" matches the
  number shown.
- Templates keep using `list.active_task_count`; the name now comes from the
  annotation instead of a model property.
