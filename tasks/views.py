from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urlparse

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


def _guard_deleted_task_mutation(request, task: Task) -> HttpResponseBadRequest | None:
    if task.is_deleted:
        return _htmx_error(request, "Deleted tasks are read-only; restore first.")
    return None


def _htmx_error(request, message: str, *, status: int = 400) -> HttpResponseBadRequest:
    response = HttpResponseBadRequest(message)
    if request.htmx:
        response["HX-Trigger"] = json.dumps(
            {"showToast": {"message": message, "error": True}}
        )
    return response


def _with_toast(
    response: HttpResponse, message: str, *, error: bool = False
) -> HttpResponse:
    response["HX-Trigger"] = json.dumps(
        {"showToast": {"message": message, "error": error}}
    )
    return response


def _mutation_redirect(request, task_list: TaskList, message: str) -> HttpResponse:
    messages.success(request, message)
    return redirect("tasks:list_detail", list_id=task_list.id)


def _base_context(request, *, task_lists=None, **kwargs):
    if task_lists is None:
        task_lists = _lists_for_request(request)
    return {"task_lists": task_lists, **kwargs}


def _append_list_count_oob(
    request, response: HttpResponse, task_list: TaskList
) -> HttpResponse:
    if not request.htmx:
        return response
    # Match TaskListQuerySet.with_active_task_counts(): top-level only.
    count = Task.objects.filter(
        task_list=task_list,
        status=TaskStatus.OPEN,
        parent__isnull=True,
    ).count()
    oob = render_to_string(
        "tasks/partials/_list_count_oob.html",
        {"task_list_id": task_list.id, "count": count},
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


def _fetch_parent_for_subtask_count_oob(request, parent_id: int) -> Task:
    return get_object_or_404(
        Task.objects.all_with_deleted()
        .for_session(_session_key(request))
        .prefetch_related("children"),
        pk=parent_id,
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
        parent = _fetch_parent_for_subtask_count_oob(request, task.parent_id)
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


def _ids_from_post(request) -> list[int]:
    raw_ids: list[str] = []
    for raw in request.POST.getlist("order"):
        raw_ids.extend(value for value in raw.replace(",", " ").split() if value.strip())
    if not raw_ids:
        raw = request.POST.get("order", "")
        raw_ids = [value for value in raw.replace(",", " ").split() if value.strip()]
    return [int(value) for value in raw_ids]


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
    filter_params = _list_filter_params({}, request=request)
    return _base_context(
        request,
        current_list=task_list,
        form=form,
        priority_choices=TaskPriority.choices,
        show_task_details=_show_task_details(form, post),
        list_filters_active=_list_filters_active(**filter_params),
        # Raw POST passthrough for datetime-local on 422; notes use form.notes.value.
        due_date_value=post.get("due_date", ""),
    )


def _list_filter_params(source, *, request=None, use_current_url: bool = True) -> dict:
    if use_current_url and request is not None and not source:
        current_url = request.META.get("HTTP_HX_CURRENT_URL", "")
        if current_url:
            parsed = urlparse(current_url)
            if parsed.query:
                qs = parse_qs(parsed.query)
                source = {
                    key: values[-1] if values else "" for key, values in qs.items()
                }
    view_filter = source.get("view", "all")
    status = source.get("status")
    priority = source.get("priority")
    query = source.get("q", "").strip()
    sort = source.get("sort", "manual")
    show_deleted = source.get("show_deleted") == "1"
    return {
        "view_filter": view_filter,
        "status": status,
        "priority": priority,
        "query": query,
        "sort": sort,
        "show_deleted": show_deleted,
    }


def _list_filters_active(**params) -> bool:
    view = params["view_filter"]
    status_active = view == "all" and params["status"] in TaskStatus.values
    return (
        view != "all"
        or params["sort"] != "manual"
        or bool(params["query"])
        or status_active
        or params["priority"] in TaskPriority.values
        or params["show_deleted"]
    )


def _show_deleted_mode(request) -> bool:
    return _list_filter_params({}, request=request)["show_deleted"]


def _task_for_deleted_partial(request, task_id: int) -> Task:
    return get_object_or_404(
        Task.objects.all_with_deleted()
        .for_session(_session_key(request))
        .select_related("task_list", "parent", "recurrence", "spawned_from")
        .prefetch_related(
            Prefetch(
                "children",
                queryset=Task.objects.all_with_deleted().ordered(),
            )
        ),
        id=task_id,
    )


def _export_query_string(filters: dict, *, show_deleted: bool) -> str:
    params = {}
    view = filters.get("view", "all")
    if view and view != "all":
        params["view"] = view
    if filters.get("status"):
        params["status"] = filters["status"]
    if filters.get("priority"):
        params["priority"] = filters["priority"]
    if filters.get("sort") and filters.get("sort") != "manual":
        params["sort"] = filters["sort"]
    if filters.get("q"):
        params["q"] = filters["q"]
    if show_deleted:
        params["show_deleted"] = "1"
    return urlencode(params)


def _list_detail_context(request, task_list: TaskList, *, filter_source=None, **extra):
    source = filter_source if filter_source is not None else request.GET
    params = _list_filter_params(
        source,
        request=request,
        use_current_url=filter_source is None,
    )
    view_filter = params["view_filter"]
    status = params["status"]
    priority = params["priority"]
    query = params["query"]
    sort = params["sort"]
    show_deleted = params["show_deleted"]
    base_qs = Task.objects.all_with_deleted() if show_deleted else Task.objects
    child_qs = base_qs.filter(task_list=task_list).ordered()
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
    reorder_enabled = (
        view_filter == "all"
        and sort == "manual"
        and not query
        and status not in TaskStatus.values
        and priority not in TaskPriority.values
    )
    status_filter_enabled = view_filter == "all"
    filter_values = {
        "view": view_filter,
        "status": status or "",
        "priority": priority or "",
        "sort": sort,
        "q": query,
    }
    return _base_context(
        request,
        current_list=task_list,
        task_form=TaskForm(),
        list_form=TaskListForm(),
        recurrence_form=RecurrenceForm(),
        tasks=tasks,
        show_deleted=show_deleted,
        reorder_enabled=reorder_enabled,
        list_filters_active=_list_filters_active(**params),
        status_filter_enabled=status_filter_enabled,
        filters=filter_values,
        export_query=_export_query_string(filter_values, show_deleted=show_deleted),
        status_choices=TaskStatus.choices,
        priority_choices=TaskPriority.choices,
        **extra,
    )


def _filter_source_from_request(request) -> dict:
    filter_params = _list_filter_params({}, request=request)
    return {
        "view": filter_params["view_filter"],
        "status": filter_params["status"] or "",
        "priority": filter_params["priority"] or "",
        "q": filter_params["query"],
        "sort": filter_params["sort"],
        "show_deleted": "1" if filter_params["show_deleted"] else "",
    }


def _uses_filtered_list_response(request) -> bool:
    return _list_filters_active(**_list_filter_params({}, request=request))


def _filtered_list_htmx_response(
    request, task_list: TaskList, *, message: str
) -> HttpResponse:
    context = _list_detail_context(
        request, task_list, filter_source=_filter_source_from_request(request)
    )
    response = _htmx_response(
        request,
        render(request, "tasks/partials/_task_list.html", context),
        message=message,
        task_list=task_list,
    )
    return _append_list_filter_oob_swaps(request, response, context)


def _append_new_task_form_oob(
    request, response: HttpResponse, context: dict
) -> HttpResponse:
    if not request.htmx:
        return response
    oob = render_to_string(
        "tasks/partials/_new_task_form.html",
        {
            "form": context["task_form"],
            "current_list": context["current_list"],
            "list_filters_active": context["list_filters_active"],
            "show_task_details": False,
            "due_date_value": "",
            "priority_choices": context["priority_choices"],
            "oob": True,
        },
        request=request,
    )
    response.content += oob.encode()
    return response


def _append_filter_status_oob(
    request, response: HttpResponse, context: dict
) -> HttpResponse:
    if not request.htmx:
        return response
    oob = render_to_string(
        "tasks/partials/_filter_status_select.html",
        {
            "filters": context["filters"],
            "status_choices": context["status_choices"],
            "status_filter_enabled": context["status_filter_enabled"],
            "oob": True,
        },
        request=request,
    )
    response.content += oob.encode()
    return response


def _append_list_filter_oob_swaps(
    request, response: HttpResponse, context: dict
) -> HttpResponse:
    response = _append_new_task_form_oob(request, response, context)
    return _append_filter_status_oob(request, response, context)


def _append_recurrence_badge_oob(
    request, response: HttpResponse, task: Task
) -> HttpResponse:
    if not request.htmx:
        return response
    task = _task_or_404(request, task.id)
    oob = render_to_string(
        "tasks/partials/_recurrence_badge_oob.html",
        {"task": task},
        request=request,
    )
    response.content += oob.encode()
    return response


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
                                list_form=TaskListForm(),
                            ),
                        ),
                        "List created",
                    )
                return redirect("tasks:list_detail", list_id=task_list.id)
        if request.htmx:
            current_list_id = request.POST.get("current_list_id")
            current_list = None
            if current_list_id and str(current_list_id).isdigit():
                current_list = (
                    _lists_for_request(request).filter(id=current_list_id).first()
                )
            return _htmx_form_error(
                request,
                template="tasks/partials/_list_sidebar.html",
                context=_base_context(
                    request,
                    current_list=current_list,
                    list_form=form,
                ),
                target="#list-sidebar",
            )
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
    context = _list_detail_context(request, task_list)
    if request.htmx:
        response = render(request, "tasks/partials/_task_list.html", context)
        return _append_list_filter_oob_swaps(request, response, context)
    return render(request, "tasks/list_detail.html", context)


