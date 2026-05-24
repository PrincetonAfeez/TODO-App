""" Admin configuration for the project """

from django.contrib import admin

from .models import Recurrence, Task, TaskEvent, TaskList


@admin.register(TaskList)
class TaskListAdmin(admin.ModelAdmin):
    list_display = ("name", "session_key", "created_at")
    search_fields = ("name", "session_key")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "task_list",
        "status",
        "priority",
        "due_date",
        "deleted_at",
    )
    list_filter = ("status", "priority", "deleted_at")
    search_fields = ("title", "notes")

    def get_queryset(self, request):
        # Default Task.objects hides soft-deleted rows; admin should still
        # show them so the deleted_at column and filter are usable.
        return Task.objects.all_with_deleted()


@admin.register(Recurrence)
class RecurrenceAdmin(admin.ModelAdmin):
    list_display = ("frequency", "interval", "weekday_mask", "day_of_month", "end_date")


@admin.register(TaskEvent)
class TaskEventAdmin(admin.ModelAdmin):
    list_display = ("action", "task", "task_list", "session_key", "created_at")
    list_filter = ("action",)
    search_fields = ("task__title", "task_list__name", "session_key")
