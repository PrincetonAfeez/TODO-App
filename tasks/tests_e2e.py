""" End-to-end tests for the project """

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def test_smoke_create_and_toggle_task(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.get_by_placeholder("New task").fill("E2E smoke task")
    page.get_by_role("button", name="Add").click()
    expect(page.get_by_text("E2E smoke task")).to_be_visible()
    row = page.locator(".task-group").filter(has_text="E2E smoke task")
    checkbox = row.locator("[data-optimistic-toggle]")
    checkbox.check()
    expect(row.locator("[data-task-title]")).to_have_class(re.compile("line-through"))


def test_smoke_create_subtask_updates_parent_count(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.get_by_placeholder("New task").fill("Parent for subtasks")
    page.get_by_role("button", name="Add").click()
    group = page.locator(".task-group").filter(has_text="Parent for subtasks")
    group.locator('input[placeholder="Subtask"]').fill("Nested item")
    group.get_by_role("button", name="Add").nth(0).click()
    count = group.locator('[id^="subtask-count-"]')
    expect(count).to_be_visible()
    expect(count).to_contain_text("0/1")
    subtask = group.locator(".subtask-row").filter(has_text="Nested item")
    subtask.locator("[data-optimistic-toggle]").check()
    expect(count).to_contain_text("1/1")


def test_delete_last_task_shows_empty_state(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.get_by_placeholder("New task").fill("Only task")
    page.get_by_role("button", name="Add").click()
    group = page.locator(".task-group").filter(has_text="Only task")
    page.once("dialog", lambda dialog: dialog.accept())
    group.get_by_role("button", name="Delete task").click()
    expect(page.get_by_text("Nothing here yet.")).to_be_visible()
    expect(page.locator("#task-list .task-group")).to_have_count(0)


def test_recurrence_form_save_and_clear(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.get_by_placeholder("New task").fill("Recurring task")
    page.get_by_role("button", name="Add").click()
    group = page.locator(".task-group").filter(has_text="Recurring task")
    group.locator("summary").click()
    form = group.locator("[data-recurrence-form]")
    form.locator('select[name="frequency"]').select_option("daily")
    form.get_by_role("button", name="Save").click()
    expect(group.get_by_text("Every day")).to_be_visible()
    group.get_by_role("button", name="Clear").click()
    expect(group.get_by_text("Every day")).not_to_be_visible()


def test_reorder_persists_after_reload(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    form = page.locator("#new-task-form")
    for title in ("Task Alpha", "Task Beta"):
        form.get_by_placeholder("New task").fill(title)
        form.get_by_role("button", name="Add").click()
        expect(page.get_by_text(title)).to_be_visible()
    expect(page.locator("#task-list .task-group")).to_have_count(2)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/reorder/")
    ) as response_info:
        page.evaluate(
            """
            () => {
                const list = document.getElementById('task-list');
                const ids = Array.from(list.querySelectorAll('.task-group'))
                    .map((el) => el.dataset.taskId)
                    .reverse();
                return htmx.ajax('POST', list.dataset.reorderUrl, {
                    values: { order: ids },
                    swap: 'none',
                });
            }
            """
        )
    assert response_info.value.ok
    page.reload()
    titles = page.locator(
        "#task-list .task-group [data-task-title]"
    ).all_text_contents()
    assert titles == ["Task Beta", "Task Alpha"]


def test_reorder_failure_resyncs_list_order(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    form = page.locator("#new-task-form")
    for title in ("Task Alpha", "Task Beta"):
        form.get_by_placeholder("New task").fill(title)
        form.get_by_role("button", name="Add").click()
        expect(page.get_by_text(title)).to_be_visible()

    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/reorder/")
    ) as response_info:
        page.evaluate(
            """
            () => {
                const list = document.getElementById('task-list');
                const groups = Array.from(list.querySelectorAll('.task-group'));
                groups.reverse().forEach((group) => list.appendChild(group));
                const firstId = list.querySelector('.task-group').dataset.taskId;
                window.htmx.ajax('POST', list.dataset.reorderUrl, {
                    values: { order: [firstId, firstId] },
                    swap: 'none',
                });
            }
            """
        )

    assert response_info.value.status == 400
    expect(page.locator("#task-list .task-group [data-task-title]")).to_have_text(
        ["Task Alpha", "Task Beta"]
    )


def test_events_page_loads(page: Page, live_server):
    page.goto(f"{live_server.url}/events/")
    expect(page.get_by_role("heading", name="Events")).to_be_visible()


def test_restore_deleted_task_in_show_deleted_view(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.locator("#new-task-form").get_by_placeholder("New task").fill("Restore me")
    page.locator("#new-task-form").get_by_role("button", name="Add").click()
    group = page.locator(".task-group").filter(has_text="Restore me")
    page.once("dialog", lambda dialog: dialog.accept())
    group.get_by_role("button", name="Delete task").click()
    page.get_by_label("Show deleted").check()
    deleted_group = page.locator(".task-group").filter(has_text="Restore me")
    expect(deleted_group.get_by_role("button", name="Restore")).to_be_visible()
    deleted_group.get_by_role("button", name="Restore").click()
    expect(deleted_group.locator("[data-task-title]")).to_be_visible()


def test_new_task_form_clears_after_add(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    form = page.locator("#new-task-form")
    form.get_by_placeholder("New task").fill("One off")
    form.locator("summary").click()
    form.locator('textarea[name="notes"]').fill("Some notes")
    form.get_by_role("button", name="Add").click()
    expect(page.get_by_text("One off")).to_be_visible()
    expect(form.get_by_placeholder("New task")).to_have_value("")
    expect(form.locator('textarea[name="notes"]')).to_have_value("")
    expect(form.locator("[data-new-task-details]")).to_have_js_property("open", False)


def test_keyboard_shortcuts_dialog_opens(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    dialog = page.locator("#keyboard-shortcuts-dialog")
    expect(dialog).not_to_be_visible()
    page.get_by_role("button", name="Keyboard shortcuts").click()
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("heading", name="Keyboard shortcuts")).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()


def test_create_task_shows_inline_validation(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    form = page.locator("#new-task-form")
    form.get_by_placeholder("New task").fill("   ")
    form.get_by_role("button", name="Add").click()
    expect(form.locator("#new-task-form-errors")).to_be_visible()
    expect(page.locator("#task-list .task-group")).to_have_count(0)


def test_inline_edit_task_title(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.locator("#new-task-form").get_by_placeholder("New task").fill("Editable")
    page.locator("#new-task-form").get_by_role("button", name="Add").click()
    group = page.locator(".task-group").filter(has_text="Editable")
    group_id = group.get_attribute("id")
    group.get_by_role("button", name="Edit task").click()
    edit_group = page.locator(f"#{group_id}")
    title_input = edit_group.locator('form.task-row input[name="title"]')
    expect(title_input).to_be_visible()
    title_input.fill("Edited title")
    edit_group.get_by_role("button", name="Save").click()
    expect(edit_group.locator("[data-task-title]")).to_have_text("Edited title")


def test_delete_in_show_deleted_keeps_deleted_badge(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.locator("#new-task-form").get_by_placeholder("New task").fill("Soft delete me")
    page.locator("#new-task-form").get_by_role("button", name="Add").click()
    group = page.locator(".task-group").filter(has_text="Soft delete me")
    page.get_by_label("Show deleted").check()
    page.once("dialog", lambda dialog: dialog.accept())
    group.get_by_role("button", name="Delete task").click()
    expect(group.get_by_text("Deleted")).to_be_visible()
    expect(group.locator("[data-task-title]")).to_have_text("Soft delete me")


def test_create_task_respects_active_priority_filter(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    form = page.locator("#new-task-form")

    def add_task(title: str, priority: str):
        form.get_by_placeholder("New task").fill(title)
        page.evaluate(
            """([priority]) => {
                const select = document.querySelector(
                    '#new-task-form select[name="priority"]'
                );
                select.value = priority;
            }""",
            [priority],
        )
        form.get_by_role("button", name="Add").click()
        expect(page.locator("#task-list").get_by_text(title)).to_be_visible()

    add_task("High task", "high")
    add_task("Low task", "low")
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and "/lists/" in response.url
        and "priority=high" in response.url
    ):
        page.locator('#task-filters-form select[name="priority"]').select_option("high")
    expect(page.locator("#task-list .task-group")).to_have_count(1)
    expect(page.get_by_text("High task")).to_be_visible()
    expect(page.get_by_text("Low task")).not_to_be_visible()

    form.get_by_placeholder("New task").fill("Another low")
    page.evaluate(
        """() => {
            const select = document.querySelector(
                '#new-task-form select[name="priority"]'
            );
            select.value = 'low';
        }"""
    )
    form.get_by_role("button", name="Add").click()
    expect(page.locator("#task-list .task-group")).to_have_count(1)
    expect(page.locator("#task-list")).not_to_contain_text("Another low")
    expect(page.locator("#task-list")).to_contain_text("High task")


def test_sort_filter_shows_reorder_disabled_banner(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.locator("#new-task-form").get_by_placeholder("New task").fill(
        "Sort filter task"
    )
    page.locator("#new-task-form").get_by_role("button", name="Add").click()
    page.locator('#task-filters-form select[name="sort"]').select_option("due_date")
    expect(page.get_by_text("Drag-and-drop reordering is disabled")).to_be_visible()


def test_reorder_in_show_deleted_view(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    form = page.locator("#new-task-form")
    for title in ("Active task", "Deleted task"):
        form.get_by_placeholder("New task").fill(title)
        form.get_by_role("button", name="Add").click()
        expect(page.get_by_text(title)).to_be_visible()
    deleted_group = page.locator(".task-group").filter(has_text="Deleted task")
    page.once("dialog", lambda dialog: dialog.accept())
    deleted_group.get_by_role("button", name="Delete task").click()
    page.get_by_label("Show deleted").check()
    expect(page.locator("#task-list")).to_have_attribute("data-sortable-list", "")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/reorder/")
    ) as response_info:
        page.evaluate(
            """
            () => {
                const list = document.getElementById('task-list');
                const ids = Array.from(list.querySelectorAll('.task-group'))
                    .map((el) => el.dataset.taskId)
                    .reverse();
                return htmx.ajax('POST', list.dataset.reorderUrl, {
                    values: { order: ids },
                    swap: 'none',
                });
            }
            """
        )
    assert response_info.value.ok
    page.reload()
    titles = page.locator(
        "#task-list .task-group [data-task-title]"
    ).all_text_contents()
    assert titles == ["Deleted task", "Active task"]


def test_subtask_form_clears_after_add(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.locator("#new-task-form").get_by_placeholder("New task").fill("Parent task")
    page.locator("#new-task-form").get_by_role("button", name="Add").click()
    group = page.locator(".task-group").filter(has_text="Parent task")
    subtask_input = group.locator('input[placeholder="Subtask"]')
    subtask_input.fill("Child task")
    group.get_by_role("button", name="Add").nth(0).click()
    expect(group.locator(".subtask-row").filter(has_text="Child task")).to_be_visible()
    expect(subtask_input).to_have_value("")


def test_recurring_task_spawns_occurrence_on_complete(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    form = page.locator("#new-task-form")
    form.get_by_placeholder("New task").fill("Daily template")
    form.locator("summary").click()
    due_input = form.locator('input[name="due_date"]')
    due_input.fill("2030-06-01T09:00")
    form.get_by_role("button", name="Add").click()
    group = page.locator(".task-group").filter(has_text="Daily template")
    group.locator("summary").click()
    group.locator('[data-recurrence-form] select[name="frequency"]').select_option(
        "daily"
    )
    group.locator("[data-recurrence-form]").get_by_role("button", name="Save").click()
    expect(group.get_by_text("Every day")).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/toggle/")
    ):
        group.locator("[data-optimistic-toggle]").check()
    groups = page.locator(".task-group").filter(has_text="Daily template")
    expect(groups).to_have_count(2)
    expect(groups.nth(1).get_by_text("Spawned")).to_be_visible()