@require_POST
def rename_list(request, list_id: int):
    task_list = _list_or_404(request, list_id)
    form = TaskListForm(request.POST, instance=task_list)
    if form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            messages.error(request, "You already have a list with that name.")
        else:
            messages.success(request, "List renamed.")
    else:
        messages.error(request, _first_form_error(form))
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
    services.create_task(task_list=task_list, **form.cleaned_data)
    if request.htmx:
        filter_params = _list_filter_params({}, request=request)
        filter_source = {
            "view": filter_params["view_filter"],
            "status": filter_params["status"] or "",
            "priority": filter_params["priority"] or "",
            "q": filter_params["query"],
            "sort": filter_params["sort"],
            "show_deleted": "1" if filter_params["show_deleted"] else "",
        }
        context = _list_detail_context(request, task_list, filter_source=filter_source)
        return _append_list_filter_oob_swaps(
            request,
            _htmx_response(
                request,
                render(request, "tasks/partials/_task_list.html", context),
                message="Task created",
                task_list=task_list,
            ),
            context,
        )
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
    if denied := _guard_deleted_task_mutation(request, task):
        return denied
    if not request.htmx:
        return redirect("tasks:list_detail", list_id=task.task_list_id)
    template = (
        "tasks/partials/_subtask_edit_form.html"
        if task.parent_id
        else "tasks/partials/_task_edit_form.html"
    )
    return render(
        request,
        template,
        {"task": task, "form": TaskForm(instance=task)},
    )


