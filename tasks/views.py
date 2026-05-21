from __future__ import annotations

import json
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import services
from .forms import RecurrenceForm, TaskForm, TaskListForm
from .models import (
    Task,
    TaskEvent,
    TaskEventAction,
    TaskList,
    TaskPriority,
    TaskStatus,
)


def _session_key(request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _lists_for_request(request):
    return (
        TaskList.objects.for_session(_session_key(request))
        .with_active_task_counts()
        .order_by("name")
    )


def _list_or_404(request, list_id: int) -> TaskList:
    return get_object_or_404(_lists_for_request(request), id=list_id)


def _task_or_404(request, task_id: int) -> Task:
    return get_object_or_404(
        Task.objects.all_with_deleted()
        .for_session(_session_key(request))
        .select_related("task_list", "parent", "recurrence", "spawned_from"),
        id=task_id,
    )


def _guard_deleted_task_mutation(task: Task) -> HttpResponseBadRequest | None:
    if task.is_deleted:
        return HttpResponseBadRequest("Deleted tasks are read-only; restore first.")
    return None


def _base_context(request, *, task_lists=None, **kwargs):
    if task_lists is None:
        task_lists = _lists_for_request(request)
    return {"task_lists": task_lists, **kwargs}


def _with_toast(response: HttpResponse, message: str) -> HttpResponse:
    response["HX-Trigger"] = json.dumps({"showToast": {"message": message}})
    return response


def _append_list_count_oob(
    request, response: HttpResponse, task_list: TaskList
) -> HttpResponse:
    if not request.htmx:
        return response
    count = Task.objects.filter(
        task_list=task_list,
        status=TaskStatus.OPEN,
    ).count()
    oob = render_to_string(
        "tasks/partials/_list_count_oob.html",
        {"task_list_id": task_list.id, "count": count},
        request=request,
    )
    response.content += oob.encode()
    return response


def _append_empty_state_oob_delete(request, response: HttpResponse) -> HttpResponse:
    if not request.htmx:
        return response
    oob = render_to_string(
        "tasks/partials/_empty_state_oob_delete.html",
        request=request,
    )
    response.content += oob.encode()
    return response


def _append_empty_state_oob_insert(request, response: HttpResponse) -> HttpResponse:
    if not request.htmx:
        return response
    oob = render_to_string(
        "tasks/partials/_empty_state_oob_insert.html",
        request=request,
    )
    response.content += oob.encode()
    return response


def _fetch_parent_for_subtask_count_oob(parent_id: int) -> Task:
    return (
        Task.objects.all_with_deleted()
        .prefetch_related("children")
        .get(pk=parent_id)
    )


def _append_subtask_count_oob(
    request, response: HttpResponse, parent: Task
) -> HttpResponse:
    """Append subtask count OOB swap.

    ``parent`` must be a fresh instance with ``children`` prefetched (see
    ``_fetch_parent_for_subtask_count_oob``).
    """
    if not request.htmx:
        return response
    oob = render_to_string(
        "tasks/partials/_subtask_count_oob.html",
        {"task": parent},
        request=request,
    )
    response.content += oob.encode()
    return response


def _with_subtask_count_oob(
    request, response: HttpResponse, task: Task
) -> HttpResponse:
    if task.parent_id:
        parent = _fetch_parent_for_subtask_count_oob(task.parent_id)
        return _append_subtask_count_oob(request, response, parent)
    return response


def _htmx_response(
    request,
    response: HttpResponse,
    *,
    message: str | None = None,
    task_list: TaskList | None = None,
) -> HttpResponse:
    if message:
        response = _with_toast(response, message)
    if task_list:
        response = _append_list_count_oob(request, response, task_list)
    return response


def _ids_from_post(request) -> list[str]:
    ids: list[str] = []
    for raw in request.POST.getlist("order"):
        ids.extend(value for value in raw.replace(",", " ").split() if value.strip())
    if ids:
        return ids
    raw = request.POST.get("order", "")
    return [value for value in raw.replace(",", " ").split() if value.strip()]


def _task_partial(task: Task, request, *, group: bool = False) -> HttpResponse:
    template = (
        "tasks/partials/_task_group.html" if group else "tasks/partials/_task_row.html"
    )
    return render(request, template, _task_row_context(task))


def _task_row_context(task: Task, **extra):
    return {
        "task": task,
        "recurrence_form": RecurrenceForm(),
        "subtask_form": TaskForm(),
        **extra,
    }


def _first_form_error(form) -> str:
    for errors in form.errors.values():
        if errors:
            return str(errors[0])
    return "Please fix the errors below."


def _show_task_details(form, post) -> bool:
    if (
        form.errors.get("due_date")
        or form.errors.get("notes")
        or form.errors.get("priority")
    ):
        return True
    if post.get("notes", "").strip():
        return True
    if post.get("due_date", "").strip():
        return True
    priority = post.get("priority", "medium")
    return bool(priority and priority != "medium")


def _create_task_form_context(request, task_list, form, *, post=None):
    post = post or {}
    return _base_context(
        request,
        current_list=task_list,
        form=form,
        priority_choices=TaskPriority.choices,
        show_task_details=_show_task_details(form, post),
        # Raw POST passthrough for datetime-local on 422; notes use form.notes.value.
        due_date_value=post.get("due_date", ""),
    )


def _htmx_form_error(
    request,
    *,
    template: str,
    context: dict,
    target: str,
    status: int = 422,
) -> HttpResponse:
    response = render(request, template, context, status=status)
    if request.htmx:
        response["HX-Retarget"] = target
        response["HX-Reswap"] = "outerHTML"
    return response


@require_GET
def home(request):
    task_list = services.ensure_default_list(_session_key(request))
    return redirect("tasks:list_detail", list_id=task_list.id)


@require_http_methods(["GET", "POST"])
def lists_view(request):
    current_list = None
    if request.method == "POST":
        form = TaskListForm(request.POST)
        if form.is_valid():
            session_key = _session_key(request)
            task_list = form.save(commit=False)
            task_list.session_key = session_key
            try:
                with transaction.atomic():
                    task_list.save()
            except IntegrityError:
                form.add_error("name", "You already have a list with that name.")
            else:
                messages.success(request, "List created.")
                if request.htmx:
                    task_lists = _lists_for_request(request)
                    current_list = None
                    current_list_id = request.POST.get("current_list_id")
                    if current_list_id and str(current_list_id).isdigit():
                        current_list = next(
                            (
                                task_list_item
                                for task_list_item in task_lists
                                if task_list_item.id == int(current_list_id)
                            ),
                            None,
                        )
                    return _with_toast(
                        render(
                            request,
                            "tasks/partials/_list_sidebar.html",
                            _base_context(
                                request,
                                task_lists=task_lists,
                                current_list=current_list,
                            ),
                        ),
                        "List created",
                    )
                return redirect("tasks:list_detail", list_id=task_list.id)
        if request.htmx:
            return HttpResponseBadRequest("Could not create list.")
        return render(
            request,
            "tasks/lists.html",
            _base_context(request, current_list=None, list_form=form),
        )

    task_list = services.ensure_default_list(_session_key(request))
    return render(
        request,
        "tasks/lists.html",
        _base_context(request, current_list=task_list, list_form=TaskListForm()),
    )


@require_GET
def list_detail(request, list_id: int):
    task_list = _list_or_404(request, list_id)
    show_deleted = request.GET.get("show_deleted") == "1"
    base_qs = Task.objects.all_with_deleted() if show_deleted else Task.objects
    child_qs = base_qs.ordered()
    view_filter = request.GET.get("view", "all")
    status = request.GET.get("status")
    priority = request.GET.get("priority")
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "manual")
    tasks = (
        base_qs.filter(task_list=task_list, parent__isnull=True)
        .select_related("recurrence", "spawned_from")
        .prefetch_related(Prefetch("children", queryset=child_qs))
        .apply_list_filters(
            view=view_filter,
            status=status if status in TaskStatus.values else None,
            priority=priority if priority in TaskPriority.values else None,
            query=query,
            sort=sort,
        )
    )

    context = _base_context(
        request,
        current_list=task_list,
        task_form=TaskForm(),
        list_form=TaskListForm(),
        recurrence_form=RecurrenceForm(),
        tasks=tasks,
        show_deleted=show_deleted,
        filters={
            "view": view_filter,
            "status": status or "",
            "priority": priority or "",
            "sort": sort,
            "q": query,
        },
        status_choices=TaskStatus.choices,
        priority_choices=TaskPriority.choices,
    )
    if request.htmx:
        return render(request, "tasks/partials/_task_list.html", context)
    return render(request, "tasks/list_detail.html", context)


