import csv
import io
import json
from datetime import date, datetime
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.http import HttpResponse, QueryDict
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from . import services
from .forms import RecurrenceForm
from .middleware import VisitorTimezoneMiddleware
from .models import (
    Recurrence,
    RecurrenceFrequency,
    Task,
    TaskEvent,
    TaskEventAction,
    TaskList,
    TaskPriority,
    TaskStatus,
)


@pytest.fixture
def task_list():
    return TaskList.objects.create(session_key="test-session", name="Inbox")


@pytest.mark.django_db
def test_task_manager_hides_soft_deleted(task_list):
    task = services.create_task(task_list=task_list, title="Visible")
    services.soft_delete_task(task)

    assert Task.objects.filter(id=task.id).exists() is False
    assert Task.objects.all_with_deleted().filter(id=task.id).exists() is True
    assert Task.objects.deleted_only().get(id=task.id).title == "Visible"


@pytest.mark.django_db
def test_subtask_depth_is_capped_at_two_levels(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")

    with pytest.raises(ValidationError):
        services.create_task(task_list=task_list, parent=child, title="Grandchild")


@pytest.mark.django_db
def test_toggle_task_completes_and_reopens(task_list):
    task = services.create_task(task_list=task_list, title="Toggle me")

    services.toggle_task(task)
    task.refresh_from_db()
    assert task.status == TaskStatus.DONE
    assert task.completed_at is not None

    services.toggle_task(task)
    task.refresh_from_db()
    assert task.status == TaskStatus.OPEN
    assert task.completed_at is None


@pytest.mark.django_db
def test_recurring_task_spawns_next_occurrence(task_list):
    due_date = timezone.now() + timezone.timedelta(hours=2)
    task = services.create_task(
        task_list=task_list,
        title="Water plants",
        due_date=due_date,
        priority=TaskPriority.LOW,
    )
    services.set_recurrence(
        task,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
    )

    services.toggle_task(task)

    occurrence = Task.objects.get(spawned_from=task)
    assert occurrence.status == TaskStatus.OPEN
    assert occurrence.recurrence_id is None
    assert occurrence.due_date.date() == (due_date + timezone.timedelta(days=1)).date()
    assert TaskEvent.objects.filter(action=TaskEventAction.SPAWNED).exists()


@pytest.mark.django_db
def test_reorder_tasks_is_scoped_and_audited(task_list):
    first = services.create_task(task_list=task_list, title="First")
    second = services.create_task(task_list=task_list, title="Second")
    third = services.create_task(task_list=task_list, title="Third")

    services.reorder_tasks(
        task_list=task_list, ordered_ids=[third.id, first.id, second.id]
    )

    assert list(Task.objects.ordered().values_list("id", flat=True)) == [
        third.id,
        first.id,
        second.id,
    ]
    event = TaskEvent.objects.get(action=TaskEventAction.REORDERED)
    assert event.changes["order"] == [third.id, first.id, second.id]


@pytest.mark.django_db
def test_task_signals_create_audit_events(task_list):
    task = services.create_task(task_list=task_list, title="Audit me")
    services.toggle_task(task)
    services.soft_delete_task(task)

    actions = set(TaskEvent.objects.values_list("action", flat=True))
    assert TaskEventAction.CREATED in actions
    assert TaskEventAction.COMPLETED in actions
    assert TaskEventAction.SOFT_DELETED in actions
    assert TaskEventAction.UPDATED not in actions


@pytest.mark.django_db
def test_toggle_emits_completed_without_updated(task_list):
    task = services.create_task(task_list=task_list, title="Toggle audit")
    TaskEvent.objects.all().delete()

    services.toggle_task(task)

    actions = list(TaskEvent.objects.values_list("action", flat=True))
    assert actions == [TaskEventAction.COMPLETED]


@pytest.mark.django_db
def test_htmx_create_task_updates_sidebar_count_oob(client):
    response = client.get(reverse("tasks:home"))
    assert response.status_code == 302
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()

    response = client.post(
        reverse("tasks:create_task", args=[task_list.id]),
        {"title": "From HTMX", "priority": "medium"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"hx-swap-oob" in response.content
    assert f"list-count-{task_list.id}".encode() in response.content


@pytest.mark.django_db
def test_task_row_cancel_returns_row_partial(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Cancel me")

    response = client.get(reverse("tasks:task_row", args=[task.id]))

    assert response.status_code == 200
    assert b"Cancel me" in response.content
    assert b"data-edit-form" not in response.content


@pytest.mark.django_db
def test_visitor_timezone_middleware_activates_cookie_timezone():
    def get_response(request):
        request.active_tz = timezone.get_current_timezone_name()
        return HttpResponse("ok")

    request = RequestFactory().get("/")
    request.COOKIES = {"timezone": "America/New_York"}

    response = VisitorTimezoneMiddleware(get_response)(request)

    assert response.status_code == 200
    assert request.active_tz == "America/New_York"


@pytest.mark.django_db
def test_htmx_create_task_returns_partial(client):
    response = client.get(reverse("tasks:home"))
    assert response.status_code == 302
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()

    response = client.post(
        reverse("tasks:create_task", args=[task_list.id]),
        {"title": "From HTMX", "priority": "medium"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"task-group" in response.content
    assert b"From HTMX" in response.content


@pytest.mark.django_db
def test_htmx_list_detail_returns_task_list_partial(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    services.create_task(task_list=task_list, title="Partial")

    response = client.get(
        reverse("tasks:list_detail", args=[task_list.id]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"task-list-frame" in response.content
    assert b"Partial" in response.content


@pytest.mark.django_db
def test_export_csv_flattens_parent_and_child_rows(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    services.create_task(task_list=task_list, parent=parent, title="Child")

    result = services.export_tasks(task_list, fmt="csv")
    rows = list(csv.reader(io.StringIO(result.body)))

    assert rows[0] == [
        "id",
        "parent_id",
        "title",
        "status",
        "priority",
        "due_date",
        "deleted_at",
        "created_at",
    ]
    titles = {row[2] for row in rows[1:]}
    assert titles == {"Parent", "Child"}
    child_row = next(row for row in rows[1:] if row[2] == "Child")
    assert child_row[1] == str(parent.id)


@pytest.mark.django_db
def test_export_json_nests_subtasks(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    services.create_task(task_list=task_list, parent=parent, title="Child")

    result = services.export_tasks(task_list, fmt="json")
    payload = json.loads(result.body)

    assert len(payload) == 1
    assert payload[0]["title"] == "Parent"
    assert payload[0]["subtasks"][0]["title"] == "Child"
    assert result.filename == f"{slugify(task_list.name, allow_unicode=True)}.json"
    assert result.content_type == "application/json"


@pytest.mark.django_db
def test_recurrence_str_uses_plural_units():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.DAILY,
        interval=2,
    )
    assert str(recurrence) == "Every 2 days"


@pytest.mark.django_db
def test_htmx_create_first_task_removes_empty_state_oob(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    Task.objects.filter(task_list=task_list).delete()

    response = client.post(
        reverse("tasks:create_task", args=[task_list.id]),
        {"title": "First task", "priority": "medium"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"hx-swap-oob" in response.content
    assert b"task-list-empty-state" in response.content
    assert b"delete" in response.content


@pytest.mark.django_db
def test_export_filename_slugifies_unsafe_list_names(task_list):
    task_list.name = 'My "Quotes"\nList'
    task_list.save()

    result = services.export_tasks(task_list, fmt="csv")

    assert result.filename == f"{slugify(task_list.name, allow_unicode=True)}.csv"
    assert '"' not in result.filename
    assert "\n" not in result.filename


@pytest.mark.django_db
def test_clear_recurrence_emits_updated_audit_event(task_list):
    task = services.create_task(task_list=task_list, title="Recurring")
    services.set_recurrence(
        task,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
    )
    TaskEvent.objects.all().delete()

    services.clear_recurrence(task)

    event = TaskEvent.objects.get(action=TaskEventAction.UPDATED)
    assert "recurrence_id" in event.changes


@pytest.mark.django_db
def test_list_detail_filters_today_and_open_status(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()

    services.create_task(
        task_list=task_list,
        title="Today open",
        due_date=timezone.now(),
    )
    today_done = services.create_task(
        task_list=task_list,
        title="Today done",
        due_date=timezone.now(),
    )
    services.toggle_task(today_done)
    services.create_task(
        task_list=task_list,
        title="Tomorrow",
        due_date=timezone.now() + timezone.timedelta(days=1),
    )

    response = client.get(
        reverse("tasks:list_detail", args=[task_list.id]),
        {"view": "today", "status": TaskStatus.OPEN},
    )

    content = response.content
    assert b"Today open" in content
    assert b"Today done" not in content
    assert b"Tomorrow" not in content


@pytest.mark.django_db
def test_restore_parent_restores_soft_deleted_children(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")

    services.soft_delete_task(parent)

    assert Task.objects.filter(id=child.id).exists() is False
    parent = Task.objects.all_with_deleted().get(id=parent.id)
    services.restore_task(parent)

    assert Task.objects.filter(id=parent.id).exists() is True
    assert Task.objects.filter(id=child.id).exists() is True


@pytest.mark.django_db
def test_restore_parent_skips_independently_deleted_child(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")

    services.soft_delete_task(child)
    earlier = timezone.now() - timezone.timedelta(days=1)
    Task.objects.all_with_deleted().filter(id=child.id).update(deleted_at=earlier)

    services.soft_delete_task(parent)
    parent = Task.objects.all_with_deleted().get(id=parent.id)
    services.restore_task(parent)

    assert Task.objects.filter(id=parent.id).exists() is True
    child = Task.objects.all_with_deleted().get(id=child.id)
    assert child.is_deleted is True


@pytest.mark.django_db
@override_settings(TIME_ZONE="America/New_York")
def test_daily_recurrence_preserves_wall_clock_across_dst():
    tz = ZoneInfo("America/New_York")
    with timezone.override(tz):
        base_due = timezone.make_aware(datetime(2024, 3, 9, 9, 0))
        recurrence = Recurrence(
            frequency=RecurrenceFrequency.DAILY,
            interval=1,
        )

        next_due = services.compute_next_due_date(base_due, recurrence)
        local_next = timezone.localtime(next_due)

        assert local_next.date() == date(2024, 3, 10)
        assert local_next.hour == 9
        assert local_next.minute == 0


@pytest.mark.django_db
def test_events_pagination_preserves_filters(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    services.create_task(task_list=task_list, title="Event task")
    services.toggle_task(Task.objects.get(title="Event task"))

    for _ in range(30):
        task = services.create_task(task_list=task_list, title=f"Bulk {_}")
        services.toggle_task(task)

    response = client.get(
        reverse("tasks:events"),
        {"action": TaskEventAction.COMPLETED, "page": 2},
    )

    assert response.status_code == 200
    assert b"action=completed" in response.content
    assert b"page=1" in response.content or b"Previous" in response.content


@pytest.mark.django_db
def test_lists_view_shows_duplicate_name_error(client):
    client.get(reverse("tasks:home"))
    TaskList.objects.filter(name="Inbox").order_by("-id").first()

    response = client.post(reverse("tasks:lists"), {"name": "Inbox"})

    assert response.status_code == 200
    assert b"already have a list with that name" in response.content


@pytest.mark.django_db
def test_sidebar_create_keeps_current_list_highlight(client):
    client.get(reverse("tasks:home"))
    inbox = TaskList.objects.filter(name="Inbox").order_by("-id").first()

    response = client.post(
        reverse("tasks:lists"),
        {"name": "Projects", "current_list_id": inbox.id},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Projects" in response.content
    inbox_idx = response.content.index(b"Inbox")
    projects_idx = response.content.index(b"Projects")
    inbox_snippet = response.content[max(0, inbox_idx - 250) : inbox_idx]
    projects_snippet = response.content[max(0, projects_idx - 250) : projects_idx]
    assert b"bg-emerald-50" in inbox_snippet
    assert b"bg-emerald-50" not in projects_snippet


@pytest.mark.django_db
def test_monthly_recurrence_clamps_day_31_to_last_day_of_month():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.MONTHLY,
        interval=1,
        day_of_month=31,
    )
    base_due = timezone.make_aware(datetime(2024, 1, 31, 9, 0))

    next_due = services.compute_next_due_date(base_due, recurrence)

    assert next_due.month == 2
    assert next_due.day == 29


@pytest.mark.django_db
def test_recurrence_end_date_prevents_next_spawn(task_list):
    due_date = timezone.now() + timezone.timedelta(hours=2)
    task = services.create_task(
        task_list=task_list,
        title="Ends soon",
        due_date=due_date,
    )
    services.set_recurrence(
        task,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
        end_date=timezone.localdate(),
    )

    services.toggle_task(task)

    assert Task.objects.filter(spawned_from=task).exists() is False


@pytest.mark.django_db
def test_active_task_count_excludes_completed_tasks(task_list):
    services.create_task(task_list=task_list, title="Still open")
    done = services.create_task(task_list=task_list, title="Done")
    services.toggle_task(done)

    annotated = TaskList.objects.with_active_task_counts().get(id=task_list.id)

    assert annotated.active_task_count == 1


@pytest.mark.django_db
def test_reorder_view_accepts_comma_separated_order(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    first = services.create_task(task_list=task_list, title="First")
    second = services.create_task(task_list=task_list, title="Second")
    third = services.create_task(task_list=task_list, title="Third")

    response = client.post(
        reverse("tasks:reorder_tasks", args=[task_list.id]),
        {"order": f"{third.id},{first.id},{second.id}"},
    )

    assert response.status_code == 204
    assert list(Task.objects.ordered().values_list("id", flat=True)) == [
        third.id,
        first.id,
        second.id,
    ]


@pytest.mark.django_db
def test_recurrence_form_prefills_weekday_checkboxes(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Weekly standup")
    services.set_recurrence(
        task,
        frequency=RecurrenceFrequency.WEEKLY,
        interval=1,
        weekday_mask=18,
    )
    task.refresh_from_db()

    response = client.get(reverse("tasks:list_detail", args=[task_list.id]))

    assert response.status_code == 200
    assert b'name="weekdays" value="2" checked' in response.content
    assert b'name="weekdays" value="16" checked' in response.content
    assert b'name="weekdays" value="1" checked' not in response.content


@pytest.mark.django_db
def test_reorder_invalid_ids_returns_400(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    other_list = TaskList.objects.create(
        session_key=task_list.session_key,
        name="Other",
    )
    mine = services.create_task(task_list=task_list, title="Mine")
    other = services.create_task(task_list=other_list, title="Other")

    payload = QueryDict(mutable=True)
    payload.setlist("order", [str(mine.id), str(other.id)])

    response = client.post(
        reverse("tasks:reorder_tasks", args=[task_list.id]),
        payload,
    )

    assert response.status_code == 400
    assert b"outside reorder scope" in response.content


@pytest.mark.django_db
def test_htmx_delete_returns_empty_body_and_soft_deletes(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Delete me")

    response = client.post(
        reverse("tasks:delete_task", args=[task.id]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"task-group" not in response.content
    assert b"Delete me" not in response.content
    assert b"hx-swap-oob" in response.content
    assert Task.objects.filter(id=task.id).exists() is False
    assert Task.objects.all_with_deleted().get(id=task.id).is_deleted


@pytest.mark.django_db
def test_rename_list_shows_success_message(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()

    response = client.post(
        reverse("tasks:rename_list", args=[task_list.id]),
        {"name": "Personal"},
        follow=True,
    )

    assert response.status_code == 200
    assert b"List renamed." in response.content
    task_list.refresh_from_db()
    assert task_list.name == "Personal"


@pytest.mark.django_db
def test_delete_list_redirects_to_remaining_list(client):
    client.get(reverse("tasks:home"))
    inbox = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    work = TaskList.objects.create(session_key=inbox.session_key, name="Work")

    response = client.post(reverse("tasks:delete_list", args=[work.id]), follow=True)

    assert response.status_code == 200
    assert TaskList.objects.filter(id=work.id).exists() is False
    assert b"Inbox" in response.content


@pytest.mark.django_db
def test_delete_last_list_redirects_home(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    list_id = task_list.id

    response = client.post(reverse("tasks:delete_list", args=[list_id]))

    assert response.status_code == 302
    assert response.url == reverse("tasks:home")
    assert TaskList.objects.filter(id=list_id).exists() is False


@pytest.mark.django_db
def test_edit_task_returns_edit_form(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Edit me")

    response = client.get(reverse("tasks:edit_task", args=[task.id]))

    assert response.status_code == 200
    assert b"data-edit-form" in response.content
    assert b"Edit me" in response.content


@pytest.mark.django_db
def test_update_task_view_returns_updated_row(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Old title")

    response = client.post(
        reverse("tasks:update_task", args=[task.id]),
        {"title": "New title", "notes": "", "priority": "medium"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"New title" in response.content
    assert "HX-Trigger" in response
    task.refresh_from_db()
    assert task.title == "New title"


@pytest.mark.django_db
def test_update_task_invalid_title_returns_400(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Keep me")

    response = client.post(
        reverse("tasks:update_task", args=[task.id]),
        {"title": "   ", "notes": "", "priority": "medium"},
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_create_task_invalid_title_returns_400(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()

    response = client.post(
        reverse("tasks:create_task", args=[task_list.id]),
        {"title": "", "priority": "medium"},
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_create_subtask_view_returns_subtask_row(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    parent = services.create_task(task_list=task_list, title="Parent")

    response = client.post(
        reverse("tasks:create_subtask", args=[parent.id]),
        {"title": "Child task", "priority": "medium"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Child task" in response.content
    assert b"subtask-row" in response.content
    assert parent.children.filter(title="Child task").exists()


@pytest.mark.django_db
def test_create_subtask_on_subtask_returns_404(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")

    response = client.post(
        reverse("tasks:create_subtask", args=[child.id]),
        {"title": "Grandchild", "priority": "medium"},
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_set_recurrence_view_saves_daily_rule(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Daily")

    response = client.post(
        reverse("tasks:set_recurrence", args=[task.id]),
        {"frequency": "daily", "interval": "2"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.recurrence.frequency == RecurrenceFrequency.DAILY
    assert task.recurrence.interval == 2
    assert "HX-Trigger" in response


@pytest.mark.django_db
def test_set_recurrence_invalid_weekly_returns_422(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Weekly")

    response = client.post(
        reverse("tasks:set_recurrence", args=[task.id]),
        {"frequency": "weekly", "interval": "1"},
    )

    assert response.status_code == 422
    task.refresh_from_db()
    assert task.recurrence_id is None


@pytest.mark.django_db
def test_set_recurrence_on_subtask_returns_400(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")

    response = client.post(
        reverse("tasks:set_recurrence", args=[child.id]),
        {"frequency": "daily", "interval": "1"},
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_clear_recurrence_view_removes_rule(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Recurring")
    services.set_recurrence(
        task,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
    )

    response = client.post(
        reverse("tasks:clear_recurrence", args=[task.id]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.recurrence_id is None
    assert "HX-Trigger" in response


@pytest.mark.django_db
def test_toggle_task_view_returns_task_group(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Toggle parent")

    response = client.post(
        reverse("tasks:toggle_task", args=[task.id]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"task-group" in response.content
    task.refresh_from_db()
    assert task.status == TaskStatus.DONE


@pytest.mark.django_db
def test_toggle_subtask_returns_subtask_row(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")

    response = client.post(
        reverse("tasks:toggle_task", args=[child.id]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"subtask-row" in response.content
    assert b"task-group" not in response.content


@pytest.mark.django_db
def test_toggle_missing_task_returns_404(client):
    client.get(reverse("tasks:home"))

    response = client.post(reverse("tasks:toggle_task", args=[99999]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_restore_task_view_returns_task_group(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    task = services.create_task(task_list=task_list, title="Restore me")
    services.soft_delete_task(task)

    response = client.post(
        reverse("tasks:restore_task", args=[task.id]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"task-group" in response.content
    assert Task.objects.filter(id=task.id).exists()


@pytest.mark.django_db
def test_reorder_subtasks_view(client):
    client.get(reverse("tasks:home"))
    task_list = TaskList.objects.filter(name="Inbox").order_by("-id").first()
    parent = services.create_task(task_list=task_list, title="Parent")
    first = services.create_task(task_list=task_list, parent=parent, title="A")
    second = services.create_task(task_list=task_list, parent=parent, title="B")

    response = client.post(
        reverse("tasks:reorder_subtasks", args=[parent.id]),
        {"order": f"{second.id},{first.id}"},
    )

    assert response.status_code == 204
    assert list(parent.children.ordered().values_list("id", flat=True)) == [
        second.id,
        first.id,
    ]


@pytest.mark.django_db
def test_lists_view_shows_list_created_message(client):
    client.get(reverse("tasks:home"))

    response = client.post(
        reverse("tasks:lists"),
        {"name": "Projects"},
        follow=True,
    )

    assert response.status_code == 200
    assert b"List created." in response.content


@pytest.mark.django_db
def test_seed_creates_demo_lists_and_tasks():
    out = StringIO()
    call_command("seed", stdout=out)

    assert TaskList.objects.filter(session_key="seed-session").count() == 2
    assert Task.objects.filter(task_list__session_key="seed-session").exists()
    assert "Seeded demo data" in out.getvalue()


@pytest.mark.django_db
def test_seed_skips_when_data_exists():
    call_command("seed")
    count_before = Task.objects.filter(task_list__session_key="seed-session").count()
    out = StringIO()
    call_command("seed", stdout=out)

    assert "already exists" in out.getvalue()
    assert (
        Task.objects.filter(task_list__session_key="seed-session").count()
        == count_before
    )


@pytest.mark.django_db
def test_seed_force_replaces_data():
    call_command("seed")
    call_command("seed", "--force", stdout=StringIO())

    lists = TaskList.objects.filter(session_key="seed-session")
    assert lists.count() == 2
    assert lists.filter(name="Inbox").exists()
    assert lists.filter(name="Work").exists()
    assert Task.objects.filter(task_list__session_key="seed-session").exists()


@pytest.fixture
def session_client(client):
    client.get(reverse("tasks:home"))
    return client


@pytest.fixture
def inbox(session_client):
    return TaskList.objects.filter(name="Inbox").order_by("-id").first()


@pytest.mark.django_db
def test_lists_view_get_renders_lists_page(session_client):
    response = session_client.get(reverse("tasks:lists"))

    assert response.status_code == 200
    assert b"Lists" in response.content


@pytest.mark.django_db
def test_htmx_invalid_list_create_returns_400(session_client):
    response = session_client.post(
        reverse("tasks:lists"),
        {"name": ""},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_create_task_non_htmx_redirects_to_list_detail(session_client, inbox):
    response = session_client.post(
        reverse("tasks:create_task", args=[inbox.id]),
        {"title": "Plain create", "priority": "medium"},
    )

    assert response.status_code == 302
    assert response.url == reverse("tasks:list_detail", args=[inbox.id])
    assert Task.objects.filter(title="Plain create").exists()


@pytest.mark.django_db
def test_delete_task_non_htmx_redirects_to_list_detail(session_client, inbox):
    task = services.create_task(task_list=inbox, title="Delete redirect")

    response = session_client.post(reverse("tasks:delete_task", args=[task.id]))

    assert response.status_code == 302
    assert response.url == reverse("tasks:list_detail", args=[inbox.id])


@pytest.mark.django_db
def test_create_subtask_invalid_title_returns_400(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")

    response = session_client.post(
        reverse("tasks:create_subtask", args=[parent.id]),
        {"title": "", "priority": "medium"},
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_create_subtask_non_htmx_redirects(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")

    response = session_client.post(
        reverse("tasks:create_subtask", args=[parent.id]),
        {"title": "Child", "priority": "medium"},
    )

    assert response.status_code == 302
    assert response.url == reverse("tasks:list_detail", args=[inbox.id])


@pytest.mark.django_db
def test_task_row_subtask_returns_subtask_partial(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")
    child = services.create_task(task_list=inbox, parent=parent, title="Child")

    response = session_client.get(reverse("tasks:task_row", args=[child.id]))

    assert response.status_code == 200
    assert b"subtask-row" in response.content
    assert b"Child" in response.content


@pytest.mark.django_db
def test_list_detail_filters_upcoming_and_priority(session_client, inbox):
    services.create_task(
        task_list=inbox,
        title="Soon",
        due_date=timezone.now() + timezone.timedelta(days=3),
        priority=TaskPriority.HIGH,
    )
    services.create_task(
        task_list=inbox,
        title="Later",
        due_date=timezone.now() + timezone.timedelta(days=10),
        priority=TaskPriority.LOW,
    )

    response = session_client.get(
        reverse("tasks:list_detail", args=[inbox.id]),
        {"view": "upcoming", "priority": TaskPriority.HIGH},
    )

    assert response.status_code == 200
    assert b"Soon" in response.content
    assert b"Later" not in response.content


@pytest.mark.django_db
def test_list_detail_filters_overdue_and_search(session_client, inbox):
    services.create_task(
        task_list=inbox,
        title="Overdue alpha",
        due_date=timezone.now() - timezone.timedelta(days=1),
    )
    services.create_task(
        task_list=inbox,
        title="Overdue beta",
        due_date=timezone.now() - timezone.timedelta(days=2),
    )

    response = session_client.get(
        reverse("tasks:list_detail", args=[inbox.id]),
        {"view": "overdue", "q": "alpha"},
    )

    assert response.status_code == 200
    assert b"Overdue alpha" in response.content
    assert b"Overdue beta" not in response.content


@pytest.mark.django_db
def test_list_detail_sorts_by_due_date_and_created_at(session_client, inbox):
    services.create_task(
        task_list=inbox,
        title="Later due",
        due_date=timezone.now() + timezone.timedelta(days=5),
    )
    services.create_task(
        task_list=inbox,
        title="Earlier due",
        due_date=timezone.now() + timezone.timedelta(days=1),
    )

    due_response = session_client.get(
        reverse("tasks:list_detail", args=[inbox.id]),
        {"sort": "due_date", "view": "all"},
        HTTP_HX_REQUEST="true",
    )
    due_content = due_response.content.decode()
    assert due_content.index("Earlier due") < due_content.index("Later due")

    newer = services.create_task(task_list=inbox, title="Newest")
    created_response = session_client.get(
        reverse("tasks:list_detail", args=[inbox.id]),
        {"sort": "created_at", "view": "all"},
        HTTP_HX_REQUEST="true",
    )
    created_content = created_response.content.decode()
    assert created_content.index("Newest") < created_content.index("Earlier due")
    assert Task.objects.filter(id=newer.id).exists()


@pytest.mark.django_db
def test_list_detail_sorts_by_priority(session_client, inbox):
    services.create_task(task_list=inbox, title="Low", priority=TaskPriority.LOW)
    services.create_task(task_list=inbox, title="High", priority=TaskPriority.HIGH)

    response = session_client.get(
        reverse("tasks:list_detail", args=[inbox.id]),
        {"sort": "priority", "view": "all"},
        HTTP_HX_REQUEST="true",
    )
    content = response.content.decode()

    assert content.index("High") < content.index("Low")


@pytest.mark.django_db
def test_list_detail_show_deleted_includes_soft_deleted_tasks(session_client, inbox):
    task = services.create_task(task_list=inbox, title="Hidden deleted")
    services.soft_delete_task(task)

    response = session_client.get(
        reverse("tasks:list_detail", args=[inbox.id]),
        {"show_deleted": "1"},
    )

    assert response.status_code == 200
    assert b"Hidden deleted" in response.content


@pytest.mark.django_db
def test_htmx_delete_last_task_inserts_empty_state_oob(session_client, inbox):
    task = services.create_task(task_list=inbox, title="Only task")

    response = session_client.post(
        reverse("tasks:delete_task", args=[task.id]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"hx-swap-oob" in response.content
    assert b"task-list-empty-state" in response.content
    assert b"beforeend:#task-list" in response.content


@pytest.mark.django_db
def test_reorder_subtasks_invalid_ids_returns_400(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")
    child = services.create_task(task_list=inbox, parent=parent, title="Child")
    stranger = services.create_task(task_list=inbox, title="Stranger")

    response = session_client.post(
        reverse("tasks:reorder_subtasks", args=[parent.id]),
        {"order": f"{child.id},{stranger.id}"},
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_reorder_view_accepts_space_separated_order(session_client, inbox):
    first = services.create_task(task_list=inbox, title="First")
    second = services.create_task(task_list=inbox, title="Second")

    response = session_client.post(
        reverse("tasks:reorder_tasks", args=[inbox.id]),
        {"order": f"{second.id} {first.id}"},
    )

    assert response.status_code == 204
    assert list(Task.objects.ordered().values_list("id", flat=True)) == [
        second.id,
        first.id,
    ]


@pytest.mark.django_db
def test_export_csv_view_downloads_flat_rows(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")
    services.create_task(task_list=inbox, parent=parent, title="Child")

    response = session_client.get(reverse("tasks:export_csv", args=[inbox.id]))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert {row[2] for row in rows[1:]} == {"Parent", "Child"}


@pytest.mark.django_db
def test_export_json_view_downloads_nested_payload(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")
    services.create_task(task_list=inbox, parent=parent, title="Child")

    response = session_client.get(reverse("tasks:export_json", args=[inbox.id]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    payload = json.loads(response.content)
    assert payload[0]["subtasks"][0]["title"] == "Child"


@pytest.mark.django_db
def test_events_view_filters_by_list(session_client, inbox):
    other = TaskList.objects.create(session_key=inbox.session_key, name="Other")
    services.create_task(task_list=inbox, title="In inbox")
    other_task = services.create_task(task_list=other, title="In other")
    services.toggle_task(other_task)

    response = session_client.get(
        reverse("tasks:events"),
        {"list": other.id},
    )

    assert response.status_code == 200
    assert b"In other" in response.content
    assert b"In inbox" not in response.content


@pytest.mark.django_db
def test_toggle_wrong_session_returns_404(client):
    owner = TaskList.objects.create(session_key="owner-session", name="Private")
    task = services.create_task(task_list=owner, title="Private task")

    client.get(reverse("tasks:home"))
    response = client.post(reverse("tasks:toggle_task", args=[task.id]))

    assert response.status_code == 404
    task.refresh_from_db()
    assert task.status == TaskStatus.OPEN


@pytest.mark.django_db
def test_recurrence_clean_rejects_invalid_interval():
    recurrence = Recurrence(frequency=RecurrenceFrequency.DAILY, interval=0)
    with pytest.raises(ValidationError):
        recurrence.full_clean()


@pytest.mark.django_db
def test_recurrence_clean_rejects_invalid_weekday_mask():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=1,
        weekday_mask=200,
    )
    with pytest.raises(ValidationError):
        recurrence.full_clean()


@pytest.mark.django_db
def test_recurrence_clean_allows_weekly_without_weekday_mask():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=2,
        weekday_mask=None,
    )
    recurrence.full_clean()


@pytest.mark.django_db
def test_task_clean_rejects_recurrence_on_subtask(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    child = Task(
        task_list=task_list,
        parent=parent,
        title="Child",
        recurrence=Recurrence.objects.create(
            frequency=RecurrenceFrequency.DAILY,
            interval=1,
        ),
    )
    with pytest.raises(ValidationError):
        child.full_clean()


@pytest.mark.django_db
def test_task_clean_rejects_parent_from_other_list(task_list):
    other = TaskList.objects.create(session_key=task_list.session_key, name="Other")
    parent = services.create_task(task_list=other, title="Elsewhere")
    child = Task(task_list=task_list, parent=parent, title="Mismatch")
    with pytest.raises(ValidationError):
        child.full_clean()


@pytest.mark.django_db
def test_task_clean_rejects_promoting_parent_with_children(task_list):
    top = services.create_task(task_list=task_list, title="Top")
    services.create_task(task_list=task_list, parent=top, title="Child")
    anchor = services.create_task(task_list=task_list, title="Anchor")
    top.parent = anchor
    with pytest.raises(ValidationError):
        top.full_clean()


@pytest.mark.django_db
def test_task_queryset_manager_helpers(task_list):
    parent = services.create_task(task_list=task_list, title="Parent")
    child = services.create_task(task_list=task_list, parent=parent, title="Child")
    services.set_recurrence(
        parent,
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
    )
    services.toggle_task(child)
    services.soft_delete_task(
        services.create_task(task_list=task_list, title="Deleted")
    )

    assert Task.objects.top_level().filter(title="Parent").exists()
    assert Task.objects.subtasks_of(parent).count() == 1
    assert Task.objects.templates().filter(id=parent.id).exists()
    assert Task.objects.deleted_only().filter(title="Deleted").exists()
    assert not Task.objects.filter(title="Deleted").exists()


@pytest.mark.django_db
def test_apply_list_filters_on_queryset(task_list):
    services.create_task(
        task_list=task_list,
        title="High today",
        due_date=timezone.now(),
        priority=TaskPriority.HIGH,
    )
    services.create_task(
        task_list=task_list,
        title="Low later",
        due_date=timezone.now() + timezone.timedelta(days=4),
        priority=TaskPriority.LOW,
    )

    filtered = Task.objects.filter(
        task_list=task_list, parent__isnull=True
    ).apply_list_filters(
        view="today",
        priority=TaskPriority.HIGH,
    )

    assert list(filtered.values_list("title", flat=True)) == ["High today"]


@pytest.mark.django_db
def test_recurrence_form_requires_weekdays():
    form = RecurrenceForm({"frequency": "weekly", "interval": "1"})
    assert form.is_valid() is False
    assert "Choose at least one weekday." in str(form.errors)


@pytest.mark.django_db
def test_recurrence_form_requires_day_of_month():
    form = RecurrenceForm({"frequency": "monthly", "interval": "1"})
    assert form.is_valid() is False
    assert "Choose a day of the month." in str(form.errors)


@pytest.mark.django_db
def test_visitor_timezone_middleware_ignores_invalid_cookie():
    def get_response(request):
        request.active_tz = timezone.get_current_timezone_name()
        return HttpResponse("ok")

    request = RequestFactory().get("/")
    request.COOKIES = {"timezone": "Not/A_Real_Zone"}

    response = VisitorTimezoneMiddleware(get_response)(request)

    assert response.status_code == 200
    assert request.active_tz != "Not/A_Real_Zone"


@pytest.mark.django_db
def test_reorder_tasks_noop_on_empty_id_list(task_list):
    services.create_task(task_list=task_list, title="Only")
    services.reorder_tasks(task_list=task_list, ordered_ids=[])
    assert TaskEvent.objects.filter(action=TaskEventAction.REORDERED).count() == 0


@pytest.mark.django_db
def test_clear_recurrence_noop_when_missing(task_list):
    task = services.create_task(task_list=task_list, title="Plain")
    services.clear_recurrence(task)
    assert task.recurrence_id is None


@pytest.mark.django_db
def test_spawn_skips_duplicate_open_occurrence(task_list):
    due_date = timezone.now() + timezone.timedelta(hours=2)
    task = services.create_task(task_list=task_list, title="Daily", due_date=due_date)
    services.set_recurrence(task, frequency=RecurrenceFrequency.DAILY, interval=1)
    services.toggle_task(task)
    assert Task.objects.filter(spawned_from=task).count() == 1
    services.toggle_task(task)
    services.toggle_task(task)
    assert Task.objects.filter(spawned_from=task, status=TaskStatus.OPEN).count() == 1


@pytest.mark.django_db
def test_weekly_recurrence_uses_weekday_mask():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=1,
        weekday_mask=2,
    )
    base_due = timezone.make_aware(datetime(2024, 6, 3, 9, 0))
    next_due = services.compute_next_due_date(base_due, recurrence)
    assert next_due.weekday() == 1


@pytest.mark.django_db
def test_spawn_returns_none_for_deleted_template(task_list):
    task = services.create_task(task_list=task_list, title="Gone")
    services.set_recurrence(task, frequency=RecurrenceFrequency.DAILY, interval=1)
    services.soft_delete_task(task)
    task = Task.objects.all_with_deleted().get(id=task.id)
    assert services.spawn_next_occurrence(task) is None


@pytest.mark.django_db
def test_reorder_view_accepts_scalar_order_string(session_client, inbox):
    first = services.create_task(task_list=inbox, title="First")
    second = services.create_task(task_list=inbox, title="Second")

    response = session_client.post(
        reverse("tasks:reorder_tasks", args=[inbox.id]),
        {"order": f"{second.id} {first.id}"},
    )

    assert response.status_code == 204
    assert list(Task.objects.ordered().values_list("id", flat=True)) == [
        second.id,
        first.id,
    ]


@pytest.mark.django_db
def test_non_htmx_create_task_has_no_oob(session_client, inbox):
    response = session_client.post(
        reverse("tasks:create_task", args=[inbox.id]),
        {"title": "No OOB", "priority": "medium"},
    )

    assert response.status_code == 302
    follow = session_client.get(response.url)
    assert b"hx-swap-oob" not in follow.content


@pytest.mark.django_db
def test_toggle_subtask_updates_parent_count_oob(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")
    child = services.create_task(task_list=inbox, parent=parent, title="Child")

    response = session_client.post(
        reverse("tasks:toggle_task", args=[child.id]),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"hx-swap-oob" in response.content
    assert f"subtask-count-{parent.id}".encode() in response.content
    assert b"1/1" in response.content


@pytest.mark.django_db
def test_create_subtask_updates_parent_count_oob(session_client, inbox):
    parent = services.create_task(task_list=inbox, title="Parent")

    response = session_client.post(
        reverse("tasks:create_subtask", args=[parent.id]),
        {"title": "Child", "priority": "medium"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"0/1" in response.content
    assert f"subtask-count-{parent.id}".encode() in response.content


@pytest.mark.django_db
def test_reopen_emits_reopened_without_updated(task_list):
    task = services.create_task(task_list=task_list, title="Reopen audit")
    services.toggle_task(task)
    TaskEvent.objects.all().delete()

    services.toggle_task(task)

    actions = list(TaskEvent.objects.values_list("action", flat=True))
    assert actions == [TaskEventAction.REOPENED]
    assert TaskEventAction.UPDATED not in actions


@pytest.mark.django_db
def test_restore_emits_restored_without_updated(task_list):
    task = services.create_task(task_list=task_list, title="Restore audit")
    services.soft_delete_task(task)
    TaskEvent.objects.all().delete()
    task = Task.objects.all_with_deleted().get(id=task.id)

    services.restore_task(task)

    actions = list(TaskEvent.objects.values_list("action", flat=True))
    assert actions == [TaskEventAction.RESTORED]
    assert TaskEventAction.UPDATED not in actions


@pytest.mark.django_db
def test_title_change_emits_updated_event(task_list):
    task = services.create_task(task_list=task_list, title="Before")
    TaskEvent.objects.all().delete()

    services.update_task(
        task, title="After", notes="", due_date=None, priority=TaskPriority.MEDIUM
    )

    event = TaskEvent.objects.get(action=TaskEventAction.UPDATED)
    assert event.changes["title"] == ["Before", "After"]


@pytest.mark.django_db
def test_save_without_changes_emits_no_updated_event(task_list):
    task = services.create_task(task_list=task_list, title="Stable")
    TaskEvent.objects.all().delete()

    task.save()

    assert not TaskEvent.objects.filter(action=TaskEventAction.UPDATED).exists()


@pytest.mark.django_db
def test_capture_old_task_values_when_previous_row_missing(task_list):
    task = services.create_task(task_list=task_list, title="Missing old")
    with patch.object(Task.objects, "all_with_deleted") as mock_manager:
        mock_manager.return_value.filter.return_value.values.return_value.first.return_value = (
            None
        )
        task.title = "Updated title"
        task.save(update_fields=["title", "updated_at"])

    task.refresh_from_db()
    assert task.title == "Updated title"
    assert not TaskEvent.objects.filter(
        task=task, action=TaskEventAction.UPDATED
    ).exists()


@pytest.mark.django_db
def test_emit_task_events_skips_when_old_values_missing(task_list):
    from tasks.signals import emit_task_events

    task = services.create_task(task_list=task_list, title="Skip")
    TaskEvent.objects.all().delete()

    emit_task_events(Task, task, created=False)

    assert TaskEvent.objects.count() == 0


@pytest.mark.django_db
def test_weekly_recurrence_without_mask_uses_interval_weeks():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=2,
        weekday_mask=None,
    )
    local_base = timezone.localtime(timezone.make_aware(datetime(2024, 6, 10, 9, 0)))

    next_local = services._next_weekly(local_base, recurrence)

    assert (next_local.date() - local_base.date()).days == 14


@pytest.mark.django_db
def test_weekly_recurrence_fallback_after_search_exhausted(monkeypatch):
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=2,
        weekday_mask=1,
    )
    local_base = timezone.localtime(timezone.make_aware(datetime(2024, 6, 10, 9, 0)))

    monkeypatch.setattr(services, "_add_local_days", lambda base, days: base)
    next_local = services._next_weekly(local_base, recurrence)

    assert next_local == local_base


@pytest.mark.django_db
def test_recurrence_form_weekday_mask_sums_selected_days():
    form = RecurrenceForm(
        {"frequency": "weekly", "interval": "1", "weekdays": ["1", "4"]},
    )
    assert form.is_valid()
    assert form.weekday_mask == 5


@pytest.mark.django_db
def test_recurrence_form_weekday_mask_empty_returns_none():
    form = RecurrenceForm({"frequency": "daily", "interval": "1"})
    assert form.is_valid()
    assert form.weekday_mask is None