@require_POST
def update_task_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    if denied := _guard_deleted_task_mutation(request, task):
        return denied
    form = TaskForm(request.POST, instance=task)
    if not form.is_valid():
        if request.htmx:
            template = (
                "tasks/partials/_subtask_edit_form.html"
                if task.parent_id
                else "tasks/partials/_task_edit_form.html"
            )
            target = (
                f"#subtask-row-{task.id}"
                if task.parent_id
                else "closest [data-edit-form]"
            )
            return _htmx_form_error(
                request,
                template=template,
                context={"task": task, "form": form},
                target=target,
            )
        return HttpResponseBadRequest(_first_form_error(form))
    task = services.update_task(task, **form.cleaned_data)
    message = "Task updated"
    if request.htmx and not task.parent_id and _uses_filtered_list_response(request):
        return _filtered_list_htmx_response(request, task.task_list, message=message)
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
    response = _with_subtask_count_oob(request, response, task)
    if request.htmx:
        return response
    return _mutation_redirect(request, task.task_list, "Task updated")


@require_POST
def toggle_task_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    if denied := _guard_deleted_task_mutation(request, task):
        return denied
    task_list = task.task_list
    task, spawned = services.toggle_task(task)
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
        response = _with_subtask_count_oob(request, response, task)
        if request.htmx:
            return response
        return _mutation_redirect(request, task_list, message)
    if request.htmx and (
        _uses_filtered_list_response(request)
        or (
            task.status == TaskStatus.DONE
            and (spawned is not None or task.recurrence_id or task.spawned_from_id)
        )
    ):
        return _filtered_list_htmx_response(request, task_list, message=message)
    task = _task_or_404(request, task.id)
    response = _htmx_response(
        request,
        _task_partial(task, request, group=True),
        message=message,
        task_list=task_list,
    )
    if request.htmx:
        return response
    return _mutation_redirect(request, task_list, message)


