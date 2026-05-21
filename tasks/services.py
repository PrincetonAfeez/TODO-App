from __future__ import annotations

import calendar
import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Max, Prefetch
from django.utils import timezone
from django.utils.text import slugify

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


class RestoreError(ValueError):
    """Raised when a task cannot be restored."""


@dataclass(frozen=True)
class ExportResult:
    filename: str
    content_type: str
    body: str


def ensure_default_list(session_key: str) -> TaskList:
    task_list, _ = TaskList.objects.get_or_create(
        session_key=session_key,
        name="Inbox",
    )
    return task_list


def _lock_order_scope(task_list: TaskList, parent: Task | None = None) -> None:
    """Serialize concurrent order assignment for a list or subtask parent.

    Uses ``select_for_update()``; on SQLite this is a no-op (Django logs a
    warning), so dev/CI on SQLite will not surface reorder races. PostgreSQL
    (production) enforces the lock.
    """
    if parent is not None:
        Task.objects.select_for_update().get(pk=parent.pk)
    else:
        TaskList.objects.select_for_update().get(pk=task_list.pk)


def next_order(task_list: TaskList, parent: Task | None = None) -> int:
    _lock_order_scope(task_list, parent)
    max_order = (
        Task.objects.all_with_deleted()
        .filter(task_list=task_list, parent=parent)
        .aggregate(Max("order"))["order__max"]
    )
    return 0 if max_order is None else max_order + 1


@transaction.atomic
def create_task(
    *,
    task_list: TaskList,
    title: str,
    notes: str = "",
    due_date=None,
    priority: str = TaskPriority.MEDIUM,
    parent: Task | None = None,
) -> Task:
    task = Task.objects.create(
        task_list=task_list,
        parent=parent,
        title=title.strip(),
        notes=notes.strip(),
        due_date=due_date,
        priority=priority,
        order=next_order(task_list, parent),
    )
    return task


@transaction.atomic
def update_task(
    task: Task,
    *,
    title: str,
    notes: str,
    due_date,
    priority: str,
) -> Task:
    task.title = title.strip()
    task.notes = notes.strip()
    task.due_date = due_date
    task.priority = priority
    task.save(update_fields=["title", "notes", "due_date", "priority", "updated_at"])
    return task


@transaction.atomic
def toggle_task(task: Task) -> Task:
    if task.status == TaskStatus.DONE:
        task.status = TaskStatus.OPEN
        task.completed_at = None
        task.save(update_fields=["status", "completed_at", "updated_at"])
        return task

    task.status = TaskStatus.DONE
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "completed_at", "updated_at"])
    spawn_next_occurrence(task)
    return task


@transaction.atomic
def soft_delete_task(task: Task) -> None:
    deleted_at = timezone.now()
    for child in Task.objects.filter(parent=task):
        child.deleted_at = deleted_at
        child.save(update_fields=["deleted_at", "updated_at"])
    task.deleted_at = deleted_at
    task.save(update_fields=["deleted_at", "updated_at"])


@transaction.atomic
def restore_task(task: Task) -> Task:
    if task.parent_id is not None and Task.objects.all_with_deleted().filter(
        pk=task.parent_id,
        deleted_at__isnull=False,
    ).exists():
        raise RestoreError("Restore the parent first.")
    parent_deleted_at = task.deleted_at
    task.deleted_at = None
    task.save(update_fields=["deleted_at", "updated_at"])
    if task.parent_id is None and parent_deleted_at is not None:
        for child in Task.objects.all_with_deleted().filter(
            parent=task,
            deleted_at=parent_deleted_at,
        ):
            child.deleted_at = None
            child.save(update_fields=["deleted_at", "updated_at"])
    return task


@transaction.atomic
def reorder_tasks(
    *,
    task_list: TaskList,
    ordered_ids: Iterable[int],
    parent: Task | None = None,
) -> None:
    ids = [int(task_id) for task_id in ordered_ids if str(task_id).strip()]
    if not ids:
        return

    scope = Task.objects.filter(task_list=task_list, parent=parent, id__in=ids)
    found_ids = set(scope.values_list("id", flat=True))
    if found_ids != set(ids):
        missing = sorted(set(ids) - found_ids)
        raise ValueError(f"Task ids outside reorder scope: {missing}")

    for index, task_id in enumerate(ids):
        Task.objects.filter(id=task_id).update(order=index)

    TaskEvent.objects.create(
        task=None,
        task_list=task_list,
        session_key=task_list.session_key,
        action=TaskEventAction.REORDERED,
        changes={
            "parent_id": parent.id if parent else None,
            "order": ids,
        },
    )


@transaction.atomic
def set_recurrence(
    task: Task,
    *,
    frequency: str,
    interval: int,
    weekday_mask: int | None = None,
    day_of_month: int | None = None,
    end_date=None,
) -> Recurrence:
    recurrence = task.recurrence or Recurrence()
    recurrence.frequency = frequency
    recurrence.interval = max(1, interval)
    recurrence.weekday_mask = (
        weekday_mask if frequency == RecurrenceFrequency.WEEKLY else None
    )
    recurrence.day_of_month = (
        day_of_month if frequency == RecurrenceFrequency.MONTHLY else None
    )
    recurrence.end_date = end_date
    recurrence.full_clean()
    recurrence.save()
    task.recurrence = recurrence
    task.save(update_fields=["recurrence", "updated_at"])
    return recurrence


@transaction.atomic
def clear_recurrence(task: Task) -> None:
    recurrence = task.recurrence
    if not recurrence:
        return
    recurrence_id = recurrence.id
    task.recurrence = None
    task.save(update_fields=["recurrence", "updated_at"])
    if not Task.objects.filter(recurrence_id=recurrence_id).exists():
        recurrence.delete()


