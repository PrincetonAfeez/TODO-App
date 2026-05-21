from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("", views.home, name="home"),
    path("lists/", views.lists_view, name="lists"),
    path("lists/<int:list_id>/", views.list_detail, name="list_detail"),
    path("lists/<int:list_id>/rename/", views.rename_list, name="rename_list"),
    path("lists/<int:list_id>/delete/", views.delete_list, name="delete_list"),
    path("lists/<int:list_id>/tasks/", views.create_task_view, name="create_task"),
    path(
        "lists/<int:list_id>/reorder/", views.reorder_list_tasks, name="reorder_tasks"
    ),
    path("lists/<int:list_id>/export.csv", views.export_csv, name="export_csv"),
    path("lists/<int:list_id>/export.json", views.export_json, name="export_json"),
    path("tasks/<int:task_id>/edit/", views.edit_task, name="edit_task"),
    path("tasks/<int:task_id>/row/", views.task_row, name="task_row"),
    path("tasks/<int:task_id>/", views.update_task_view, name="update_task"),
    path("tasks/<int:task_id>/toggle/", views.toggle_task_view, name="toggle_task"),
    path("tasks/<int:task_id>/delete/", views.delete_task_view, name="delete_task"),
    path("tasks/<int:task_id>/restore/", views.restore_task_view, name="restore_task"),
    path(
        "tasks/<int:task_id>/subtasks/",
        views.create_subtask_view,
        name="create_subtask",
    ),
    path(
        "tasks/<int:task_id>/reorder-subtasks/",
        views.reorder_subtasks,
        name="reorder_subtasks",
    ),
    path(
        "tasks/<int:task_id>/recurrence/",
        views.set_recurrence_view,
        name="set_recurrence",
    ),
    path(
        "tasks/<int:task_id>/recurrence/clear/",
        views.clear_recurrence_view,
        name="clear_recurrence",
    ),
    path("events/", views.events_view, name="events"),
]