@require_POST
def rename_list(request, list_id: int):
    task_list = _list_or_404(request, list_id)
    form = TaskListForm(request.POST, instance=task_list)
    if form.is_valid():
        form.save()
        messages.success(request, "List renamed.")
    return redirect("tasks:list_detail", list_id=task_list.id)


@require_POST
def delete_list(request, list_id: int):
    task_list = _list_or_404(request, list_id)
    task_list.delete()
    next_list = _lists_for_request(request).first()
    if next_list:
        return redirect("tasks:list_detail", list_id=next_list.id)
    return redirect("tasks:home")


@require_POST
def create_task_view(request, list_id: int):
    task_list = _list_or_404(request, list_id)
    form = TaskForm(request.POST)
    if not form.is_valid():
        if request.htmx:
            return _htmx_form_error(
                request,
                template="tasks/partials/_new_task_form.html",
                context=_create_task_form_context(
                    request, task_list, form, post=request.POST
                ),
                target="#new-task-form",
            )
        return HttpResponseBadRequest(_first_form_error(form))
    was_empty = not Task.objects.filter(
        task_list=task_list, parent__isnull=True
    ).exists()
    task = services.create_task(task_list=task_list, **form.cleaned_data)
    if request.htmx:
        response = _htmx_response(
            request,
            render(
                request,
                "tasks/partials/_task_group.html",
                _task_row_context(task),
            ),
            message="Task created",
            task_list=task_list,
        )
        if was_empty:
            response = _append_empty_state_oob_delete(request, response)
        return response
    return redirect("tasks:list_detail", list_id=task_list.id)


