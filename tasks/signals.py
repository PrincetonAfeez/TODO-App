from __future__ import annotations

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Task, TaskEvent, TaskEventAction, TaskStatus

STATUS_EVENT_FIELDS = {"status", "completed_at"}
DELETE_EVENT_FIELDS = {"deleted_at"}

TRACKED_FIELDS = [
    "task_list_id",
    "parent_id",
    "title",
    "notes",
    "due_date",
    "status",
    "priority",
    "order",
    "recurrence_id",
    "spawned_from_id",
    "completed_at",
    "deleted_at",
]


def _serialize(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _snapshot(task: Task) -> dict:
    return {field: getattr(task, field) for field in TRACKED_FIELDS}


def _emit(task: Task, action: str, changes: dict | None = None) -> None:
    TaskEvent.objects.create(
        task=task,
        task_list=task.task_list,
        session_key=task.task_list.session_key,
        action=action,
        changes=changes or {},
    )


@receiver(pre_save, sender=Task)
def capture_old_task_values(sender, instance: Task, **kwargs) -> None:
    if not instance.pk:
        instance._old_values = None
        return
    old = (
        sender.objects.all_with_deleted()
        .filter(pk=instance.pk)
        .values(*TRACKED_FIELDS)
        .first()
    )
    if old is None:
        instance._old_values = None
        return
    instance._old_values = old


@receiver(post_save, sender=Task)
def emit_task_events(sender, instance: Task, created: bool, **kwargs) -> None:
    if created:
        _emit(instance, TaskEventAction.CREATED)
        return

    old_values = getattr(instance, "_old_values", None)
    if not old_values:
        return

    new_values = _snapshot(instance)
    changes = {
        field: [_serialize(old_values[field]), _serialize(new_values[field])]
        for field in TRACKED_FIELDS
        if old_values[field] != new_values[field]
    }
    if not changes:
        return

    old_status = old_values.get("status")
    new_status = new_values.get("status")
    status_completed = old_status == TaskStatus.OPEN and new_status == TaskStatus.DONE
    status_reopened = old_status == TaskStatus.DONE and new_status == TaskStatus.OPEN

    old_deleted = old_values.get("deleted_at")
    new_deleted = new_values.get("deleted_at")
    soft_deleted = old_deleted is None and new_deleted is not None
    restored = old_deleted is not None and new_deleted is None

    covered_fields: set[str] = set()
    if status_completed:
        _emit(instance, TaskEventAction.COMPLETED)
        covered_fields |= STATUS_EVENT_FIELDS
    elif status_reopened:
        _emit(instance, TaskEventAction.REOPENED)
        covered_fields |= STATUS_EVENT_FIELDS

    if soft_deleted:
        _emit(instance, TaskEventAction.SOFT_DELETED)
        covered_fields |= DELETE_EVENT_FIELDS
    elif restored:
        _emit(instance, TaskEventAction.RESTORED)
        covered_fields |= DELETE_EVENT_FIELDS

    update_changes = {
        field: value for field, value in changes.items() if field not in covered_fields
    }
    if update_changes:
        _emit(instance, TaskEventAction.UPDATED, update_changes)
