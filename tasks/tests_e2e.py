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
    page.wait_for_timeout(300)
    page.reload()
    titles = page.locator(
        "#task-list .task-group [data-task-title]"
    ).all_text_contents()
    assert titles == ["Task Beta", "Task Alpha"]


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