@require_GET
def task_row(request, task_id: int):
    task = _task_or_404(request, task_id)
    template = (
        "tasks/partials/_subtask_row.html"
        if task.parent_id
        else "tasks/partials/_task_row.html"
    )
    return render(request, template, _task_row_context(task))


@require_GET
def edit_task(request, task_id: int):
    task = _task_or_404(request, task_id)
    if denied := _guard_deleted_task_mutation(task):
        return denied
    return render(
        request,
        "tasks/partials/_task_edit_form.html",
        {"task": task, "form": TaskForm(instance=task)},
    )


@require_POST
def update_task_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    if denied := _guard_deleted_task_mutation(task):
        return denied
    form = TaskForm(request.POST, instance=task)
    if not form.is_valid():
        if request.htmx:
            return render(
                request,
                "tasks/partials/_task_edit_form.html",
                {"task": task, "form": form},
                status=422,
            )
        return HttpResponseBadRequest(_first_form_error(form))
    task = services.update_task(task, **form.cleaned_data)
    template = (
        "tasks/partials/_subtask_row.html"
        if task.parent_id
        else "tasks/partials/_task_row.html"
    )
    response = _htmx_response(
        request,
        render(request, template, _task_row_context(task)),
        message="Task updated",
        task_list=task.task_list,
    )
    return _with_subtask_count_oob(request, response, task)


@require_POST
def toggle_task_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    if denied := _guard_deleted_task_mutation(task):
        return denied
    task_list = task.task_list
    task = services.toggle_task(task)
    message = "Task reopened" if task.status == TaskStatus.OPEN else "Task completed"
    if task.parent_id:
        response = _htmx_response(
            request,
            render(
                request,
                "tasks/partials/_subtask_row.html",
                _task_row_context(task),
            ),
            message=message,
            task_list=task_list,
        )
        return _with_subtask_count_oob(request, response, task)
    task = _task_or_404(request, task.id)
    return _htmx_response(
        request,
        _task_partial(task, request, group=True),
        message=message,
        task_list=task_list,
    )


@require_POST
def delete_task_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    task_list = task.task_list
    parent_for_oob = task.parent
    services.soft_delete_task(task)
    if request.htmx:
        response = _htmx_response(
            request,
            HttpResponse(""),
            message="Task moved to deleted",
            task_list=task_list,
        )
        if not Task.objects.filter(task_list=task_list, parent__isnull=True).exists():
            response = _append_empty_state_oob_insert(request, response)
        if parent_for_oob:
            parent = _fetch_parent_for_subtask_count_oob(parent_for_oob.pk)
            return _append_subtask_count_oob(request, response, parent)
        return response
    return redirect("tasks:list_detail", list_id=task.task_list_id)


@require_POST
def restore_task_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    task_list = task.task_list
    try:
        task = services.restore_task(task)
    except services.RestoreError as exc:
        message = str(exc)
        if request.htmx:
            return _with_toast(HttpResponseBadRequest(message), message)
        return HttpResponseBadRequest(message)
    template = (
        "tasks/partials/_subtask_row.html"
        if task.parent_id
        else "tasks/partials/_task_group.html"
    )
    response = _htmx_response(
        request,
        render(request, template, _task_row_context(task)),
        message="Task restored",
        task_list=task_list,
    )
    return _with_subtask_count_oob(request, response, task)


