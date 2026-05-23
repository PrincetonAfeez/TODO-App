# Edge cases and invariants

This app is more than a basic todo list: recurrence templates, spawned
occurrences, soft delete, audit events, and HTMX partial swaps interact in
non-obvious ways. The rules below are the contract the code and tests enforce.

**Source of truth:** `tasks/services.py`, `tasks/views.py`, and the tests cited
under each heading. When you change behavior, update this doc and the linked
tests together.

## Soft delete and managers

| Invariant | Why | Tests |
| --- | --- | --- |
| Default `Task.objects` hides `deleted_at` rows | Keeps list views simple | `tests.py::test_task_manager_hides_soft_deleted` |
| Mutations on deleted tasks return 400 | UI hides controls; POST must not bypass (including delete) | `tests.py::test_deleted_task_post_mutations_rejected`, `test_delete_already_deleted_task_returns_400` |
| `status` and `completed_at` stay aligned | Open tasks have no completion time; done tasks require one | `test_full_coverage.py::test_task_clean_rejects_status_completed_at_mismatch` |
| Restore blocked when parent is deleted | Avoid orphan subtasks in the tree | `test_full_coverage.py::test_restore_subtask_under_deleted_parent_is_rejected` |
| Delete in **Show deleted** keeps the row | Empty HTMX body would remove the row | `test_full_coverage.py::test_delete_in_show_deleted_keeps_deleted_row`, `tests_e2e.py::test_delete_in_show_deleted_keeps_deleted_badge` |
| **List delete is permanent** | Tasks use soft delete; lists hard-delete and cascade tasks (no restore) | UI confirm on list detail; `tests.py::test_delete_list_*` |
| Export excludes deleted unless `show_deleted=1` | Export links carry the current show-deleted toggle | `test_full_coverage.py::test_export_excludes_soft_deleted_by_default`, `tests.py::test_export_view_includes_soft_deleted_with_show_deleted`, `test_list_detail_export_links_carry_show_deleted` |
| Export matches active list filters | CSV/JSON reflect the same scope as the visible list | `tests.py::test_export_respects_priority_filter`, `test_list_detail_export_links_carry_active_filters` |
| JSON export includes `parent_id` and `task_list_id` on every node | Matches flat CSV linkage | `tests.py::test_export_json_nests_subtasks` |
| CSV export includes full recurrence columns | Matches JSON recurrence payload | `test_full_coverage.py::test_export_csv_includes_notes_and_recurrence` |

## Recurrence and spawn

| Invariant | Why | Tests |
| --- | --- | --- |
| Only the **template** holds `recurrence_id`; occurrences use `spawned_from` | ADR 0004 | `tests.py::test_recurring_task_spawns_next_occurrence` |
| Completing a recurring task refreshes the list when a spawn may occur | Spawned row must appear without reload | `tests.py::test_toggle_recurring_task_htmx_shows_spawned_occurrence`, `tests_e2e.py::test_recurring_task_spawns_occurrence_on_complete` |
| No second occurrence at the same `due_date` (any status, including deleted) | Re-complete must not duplicate history | `tests.py::test_spawn_skips_duplicate_*` |
| Template re-complete skips spawn when an open occurrence exists | Undo/redo complete must not stack duplicates | `tests.py::test_spawn_template_without_due_date_recomplete_does_not_duplicate` |
| Spawn anchor is stable without template `due_date` | Uses last occurrence or `completed_at`, not fresh `now()` each time | `tests.py::test_spawn_template_without_due_date_recomplete_does_not_duplicate` |
| Weekly interval capped at 52 in form and service | Form and `set_recurrence()` reject values above 52 | `tests.py::test_recurrence_form_rejects_interval_above_weekly_cap`, `test_set_recurrence_rejects_interval_above_max` |
| Weekly recurrence requires `weekday_mask` | Model, form, service, and `_next_weekly()` agree | `tests.py::test_recurrence_clean_rejects_weekly_without_weekday_mask`, `test_next_weekly_requires_weekday_mask` |
| Deleted template does not spawn | Soft-deleted rules stop the chain | `tests.py::test_spawn_returns_none_for_deleted_template` |
| Set/clear recurrence refreshes badge OOB | Row partial alone leaves stale badge | `tests.py::test_set_recurrence_view_saves_daily_rule`, `test_clear_recurrence_oob_hides_badge` |
| Recurrence date math | Property tests for daily/weekly/monthly advance rules | `test_recurrence_hypothesis.py` |

## HTMX partials and forms