@transaction.atomic
def spawn_next_occurrence(task: Task) -> Task | None:
    template = task if task.recurrence_id else task.spawned_from
    if not template or template.deleted_at or not template.recurrence_id:
        return None

    recurrence = template.recurrence
    base_due = task.due_date or timezone.now()
    next_due = compute_next_due_date(base_due, recurrence)
    if next_due is None:
        return None

    duplicate_exists = Task.objects.filter(
        task_list=template.task_list,
        spawned_from=template,
        due_date=next_due,
        status=TaskStatus.OPEN,
    ).exists()
    if duplicate_exists:
        TaskEvent.objects.create(
            task=task,
            task_list=template.task_list,
            session_key=template.task_list.session_key,
            action=TaskEventAction.SPAWNED,
            changes={
                "template_id": template.id,
                "due_date": next_due.isoformat(),
                "duplicate": True,
            },
        )
        return None

    occurrence = Task.objects.create(
        task_list=template.task_list,
        parent=None,
        title=template.title,
        notes=template.notes,
        due_date=next_due,
        priority=template.priority,
        order=next_order(template.task_list),
        spawned_from=template,
    )
    TaskEvent.objects.create(
        task=occurrence,
        task_list=template.task_list,
        session_key=template.task_list.session_key,
        action=TaskEventAction.SPAWNED,
        changes={
            "template_id": template.id,
            "occurrence_id": occurrence.id,
            "due_date": (
                occurrence.due_date.isoformat() if occurrence.due_date else None
            ),
        },
    )
    return occurrence


def compute_next_due_date(base_due, recurrence: Recurrence):
    local_base = timezone.localtime(base_due)
    if recurrence.frequency == RecurrenceFrequency.DAILY:
        next_local = _add_local_days(local_base, recurrence.interval)
    elif recurrence.frequency == RecurrenceFrequency.WEEKLY:
        next_local = _next_weekly(local_base, recurrence)
    else:
        next_local = _next_monthly(local_base, recurrence)

    if recurrence.end_date and next_local.date() > recurrence.end_date:
        return None
    return next_local


def _add_local_days(local_base: datetime, days: int) -> datetime:
    """Advance by calendar days while preserving local wall-clock time."""
    target_date = local_base.date() + timedelta(days=days)
    return local_base.replace(
        year=target_date.year,
        month=target_date.month,
        day=target_date.day,
    )


def _next_weekly(local_base: datetime, recurrence: Recurrence) -> datetime:
    if not recurrence.weekday_mask:
        return _add_local_days(local_base, 7 * recurrence.interval)

    anchor_week_start = local_base.date() - timedelta(days=local_base.weekday())
    for offset in range(1, 371):
        candidate = _add_local_days(local_base, offset)
        candidate_week_start = candidate.date() - timedelta(days=candidate.weekday())
        weeks = (candidate_week_start - anchor_week_start).days // 7
        bit = 1 << candidate.weekday()
        if weeks % recurrence.interval == 0 and recurrence.weekday_mask & bit:
            return candidate
    return _add_local_days(local_base, 7 * recurrence.interval)


def _next_monthly(local_base: datetime, recurrence: Recurrence) -> datetime:
    target_months = recurrence.interval
    month_index = local_base.month - 1 + target_months
    year = local_base.year + month_index // 12
    month = month_index % 12 + 1
    day = recurrence.day_of_month or local_base.day
    last_day = calendar.monthrange(year, month)[1]
    return local_base.replace(year=year, month=month, day=min(day, last_day))


def _export_filename(task_list: TaskList, extension: str) -> str:
    stem = slugify(task_list.name, allow_unicode=True) or "tasks"
    return f"{stem}.{extension}"


def export_tasks(task_list: TaskList, *, fmt: str) -> ExportResult:
    child_qs = Task.objects.all_with_deleted().ordered()
    tasks = (
        Task.objects.all_with_deleted()
        .filter(task_list=task_list, parent__isnull=True)
        .ordered()
        .prefetch_related(Prefetch("children", queryset=child_qs))
    )
    if fmt == "json":
        import json

        body = json.dumps([_task_to_json(task) for task in tasks], indent=2)
        return ExportResult(
            filename=_export_filename(task_list, "json"),
            content_type="application/json",
            body=body,
        )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "parent_id",
            "title",
            "status",
            "priority",
            "due_date",
            "deleted_at",
            "created_at",
        ]
    )
    for task in tasks:
        _write_task_csv_row(writer, task)
        for child in task.children.all():
            _write_task_csv_row(writer, child)
    return ExportResult(
        filename=_export_filename(task_list, "csv"),
        content_type="text/csv",
        body=buffer.getvalue(),
    )


def _export_safe_text(value: str) -> str:
    if not value:
        return value
    if value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _task_to_json(task: Task) -> dict:
    return {
        "id": task.id,
        "title": _export_safe_text(task.title),
        "notes": _export_safe_text(task.notes),
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "deleted_at": task.deleted_at.isoformat() if task.deleted_at else None,
        "subtasks": [_task_to_json(child) for child in task.children.all()],
    }


def _write_task_csv_row(writer, task: Task) -> None:
    writer.writerow(
        [
            task.id,
            task.parent_id or "",
            _export_safe_text(task.title),
            task.status,
            task.priority,
            task.due_date.isoformat() if task.due_date else "",
            task.deleted_at.isoformat() if task.deleted_at else "",
            task.created_at.isoformat(),
        ]
    )