@require_POST
def delete_task_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    if denied := _guard_deleted_task_mutation(request, task):
        return denied
    task_list = task.task_list
    parent_for_oob = task.parent
    services.soft_delete_task(task)
    show_deleted_mode = _show_deleted_mode(request)
    if request.htmx:
        if show_deleted_mode:
            task = _task_for_deleted_partial(request, task_id)
            template = (
                "tasks/partials/_subtask_row.html"
                if task.parent_id
                else "tasks/partials/_task_group.html"
            )
            response = _htmx_response(
                request,
                render(request, template, _task_row_context(task)),
                message="Task moved to deleted",
                task_list=task_list,
            )
            if parent_for_oob:
                parent = _fetch_parent_for_subtask_count_oob(request, parent_for_oob.pk)
                return _append_subtask_count_oob(request, response, parent)
            return response
        if not task.parent_id and _uses_filtered_list_response(request):
            return _filtered_list_htmx_response(
                request, task_list, message="Task moved to deleted"
            )
        response = _htmx_response(
            request,
            HttpResponse(""),
            message="Task moved to deleted",
            task_list=task_list,
        )
        if not Task.objects.filter(task_list=task_list, parent__isnull=True).exists():
            response = _append_empty_state_oob_insert(request, response)
        if parent_for_oob:
            parent = _fetch_parent_for_subtask_count_oob(request, parent_for_oob.pk)
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
            return _with_toast(HttpResponseBadRequest(message), message, error=True)
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
    response = _with_subtask_count_oob(request, response, task)
    if request.htmx:
        return response
    return _mutation_redirect(request, task_list, "Task restored")


@require_POST
def create_subtask_view(request, task_id: int):
    parent = _task_or_404(request, task_id)
    if parent.parent_id:
        raise Http404("Subtasks cannot have subtasks.")
    if parent.is_deleted:
        return _htmx_error(request, "Restore the parent task before adding subtasks.")
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
            _fetch_parent_for_subtask_count_oob(request, parent.pk),
        )
    return redirect("tasks:list_detail", list_id=parent.task_list_id)


@require_POST
def reorder_list_tasks(request, list_id: int):
    task_list = _list_or_404(request, list_id)
    try:
        services.reorder_tasks(
            task_list=task_list,
            ordered_ids=_ids_from_post(request),
            include_deleted=_show_deleted_mode(request),
        )
    except ValueError as exc:
        return _htmx_error(request, str(exc))
    return HttpResponse(status=204)


@require_POST
def reorder_subtasks(request, task_id: int):
    parent = _task_or_404(request, task_id)
    try:
        services.reorder_tasks(
            task_list=parent.task_list,
            parent=parent,
            ordered_ids=_ids_from_post(request),
            include_deleted=_show_deleted_mode(request),
        )
    except ValueError as exc:
        return _htmx_error(request, str(exc))
    return HttpResponse(status=204)


@require_POST
def set_recurrence_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    if denied := _guard_deleted_task_mutation(request, task):
        return denied
    if task.parent_id:
        return _htmx_error(request, "Subtasks cannot recur.")
    if task.spawned_from_id:
        return _htmx_error(request, "Spawned occurrences cannot have recurrence rules.")
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
    if request.htmx:
        response = _with_toast(
            render(
                request,
                "tasks/partials/_recurrence_form.html",
                {"task": task, "form": RecurrenceForm()},
            ),
            "Recurrence saved",
        )
        return _append_recurrence_badge_oob(request, response, task)
    return _mutation_redirect(request, task.task_list, "Recurrence saved")


@require_POST
def clear_recurrence_view(request, task_id: int):
    task = _task_or_404(request, task_id)
    if denied := _guard_deleted_task_mutation(request, task):
        return denied
    services.clear_recurrence(task)
    task = _task_or_404(request, task.id)
    if request.htmx:
        response = _with_toast(
            render(
                request,
                "tasks/partials/_recurrence_form.html",
                {"task": task, "form": RecurrenceForm()},
            ),
            "Recurrence cleared",
        )
        return _append_recurrence_badge_oob(request, response, task)
    return _mutation_redirect(request, task.task_list, "Recurrence cleared")


def _export(request, list_id: int, fmt: str):
    task_list = _list_or_404(request, list_id)
    params = _list_filter_params(request.GET, request=request, use_current_url=False)
    result = services.export_tasks(
        task_list,
        fmt=fmt,
        include_deleted=params["show_deleted"],
        view=params["view_filter"],
        status=params["status"] if params["status"] in TaskStatus.values else None,
        priority=(
            params["priority"] if params["priority"] in TaskPriority.values else None
        ),
        query=params["query"],
        sort=params["sort"],
    )
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
    valid_list_filter = False
    if list_id and str(list_id).isdigit():
        if _lists_for_request(request).filter(id=list_id).exists():
            events = events.filter(task_list_id=list_id)
            valid_list_filter = True

    paginator = Paginator(events, 25)
    page = paginator.get_page(request.GET.get("page"))
    filter_params = {}
    if action in TaskEventAction.values:
        filter_params["action"] = action
    if valid_list_filter:
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