| Invariant | Why | Tests |
| --- | --- | --- |
| Toggle/delete/restore swap `_task_group.html` (top-level) | Row + subtasks stay in sync (ADR 0006) | HTMX view tests throughout `tests.py` |
| Filtered mutations refresh `_task_list.html` | Row partial would drift outside active filters | `tests.py::test_toggle_under_status_filter_returns_filtered_list`, `test_delete_last_filtered_task_shows_empty_state` |
| Unfiltered delete of last task inserts empty state OOB | Empty swap body removes the group; create uses full list frame instead | `tests.py::test_htmx_delete_last_task_inserts_empty_state_oob`, `test_htmx_create_first_task_returns_list_frame_without_empty_state` |
| Create task HTMX swaps `#task-list-frame` with `_task_list.html` | Matches form target; avoids nested ids after filter changes | `tests.py::test_create_task_htmx_always_returns_task_list_frame`, `test_create_task_after_view_filter_returns_single_list_frame` |
| Filter HTMX returns list partial + OOB filter/new-form fragments | Status control and new-task form stay in sync | `tests.py::test_list_filter_htmx_oob_refreshes_new_task_form_target`, `test_list_filter_htmx_oob_refreshes_status_control` |
| Subtask prefetch ignores list filters | Parent filters must not hide children or skew `(x/y)` counts | `tests.py::test_list_detail_keeps_subtasks_under_filtered_parent` |
| Search applies to top-level title/notes only | Subtask matches do not surface parent rows | `tasks/models.py` (`apply_list_filters`) |
| Status filter applies on All view only | Today/Upcoming/Overdue are open-task date views | `tests.py::test_apply_list_filters_ignores_status_on_date_views`, `test_list_detail_disables_status_on_date_views` |
| Filter form GET uses request query, not stale `HX-Current-URL` | First filter change was ignored when URL lagged behind | `tests.py::test_list_filter_htmx_uses_request_get_not_stale_current_url` |
| New-task form notes when filters are active | Create-under-filter may hide new rows until filters change | `_new_task_form.html` uses `list_filters_active` |
| Empty notes on validation error stay empty | `\|default:` treats `""` as missing | edit form uses `\|default_if_none` in `_task_edit_form.html` | `tests.py::test_edit_form_keeps_empty_notes_on_validation_error` |
| Subtask form resets after successful add | Separate form id from `#new-task-form` | `static/tasks/app.js`, `tests_e2e.py::test_subtask_form_clears_after_add` |
| HTMX errors use `showToast` with `"error": true` | Plain 400 bodies are invisible in the UI | `tests.py::test_restore_subtask_view_error_toast_is_marked_error` |
| Sidebar/list counts use OOB fragments | Avoid stale badges after mutations | `tests.py::test_htmx_create_task_updates_sidebar_count_oob` |

## Reorder scope

| Invariant | Why | Tests |
| --- | --- | --- |
| Reorder disabled when filters/search/non-manual sort active | Partial order rewrite corrupts full list; subtask lists follow same flag | `test_full_coverage.py::test_list_detail_disables_reorder_when_filters_active`, `tests.py::test_list_detail_disables_reorder_for_active_filters` |
| Failed reorder resyncs list frame before toast | SortableJS moves DOM optimistically; server 400 must not leave stale order | `static/tasks/app.js`, `tests_e2e.py::test_reorder_failure_resyncs_list_order` |
| Normal reorder scope matches visible active rows only | Hidden soft-deleted rows must not break SortableJS | `tests.py::test_reorder_active_only_payload_with_deleted_task_in_list`, `test_reorder_view_succeeds_when_deleted_task_hidden` |
| Show-deleted reorder uses `include_deleted=True` | Rendered list includes deleted rows | `tests.py::test_reorder_tasks_includes_soft_deleted_in_scope`, `tests_e2e.py::test_reorder_in_show_deleted_view` |
| Payload must include every id in scope (no duplicates) | Prevents silent gaps | `test_full_coverage.py::test_reorder_rejects_duplicate_ids` |

## Audit events

| Invariant | Why | Tests |
| --- | --- | --- |
| Toggle/delete/restore emit lifecycle action only, not `updated` | ADR 0007 | `tests.py::test_toggle_emits_completed_without_updated` |
| Reorder and spawn logged in services | Intent-bearing events (ADR 0003) | `tests.py::test_reorder_tasks_is_scoped_and_audited` |
| Signals capture field diffs on ordinary saves | Implicit change log | `tests.py::test_task_signals_create_audit_events` |

## Accessibility

| Invariant | Why | Tests |
| --- | --- | --- |
| axe reports zero violations on key pages | CI gate for regressions (static + dynamic UI states) | `tests_a11y_e2e.py` |

## Events filters

| Invariant | Why | Tests |
| --- | --- | --- |
| Invalid list filter omitted from pagination query | Foreign list ids must not pollute `?list=` links | `tests.py::test_events_view_omits_invalid_list_from_pagination_query` |

See [`accessibility.md`](accessibility.md) for patterns and known limitations.

## Schema reference

`Schema/` mirrors `tasks/migrations/0001_initial.py`. Drift is guarded by
`tasks/test_schema_reference.py`. Django migrations remain authoritative; update
`Schema/` when models change.

## E2E smoke tests (Playwright)

Browser tests in `tasks/tests_e2e.py` cover flows referenced above:

| Test | Covers |
| --- | --- |
| `test_delete_in_show_deleted_keeps_deleted_badge` | Soft delete in show-deleted mode |
| `test_reorder_in_show_deleted_view` | Reorder with `include_deleted=True` |
| `test_subtask_form_clears_after_add` | Subtask input reset after add |
| `test_smoke_create_and_toggle_task` | Core create/toggle path |
| `test_recurrence_form_save_and_clear` | Recurrence UI |
| `test_inline_edit_task_title` | Inline edit HTMX |
| `test_restore_deleted_task_in_show_deleted_view` | Restore flow |

See `tasks/tests_e2e.py` for smoke flows. Accessibility scans live in
`tasks/tests_a11y_e2e.py` (list detail light/dark, lists, events, inline edit,
create validation error, keyboard shortcuts dialog).

Run: `make e2e` or `python -m pytest -m e2e`.
