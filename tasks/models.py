from __future__ import annotations

from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone


class TaskStatus(models.TextChoices):
    OPEN = "open", "Open"
    DONE = "done", "Done"


class TaskPriority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class RecurrenceFrequency(models.TextChoices):
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"


class TaskEventAction(models.TextChoices):
    CREATED = "created", "Created"
    UPDATED = "updated", "Updated"
    COMPLETED = "completed", "Completed"
    REOPENED = "reopened", "Reopened"
    SOFT_DELETED = "soft_deleted", "Soft deleted"
    RESTORED = "restored", "Restored"
    REORDERED = "reordered", "Reordered"
    SPAWNED = "spawned", "Spawned"


class TaskListQuerySet(models.QuerySet):
    def for_session(self, session_key: str):
        return self.filter(session_key=session_key)

    def with_active_task_counts(self):
        # Count open, non-deleted, top-level tasks. The sidebar label "open
        # item(s)" reflects the main list view, which renders top-level
        # rows; including subtasks would inflate the count beyond what is
        # visible.
        return self.annotate(
            active_task_count=models.Count(
                "tasks",
                filter=models.Q(
                    tasks__deleted_at__isnull=True,
                    tasks__status=TaskStatus.OPEN,
                    tasks__parent__isnull=True,
                ),
            )
        )


class TaskListManager(models.Manager.from_queryset(TaskListQuerySet)):
    pass


class TaskList(models.Model):
    name = models.CharField(max_length=120)
    session_key = models.CharField(max_length=80, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TaskListManager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["session_key", "name"],
                name="unique_task_list_name_per_session",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Recurrence(models.Model):
    frequency = models.CharField(
        max_length=12,
        choices=RecurrenceFrequency.choices,
    )
    interval = models.PositiveIntegerField(default=1)
    weekday_mask = models.PositiveSmallIntegerField(null=True, blank=True)
    day_of_month = models.PositiveSmallIntegerField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        units = {
            RecurrenceFrequency.DAILY: ("day", "days"),
            RecurrenceFrequency.WEEKLY: ("week", "weeks"),
            RecurrenceFrequency.MONTHLY: ("month", "months"),
        }
        singular, plural = units[self.frequency]
        label = singular if self.interval == 1 else plural
        if self.interval == 1:
            return f"Every {label}"
        return f"Every {self.interval} {label}"

    def clean(self) -> None:
        errors = {}
        if self.interval < 1:
            errors["interval"] = "Interval must be at least 1."
        if self.day_of_month is not None and not 1 <= self.day_of_month <= 31:
            errors["day_of_month"] = "Day of month must be between 1 and 31."
        if self.weekday_mask is not None and not 1 <= self.weekday_mask <= 127:
            errors["weekday_mask"] = "Weekday mask must fit Monday through Sunday."
        if errors:
            raise ValidationError(errors)


class TaskQuerySet(models.QuerySet):
    def deleted_only(self):
        return self.filter(deleted_at__isnull=False)

    def for_session(self, session_key: str):
        return self.filter(task_list__session_key=session_key)

    def top_level(self):
        return self.filter(parent__isnull=True)

    def subtasks_of(self, task: Task):
        return self.filter(parent=task)

    def due_today(self):
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, time.min))
        end = timezone.make_aware(datetime.combine(today, time.max))
        return self.filter(due_date__range=(start, end))

    def overdue(self):
        return self.filter(
            status=TaskStatus.OPEN,
            due_date__lt=timezone.now(),
        )

    def upcoming(self):
        today = timezone.localdate()
        end = timezone.make_aware(datetime.combine(today, time.max))
        return self.filter(due_date__gt=end)

    def templates(self):
        return self.filter(recurrence__isnull=False)

    def occurrences_of(self, template: Task):
        return self.filter(spawned_from=template)

    def ordered(self):
        return self.order_by("order", "created_at")

    def apply_list_filters(
        self,
        *,
        view: str = "all",
        status: str | None = None,
        priority: str | None = None,
        query: str = "",
        sort: str = "manual",
    ):
        tasks = self
        if view == "today":
            tasks = tasks.due_today()
        elif view == "upcoming":
            tasks = tasks.upcoming()
        elif view == "overdue":
            tasks = tasks.overdue()

        if status in TaskStatus.values:
            tasks = tasks.filter(status=status)

        if priority in TaskPriority.values:
            tasks = tasks.filter(priority=priority)

        stripped = query.strip()
        if stripped:
            # Search top-level title and notes. Subtask matches do not
            # surface their parent; this is documented in To-Do App.txt.
            tasks = tasks.filter(
                Q(title__icontains=stripped) | Q(notes__icontains=stripped)
            )

        if sort == "due_date":
            return tasks.order_by("due_date", "order")
        if sort == "priority":
            return tasks.annotate(
                priority_rank=Case(
                    When(priority=TaskPriority.HIGH, then=Value(0)),
                    When(priority=TaskPriority.MEDIUM, then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                )
            ).order_by("priority_rank", "order")
        if sort == "created_at":
            return tasks.order_by("-created_at")
        return tasks.ordered()


class TaskManager(models.Manager.from_queryset(TaskQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

    def all_with_deleted(self):
        return TaskQuerySet(self.model, using=self._db)

    def deleted_only(self):
        return self.all_with_deleted().deleted_only()


class Task(models.Model):
    task_list = models.ForeignKey(
        TaskList,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    title = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=8,
        choices=TaskStatus.choices,
        default=TaskStatus.OPEN,
    )
    priority = models.CharField(
        max_length=8,
        choices=TaskPriority.choices,
        default=TaskPriority.MEDIUM,
    )
    order = models.PositiveIntegerField(default=0)
    recurrence = models.ForeignKey(
        Recurrence,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="template_tasks",
    )
    spawned_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spawned_occurrences",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = TaskManager()

    class Meta:
        ordering = ["order", "created_at"]
        indexes = [
            models.Index(fields=["task_list"]),
            models.Index(fields=["parent"]),
            models.Index(fields=["status"]),
            models.Index(fields=["due_date"]),
            models.Index(fields=["deleted_at"]),
            models.Index(fields=["task_list", "parent", "order"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=TaskStatus.values),
                name="task_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(priority__in=TaskPriority.values),
                name="task_priority_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self) -> None:
        errors = {}
        if self.parent_id:
            parent = self.parent
            if parent.parent_id:
                errors["parent"] = "Subtasks cannot have their own subtasks."
            if parent.task_list_id != self.task_list_id:
                errors["parent"] = "Subtasks must belong to the same task list."
            if self.recurrence_id:
                errors["recurrence"] = "Subtasks cannot be recurrence templates."
        if self.pk and self.parent_id:
            has_children = Task.objects.all_with_deleted().filter(parent=self).exists()
            if has_children:
                errors["parent"] = "A task with children cannot become a subtask."
        if errors:
            raise ValidationError(errors)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def _subtask_children(self) -> list[Task]:
        return [child for child in self.children.all() if not child.is_deleted]

    @property
    def subtask_total(self) -> int:
        return len(self._subtask_children())

    @property
    def subtask_done_count(self) -> int:
        return sum(
            1
            for child in self._subtask_children()
            if child.status == TaskStatus.DONE
        )

    @property
    def has_recurrence_template(self) -> bool:
        return self.recurrence_id is not None


class TaskEvent(models.Model):
    task = models.ForeignKey(
        Task,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    task_list = models.ForeignKey(
        TaskList,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    session_key = models.CharField(max_length=80, db_index=True)
    action = models.CharField(max_length=20, choices=TaskEventAction.choices)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session_key"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} at {self.created_at:%Y-%m-%d %H:%M}"