@require_POST
def create_subtask_view(request, task_id: int):
    parent = _task_or_404(request, task_id)
    if parent.parent_id:
        raise Http404("Subtasks cannot have subtasks.")
    form = TaskForm(request.POST)
    if not form.is_valid():
        if request.htmx:
            return _htmx_form_error(
                request,
                template="tasks/partials/_subtask_create_form.html",
                context={"task": parent, "form": form},
                target=f"#subtask-form-{parent.id}",
            )
        return HttpResponseBadRequest(_first_form_error(form))
    task = services.create_task(
        task_list=parent.task_list,
        parent=parent,
        **form.cleaned_data,
    )
    if request.htmx:
        response = _htmx_response(
            request,
            render(
                request,
                "tasks/partials/_subtask_row.html",
                _task_row_context(task),
            ),
            message="Subtask created",
            task_list=parent.task_list,
        )
        return _append_subtask_count_oob(
            request,
            response,
            _fetch_parent_for_subtask_count_oob(parent.pk),
        )
    return redirect("tasks:list_detail", list_id=parent.task_list_id)


@require_POST
def reorder_list_tasks(request, list_id: int):
    task_list = _list_or_404(request, list_id)
    try:
        services.reorder_tasks(task_list=task_list, ordered_ids=_ids_from_post(request))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    return HttpResponse(status=204)


@require_POST
def reorder_subtasks(request, task_id: int):
    parent = _task_or_404(request, task_id)
    try:
        services.reorder_tasks(
            task_list=parent.task_list,
            parent=parent,
            ordered_ids=_ids_from_post(request),
        )
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    return HttpResponse(status=204)


@require_POST
def set_recurrence_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    if denied := _guard_deleted_task_mutation(task):
        return denied
    if task.parent_id:
        return HttpResponseBadRequest("Subtasks cannot recur.")
    form = RecurrenceForm(request.POST)
    if not form.is_valid():
        return _htmx_form_error(
            request,
            template="tasks/partials/_recurrence_form.html",
            context={"task": task, "form": form},
            target=f"#recurrence-form-{task.id}",
        )
    services.set_recurrence(
        task,
        frequency=form.cleaned_data["frequency"],
        interval=form.cleaned_data["interval"],
        weekday_mask=form.weekday_mask,
        day_of_month=form.cleaned_data.get("day_of_month"),
        end_date=form.cleaned_data.get("end_date"),
    )
    task = _task_or_404(request, task.id)
    return _with_toast(
        render(
            request,
            "tasks/partials/_recurrence_form.html",
            {"task": task, "form": RecurrenceForm()},
        ),
        "Recurrence saved",
    )


@require_POST
def clear_recurrence_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    if denied := _guard_deleted_task_mutation(task):
        return denied
    services.clear_recurrence(task)
    task = _task_or_404(request, task.id)
    return _with_toast(
        render(
            request,
            "tasks/partials/_recurrence_form.html",
            {"task": task, "form": RecurrenceForm()},
        ),
        "Recurrence cleared",
    )


def _export(request, list_id: int, fmt: str):
    task_list = _list_or_404(request, list_id)
    result = services.export_tasks(task_list, fmt=fmt)
    response = HttpResponse(result.body, content_type=result.content_type)
    response["Content-Disposition"] = content_disposition_header(
        as_attachment=True,
        filename=result.filename,
    )
    return response


@require_GET
def export_csv(request, list_id: int):
    return _export(request, list_id, "csv")


@require_GET
def export_json(request, list_id: int):
    return _export(request, list_id, "json")


@require_GET
def events_view(request):
    events = TaskEvent.objects.filter(session_key=_session_key(request)).select_related(
        "task", "task_list"
    )
    action = request.GET.get("action")
    if action in TaskEventAction.values:
        events = events.filter(action=action)
    list_id = request.GET.get("list")
    if list_id and str(list_id).isdigit():
        events = events.filter(task_list_id=list_id)

    paginator = Paginator(events, 25)
    page = paginator.get_page(request.GET.get("page"))
    filter_params = {}
    if action in TaskEventAction.values:
        filter_params["action"] = action
    if list_id and str(list_id).isdigit():
        filter_params["list"] = list_id
    return render(
        request,
        "tasks/events.html",
        _base_context(
            request,
            page=page,
            actions=TaskEventAction.choices,
            current_action=action or "",
            current_list_id=list_id or "",
            events_filter_query=urlencode(filter_params),
        ),
    )
