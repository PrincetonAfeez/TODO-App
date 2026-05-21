"""Additional tests targeting models, services, views, forms, and helpers."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.http import HttpResponse
from django.template import Context, Template
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tasks import services
from tasks.admin import RecurrenceAdmin, TaskAdmin, TaskEventAdmin, TaskListAdmin
from tasks.forms import RecurrenceForm, TaskForm, TaskListForm
from tasks.middleware import SessionKeyMiddleware
from tasks.models import (
    Recurrence,
    RecurrenceFrequency,
    Task,
    TaskEvent,
    TaskEventAction,
    TaskList,
    TaskPriority,
)
from tasks.views import (
    _append_empty_state_oob_delete,
    _append_empty_state_oob_insert,
    _append_list_count_oob,
    _append_subtask_count_oob,
    _fetch_parent_for_subtask_count_oob,
    _ids_from_post,
    _session_key,
    _with_subtask_count_oob,
)


@pytest.fixture
def task_list():
    return TaskList.objects.create(session_key="full-cov-session", name="Coverage")


@pytest.fixture
def session_client(client):
    client.get(reverse("tasks:home"))
    return client


@pytest.fixture
def inbox(session_client):
    return TaskList.objects.filter(name="Inbox").order_by("-id").first()


# --- Model representations and properties ---


@pytest.mark.django_db
def test_model_str_representations(task_list):
    task = services.create_task(task_list=task_list, title="Task title")
    event = TaskEvent.objects.create(
        task=task,
        task_list=task_list,
        session_key=task_list.session_key,
        action=TaskEventAction.CREATED,
    )
    recurrence = Recurrence.objects.create(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=1,
    )

    assert str(task_list) == "Coverage"
    assert str(task) == "Task title"
    assert "Created at" in str(event)
    assert str(recurrence) == "Every week"


@pytest.mark.django_db
def test_recurrence_str_singular_month():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.MONTHLY,
        interval=1,
    )
    assert str(recurrence) == "Every month"


@pytest.mark.django_db
def test_task_properties_and_is_deleted(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")
    services.toggle_task(child)
    services.set_recurrence(
        parent,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
    )

    assert parent.subtask_total == 1
    assert parent.subtask_done_count == 1
    assert parent.has_recurrence_template is True
    assert parent.is_deleted is False

    services.soft_delete_task(parent)
    parent = Task.objects.all_with_deleted().get(id=parent.id)
    assert parent.is_deleted is True


@pytest.mark.django_db
def test_recurrence_clean_rejects_invalid_day_of_month():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.MONTHLY,
        interval=1,
        day_of_month=32,
    )
    with pytest.raises(ValidationError) as exc:
        recurrence.full_clean()
    assert "day_of_month" in exc.value.error_dict


@pytest.mark.django_db
def test_subtask_counts_reuse_prefetched_children(task_list):
    from django.db import connection
    from django.db.models import Prefetch
    from django.test.utils import CaptureQueriesContext

    parent = services.create_task(task_list=task_list, title="Parent")
    services.create_task(task_list=task_list, parent=parent, title="Child")
    child_qs = Task.objects.all_with_deleted().ordered()
    parent = (
        Task.objects.filter(id=parent.id)
        .prefetch_related(Prefetch("children", queryset=child_qs))
        .first()
    )

    with CaptureQueriesContext(connection) as ctx:
        assert parent.subtask_total == 1
        assert parent.subtask_done_count == 0

    assert len(ctx.captured_queries) == 0


@pytest.mark.django_db
def test_subtask_counts_exclude_deleted_from_prefetch(task_list):
    from django.db.models import Prefetch

    parent = services.create_task(task_list=task_list, title="Parent")
    deleted = services.create_task(task_list=task_list, parent=parent, title="Gone")
    services.create_task(task_list=task_list, parent=parent, title="Active")
    services.soft_delete_task(deleted)
    child_qs = Task.objects.all_with_deleted().ordered()
    parent = (
        Task.objects.filter(id=parent.id)
        .prefetch_related(Prefetch("children", queryset=child_qs))
        .first()
    )

    assert parent.subtask_total == 1
    assert parent.subtask_done_count == 0


@pytest.mark.django_db
def test_subtask_count_oob_template_hides_zero_count(task_list):
    from django.template.loader import render_to_string

    task = services.create_task(task_list=task_list, title="Solo")
    html = render_to_string(
        "tasks/partials/_subtask_count_oob.html",
        {"task": task},
    )
    assert "hidden" in html
    assert "0/0" in html


@pytest.mark.django_db
def test_append_subtask_count_oob_uses_prefetched_children(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    services.create_task(task_list=task_list, parent=parent, title="Child")
    request = RequestFactory().get("/")
    request.htmx = True
    response = HttpResponse("ok")
    parent = _fetch_parent_for_subtask_count_oob(parent.pk)

    with CaptureQueriesContext(connection) as ctx:
        _append_subtask_count_oob(request, response, parent)

    assert len(ctx.captured_queries) == 0
    assert b"0/1" in response.content


@pytest.mark.django_db
def test_with_subtask_count_oob_fetches_parent_once(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")
    request = RequestFactory().get("/")
    request.htmx = True
    response = HttpResponse("ok")

    with CaptureQueriesContext(connection) as ctx:
        _with_subtask_count_oob(request, response, child)

    assert len(ctx.captured_queries) == 2
    assert b"0/1" in response.content


@pytest.mark.django_db
def test_task_clean_rejects_nested_subtask(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")
    grandchild = Task(task_list=task_list, parent=child, title="Too deep")
    with pytest.raises(ValidationError) as exc:
        grandchild.full_clean()
    assert "parent" in exc.value.error_dict


@pytest.mark.django_db
def test_task_queryset_all_with_deleted_and_occurrences(task_list):
    template = services.create_task(task_list=task_list, title="Template")
    services.set_recurrence(
        template,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
    )
    services.toggle_task(template)
    occurrence = Task.objects.get(spawned_from=template)

    qs = Task.objects.filter(task_list=task_list)
    assert qs.all_with_deleted().filter(id=template.id).exists()
    assert qs.occurrences_of(template).get(id=occurrence.id).title == "Template"


@pytest.mark.django_db
def test_task_list_queryset_for_session_and_counts(task_list):
    services.create_task(task_list=task_list, title="Open")
    done = services.create_task(task_list=task_list, title="Done")
    services.toggle_task(done)

    annotated = (
        TaskList.objects.for_session(task_list.session_key)
        .with_active_task_counts()
        .get(id=task_list.id)
    )
    assert annotated.active_task_count == 1


# --- Service layer ---


@pytest.mark.django_db
def test_ensure_default_list_is_idempotent():
    first = services.ensure_default_list("new-session")
    second = services.ensure_default_list("new-session")
    assert first.id == second.id
    assert first.name == "Inbox"


@pytest.mark.django_db
def test_next_order_increments_within_scope(task_list):
    first = services.create_task(task_list=task_list, title="First")
    parent = services.create_task(task_list=task_list, title="Parent")
    second = services.create_task(task_list=task_list, title="Second")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")

    assert second.order > first.order
    assert child.order == services.next_order(task_list, parent) - 1
    assert services.next_order(TaskList.objects.create(session_key="x", name="Y")) == 0


@pytest.mark.django_db
def test_create_and_update_task_with_optional_fields(task_list):
    due = timezone.now() + timezone.timedelta(days=1)
    task = services.create_task(
        task_list=task_list,
        title="  Notes task  ",
        notes="  Some notes  ",
        due_date=due,
        priority=TaskPriority.HIGH,
    )
    assert task.title == "Notes task"
    assert task.notes == "Some notes"

    updated = services.update_task(
        task,
        title="Updated",
        notes="New notes",
        due_date=None,
        priority=TaskPriority.LOW,
    )
    assert updated.title == "Updated"
    assert updated.notes == "New notes"
    assert updated.due_date is None


@pytest.mark.django_db
def test_soft_delete_cascades_to_open_children(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")
    services.soft_delete_task(parent)
    assert (
        Task.objects.all_with_deleted()
        .filter(id=child.id, deleted_at__isnull=False)
        .exists()
    )


@pytest.mark.django_db
def test_restore_subtask_does_not_restore_siblings(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")
    services.soft_delete_task(child)
    child = Task.objects.all_with_deleted().get(id=child.id)
    services.restore_task(child)
    assert Task.objects.filter(id=child.id).exists()


@pytest.mark.django_db
def test_set_recurrence_weekly_and_monthly(task_list):
    task = services.create_task(task_list=task_list, title="Recurring")
    weekly = services.set_recurrence(
        task,
        frequency=RecurrenceFrequency.WEEKLY,
        interval=2,
        weekday_mask=4,
    )
    assert weekly.weekday_mask == 4
    assert weekly.day_of_month is None

    monthly = services.set_recurrence(
        task,
        frequency=RecurrenceFrequency.MONTHLY,
        interval=1,
        day_of_month=15,
        end_date=date(2026, 12, 31),
    )
    assert monthly.day_of_month == 15
    assert monthly.end_date == date(2026, 12, 31)


@pytest.mark.django_db
def test_clear_recurrence_keeps_shared_recurrence_record(task_list):
    first = services.create_task(task_list=task_list, title="One")
    second = services.create_task(task_list=task_list, title="Two")
    recurrence = services.set_recurrence(
        first,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
    )
    second.recurrence = recurrence
    second.save(update_fields=["recurrence", "updated_at"])

    services.clear_recurrence(first)

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.recurrence_id is None
    assert second.recurrence_id == recurrence.id
    assert Recurrence.objects.filter(id=recurrence.id).exists()


@pytest.mark.django_db
def test_spawn_occurrence_from_completed_child_template(task_list):
    due = timezone.now() + timezone.timedelta(hours=3)
    template = services.create_task(
        task_list=task_list,
        title="Template",
        due_date=due,
    )
    services.set_recurrence(
        template,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
    )
    services.toggle_task(template)
    occurrence = Task.objects.get(spawned_from=template)
    services.toggle_task(occurrence)

    occurrences = Task.objects.filter(spawned_from=template).order_by("id")
    assert occurrences.count() == 2


@pytest.mark.django_db
def test_spawn_returns_none_without_due_date_when_end_passed(task_list):
    task = services.create_task(task_list=task_list, title="No due")
    services.set_recurrence(
        task,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
        end_date=timezone.localdate() - timezone.timedelta(days=1),
    )
    services.toggle_task(task)
    assert services.spawn_next_occurrence(task) is None


@pytest.mark.django_db
def test_compute_next_due_date_returns_none_past_end_date():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
        end_date=date(2019, 12, 31),
    )
    base = timezone.make_aware(datetime(2019, 12, 31, 9, 0))
    assert services.compute_next_due_date(base, recurrence) is None


@pytest.mark.django_db
def test_next_weekly_returns_next_masked_weekday():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=1,
        weekday_mask=2,
    )
    monday = timezone.localtime(timezone.make_aware(datetime(2024, 6, 3, 9, 0)))
    tuesday = services._next_weekly(monday, recurrence)
    assert tuesday.weekday() == 1


def test_next_weekly_falls_back_when_mask_never_aligns():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=371,
        weekday_mask=1,
    )
    sunday = timezone.localtime(timezone.make_aware(datetime(2024, 6, 9, 9, 0)))
    fallback = services._next_weekly(sunday, recurrence)
    assert fallback == services._add_local_days(sunday, 7 * 371)


@pytest.mark.django_db
def test_next_monthly_uses_base_day_when_day_of_month_missing():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.MONTHLY,
        interval=1,
        day_of_month=None,
    )
    base = timezone.localtime(timezone.make_aware(datetime(2024, 1, 15, 9, 0)))
    nxt = services._next_monthly(base, recurrence)
    assert nxt.month == 2
    assert nxt.day == 15


@pytest.mark.django_db
def test_export_empty_list_csv_and_json(task_list):
    csv_result = services.export_tasks(task_list, fmt="csv")
    json_result = services.export_tasks(task_list, fmt="json")

    assert csv_result.filename == "coverage.csv"
    assert json_result.filename == "coverage.json"
    assert json_result.body.strip() == "[]"
    assert "id,parent_id,title" in csv_result.body


@pytest.mark.django_db
def test_export_includes_deleted_rows(task_list):
    task = services.create_task(task_list=task_list, title="Deleted export")
    services.soft_delete_task(task)
    result = services.export_tasks(task_list, fmt="json")
    assert "Deleted export" in result.body
    assert "deleted_at" in result.body


@pytest.mark.django_db
def test_export_filename_preserves_unicode_list_names(task_list):
    task_list.name = "任务"
    task_list.save()
    result = services.export_tasks(task_list, fmt="json")
    assert result.filename == "任务.json"


@pytest.mark.django_db
def test_export_filename_fallback_for_blank_name(task_list):
    task_list.name = "---"
    task_list.save()
    result = services.export_tasks(task_list, fmt="csv")
    assert result.filename == "tasks.csv"


# --- View helpers ---


def test_ids_from_post_fallback_when_getlist_empty():
    request = SimpleNamespace(
        POST=SimpleNamespace(
            getlist=lambda key: [],
            get=lambda key, default="": "9 8 7" if key == "order" else default,
        )
    )
    assert _ids_from_post(request) == ["9", "8", "7"]


@pytest.mark.django_db
def test_view_oob_helpers_skip_without_htmx(task_list):
    request = RequestFactory().get("/")
    request.htmx = False
    response = HttpResponse("ok")

    assert _append_list_count_oob(request, response, task_list).content == b"ok"
    assert _append_empty_state_oob_delete(request, response).content == b"ok"
    assert _append_empty_state_oob_insert(request, response).content == b"ok"
    assert _append_subtask_count_oob(request, response, task_list).content == b"ok"


# --- Views and URLs ---


@pytest.mark.django_db
def test_home_creates_session_and_redirects(client):
    client.cookies.clear()
    response = client.get(reverse("tasks:home"))
    assert response.status_code == 302
    assert client.session.session_key


@pytest.mark.django_db
def test_list_detail_full_page_renders(session_client, inbox):
    services.create_task(task_list=inbox, title="UX check")
    response = session_client.get(reverse("tasks:list_detail", args=[inbox.id]))
    assert response.status_code == 200
    assert b"task-list-frame" in response.content
    assert b'id="task-filters-form"' in response.content
    assert b"change from:select" in response.content
    assert b'aria-label="Edit task"' in response.content
    assert b"Add details" in response.content
    assert b"keyboard-shortcuts-dialog" in response.content


@pytest.mark.django_db
def test_create_task_invalid_title_htmx_returns_inline_errors(session_client, inbox):
    response = session_client.post(
        reverse("tasks:create_task", args=[inbox.id]),
        {
            "title": "   ",
            "due_date": "2024-06-15T14:30",
            "priority": "medium",
            "notes": "",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert response["HX-Retarget"] == "#new-task-form"
    assert b"new-task-form-errors" in response.content
    assert b"aria-invalid" in response.content
    assert b'value="2024-06-15T14:30"' in response.content


@pytest.mark.django_db
def test_update_task_invalid_title_htmx_returns_edit_form(session_client, inbox):
    task = services.create_task(task_list=inbox, title="Keep me")

    response = session_client.post(
        reverse("tasks:update_task", args=[task.id]),
        {"title": "   ", "notes": "", "priority": "medium"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert b"edit-task-form-errors" in response.content
    assert b'data-edit-form' in response.content


@pytest.mark.django_db
def test_create_subtask_invalid_title_htmx_returns_inline_errors(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")

    response = session_client.post(
        reverse("tasks:create_subtask", args=[parent.id]),
        {"title": "   ", "priority": "medium"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert response["HX-Retarget"] == f"#subtask-form-{parent.id}"
    assert b"subtask-form-errors" in response.content


@pytest.mark.django_db
def test_list_detail_ignores_invalid_filter_values(session_client, inbox):
    services.create_task(task_list=inbox, title="Visible")
    response = session_client.get(
        reverse("tasks:list_detail", args=[inbox.id]),
        {"status": "invalid", "priority": "invalid", "sort": "manual"},
    )
    assert b"Visible" in response.content


@pytest.mark.django_db
def test_events_view_renders_and_filters_by_action(session_client, inbox):
    task = services.create_task(task_list=inbox, title="Audit")
    services.toggle_task(task)

    response = session_client.get(
        reverse("tasks:events"),
        {"action": TaskEventAction.COMPLETED},
    )
    assert response.status_code == 200
    assert b"Completed" in response.content or b"completed" in response.content


@pytest.mark.django_db
def test_events_view_invalid_list_filter_ignored(session_client, inbox):
    response = session_client.get(reverse("tasks:events"), {"list": "not-a-number"})
    assert response.status_code == 200


@pytest.mark.django_db
def test_htmx_sidebar_create_without_current_list_id(session_client, inbox):
    response = session_client.post(
        reverse("tasks:lists"),
        {"name": "Side list"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert b"Side list" in response.content
    assert "HX-Trigger" in response


@pytest.mark.django_db
def test_delete_subtask_updates_parent_count_oob(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")
    child = services.create_task(task_list=inbox, parent=parent, title="Child")

    response = session_client.post(
        reverse("tasks:delete_task", args=[child.id]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert f"subtask-count-{parent.id}".encode() in response.content


@pytest.mark.django_db
def test_restore_subtask_view_returns_row(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")
    child = services.create_task(task_list=inbox, parent=parent, title="Child")
    services.soft_delete_task(child)
    child = Task.objects.all_with_deleted().get(id=child.id)

    response = session_client.post(
        reverse("tasks:restore_task", args=[child.id]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"subtask-row" in response.content


@pytest.mark.django_db
def test_update_subtask_view_returns_row_and_oob(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")
    child = services.create_task(task_list=inbox, parent=parent, title="Old")

    response = session_client.post(
        reverse("tasks:update_task", args=[child.id]),
        {"title": "New child", "notes": "", "priority": "medium"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"New child" in response.content
    assert f"subtask-count-{parent.id}".encode() in response.content


@pytest.mark.django_db
def test_set_recurrence_monthly_via_view(session_client, inbox):
    task = services.create_task(task_list=inbox, title="Monthly")

    response = session_client.post(
        reverse("tasks:set_recurrence", args=[task.id]),
        {"frequency": "monthly", "interval": "1", "day_of_month": "10"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.recurrence.day_of_month == 10


@pytest.mark.django_db
def test_lists_view_handles_duplicate_name_integrity_error(client):
    from unittest.mock import patch

    client.get(reverse("tasks:home"))

    with patch(
        "tasks.views.TaskList.save",
        side_effect=IntegrityError,
    ):
        response = client.post(reverse("tasks:lists"), {"name": "Projects"})

    assert response.status_code == 200
    assert b"already have a list with that name" in response.content


@pytest.mark.django_db
def test_set_recurrence_weekly_htmx_shows_inline_errors(session_client, inbox):
    task = services.create_task(task_list=inbox, title="Weekly")

    response = session_client.post(
        reverse("tasks:set_recurrence", args=[task.id]),
        {"frequency": "weekly", "interval": "3", "end_date": "2026-12-01"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert response["HX-Retarget"] == f"#recurrence-form-{task.id}"
    assert b"weekday" in response.content.lower()
    assert b'value="3"' in response.content
    assert b'value="2026-12-01"' in response.content


@pytest.mark.django_db
def test_set_recurrence_view_returns_form_errors(session_client, inbox):
    task = services.create_task(task_list=inbox, title="Bad monthly")

    response = session_client.post(
        reverse("tasks:set_recurrence", args=[task.id]),
        {"frequency": "monthly", "interval": "1"},
    )

    assert response.status_code == 422
    assert b"day of the month" in response.content.lower()


@pytest.mark.django_db
def test_set_recurrence_422_preserves_submitted_values(session_client, inbox):
    task = services.create_task(task_list=inbox, title="Keep input")
    services.set_recurrence(
        task,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
    )
    task.refresh_from_db()

    response = session_client.post(
        reverse("tasks:set_recurrence", args=[task.id]),
        {
            "frequency": "weekly",
            "interval": "5",
            "end_date": "2026-12-01",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert b'value="5"' in response.content
    assert b"weekly" in response.content
    assert b'value="2026-12-01"' in response.content


@pytest.mark.django_db
def test_set_recurrence_422_keeps_day_of_month(session_client, inbox):
    task = services.create_task(task_list=inbox, title="Keep day")

    response = session_client.post(
        reverse("tasks:set_recurrence", args=[task.id]),
        {
            "frequency": "monthly",
            "interval": "0",
            "day_of_month": "15",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert b'value="15"' in response.content
    assert b"monthly" in response.content


@pytest.mark.django_db
def test_list_detail_404_for_other_session(client):
    other = TaskList.objects.create(session_key="other-session", name="Private")
    client.get(reverse("tasks:home"))
    response = client.get(reverse("tasks:list_detail", args=[other.id]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_rename_list_invalid_name_still_redirects(session_client, inbox):
    response = session_client.post(
        reverse("tasks:rename_list", args=[inbox.id]),
        {"name": ""},
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_reorder_subtasks_invalid_parent_returns_400(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")
    response = session_client.post(
        reverse("tasks:reorder_subtasks", args=[parent.id]),
        {"order": "999"},
    )
    assert response.status_code == 400


# --- Forms ---


@pytest.mark.django_db
def test_task_list_form_strips_name():
    form = TaskListForm({"name": "  Trimmed  "})
    assert form.is_valid()
    assert form.cleaned_data["name"] == "Trimmed"


@pytest.mark.django_db
def test_task_form_rejects_blank_title():
    form = TaskForm({"title": "   ", "notes": "", "priority": TaskPriority.MEDIUM})
    assert form.is_valid() is False


@pytest.mark.django_db
def test_task_form_accepts_datetime_local_format():
    form = TaskForm(
        {
            "title": "Due",
            "notes": "",
            "priority": TaskPriority.MEDIUM,
            "due_date": "2026-05-21T14:30",
        }
    )
    assert form.is_valid()


@pytest.mark.django_db
def test_recurrence_form_daily_and_monthly_valid():
    daily = RecurrenceForm({"frequency": "daily", "interval": "3"})
    monthly = RecurrenceForm(
        {
            "frequency": "monthly",
            "interval": "1",
            "day_of_month": "12",
            "end_date": "2026-12-01",
        }
    )
    assert daily.is_valid()
    assert monthly.is_valid()


# --- Middleware, admin, templatetags, signals ---


@pytest.mark.django_db
def test_session_key_middleware_creates_session():
    created = []

    def get_response(request):
        created.append(request.session.session_key)
        return HttpResponse("ok")

    middleware = SessionKeyMiddleware(get_response)
    request = RequestFactory().get("/")
    from django.contrib.sessions.middleware import SessionMiddleware

    SessionMiddleware(get_response).process_request(request)
    request.session.save()

    middleware(request)
    assert created[0] is not None


@pytest.mark.django_db
def test_session_key_view_helper_creates_session():
    def get_response(request):
        return HttpResponse("ok")

    request = RequestFactory().get("/")
    from django.contrib.sessions.middleware import SessionMiddleware

    SessionMiddleware(get_response).process_request(request)
    assert request.session.session_key is None

    key = _session_key(request)
    assert key is not None
    assert request.session.session_key == key


@pytest.mark.django_db
def test_admin_classes_register_models(task_list):
    site = AdminSite()
    task = services.create_task(task_list=task_list, title="Admin")
    event = TaskEvent.objects.create(
        task=task,
        task_list=task_list,
        session_key=task_list.session_key,
        action=TaskEventAction.CREATED,
    )
    recurrence = Recurrence.objects.create(
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
    )

    assert TaskListAdmin(TaskList, site).list_display == (
        "name",
        "session_key",
        "created_at",
    )
    assert TaskAdmin(Task, site).get_queryset(None).filter(id=task.id).exists()
    assert RecurrenceAdmin(Recurrence, site).list_display[0] == "frequency"
    assert RecurrenceAdmin(Recurrence, site).get_queryset(None).filter(
        id=recurrence.id
    ).exists()
    assert (
        TaskEventAdmin(TaskEvent, site).get_queryset(None).filter(id=event.id).exists()
    )


@pytest.mark.django_db
def test_weekday_checked_template_filter():
    from tasks.templatetags.task_extras import weekday_checked

    recurrence = Recurrence(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=1,
        weekday_mask=18,
    )
    template = Template(
        "{% load task_extras %}"
        "{{ none_rec|weekday_checked:2 }}"
        "{{ recurrence|weekday_checked:2 }}"
        "{{ recurrence|weekday_checked:1 }}"
    )
    rendered = template.render(Context({"recurrence": recurrence, "none_rec": None}))
    assert rendered == "FalseTrueFalse"
    assert weekday_checked(recurrence, "bad") is False


def test_weekday_selected_prefers_bound_form_data():
    from tasks.forms import RecurrenceForm
    from tasks.templatetags.task_extras import _weekday_selected

    form = RecurrenceForm(
        {
            "frequency": "weekly",
            "interval": "2",
            "weekdays": ["4", "16"],
        }
    )
    assert _weekday_selected(form, None, 4) is True
    assert _weekday_selected(form, None, 1) is False


@pytest.mark.django_db
def test_soft_delete_emits_soft_deleted_without_updated(task_list):
    task = services.create_task(task_list=task_list, title="Delete audit")
    TaskEvent.objects.all().delete()

    services.soft_delete_task(task)

    actions = list(TaskEvent.objects.values_list("action", flat=True))
    assert TaskEventAction.SOFT_DELETED in actions
    assert TaskEventAction.UPDATED not in actions


@pytest.mark.django_db
def test_pre_save_skips_snapshot_for_new_tasks(task_list):
    before = TaskEvent.objects.count()
    services.create_task(task_list=task_list, title="Brand new")
    assert TaskEvent.objects.count() == before + 1


@pytest.mark.django_db
def test_reorder_subtasks_service_records_parent_id(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    first = services.create_task(task_list=task_list, parent=parent, title="A")
    second = services.create_task(task_list=task_list, parent=parent, title="B")

    services.reorder_tasks(
        task_list=task_list,
        parent=parent,
        ordered_ids=[second.id, first.id],
    )

    event = TaskEvent.objects.get(action=TaskEventAction.REORDERED)
    assert event.changes["parent_id"] == parent.id


@pytest.mark.django_db
def test_apply_list_filters_manual_sort_is_default(task_list):
    second = services.create_task(task_list=task_list, title="Second")
    first = services.create_task(task_list=task_list, title="First")
    Task.objects.filter(id=first.id).update(order=0)
    Task.objects.filter(id=second.id).update(order=1)

    ordered = Task.objects.filter(
        task_list=task_list, parent__isnull=True
    ).apply_list_filters(sort="manual")
    assert list(ordered.values_list("title", flat=True)) == ["First", "Second"]


# --- Round-4 fixes (NB16-NB22) ---


@pytest.mark.django_db
def test_rename_list_handles_duplicate_name(session_client, inbox):
    TaskList.objects.create(session_key=inbox.session_key, name="Projects")

    response = session_client.post(
        reverse("tasks:rename_list", args=[inbox.id]),
        {"name": "Projects"},
        follow=True,
    )

    assert response.status_code == 200
    assert b"already have a list with that name" in response.content
    inbox.refresh_from_db()
    assert inbox.name == "Inbox"


@pytest.mark.django_db
def test_lists_view_returns_duplicate_name_error_real_db(client):
    client.get(reverse("tasks:home"))
    session_key = client.session.session_key
    TaskList.objects.create(session_key=session_key, name="Projects")

    response = client.post(reverse("tasks:lists"), {"name": "Projects"})

    assert response.status_code == 200
    assert b"already have a list with that name" in response.content


