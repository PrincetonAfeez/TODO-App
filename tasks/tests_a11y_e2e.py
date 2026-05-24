""" axe-core accessibility scans for key pages """

import re

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _assert_no_violations(page: Page) -> None:
    page.wait_for_load_state("domcontentloaded")
    page.locator("body").wait_for(state="visible")
    results = Axe().run(page)
    assert results.violations_count == 0, results.generate_report()


def test_a11y_list_detail(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    _assert_no_violations(page)


def test_a11y_list_detail_dark_mode(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.evaluate("() => window.TodoThemeHelpers.applyTheme('dark')")
    expect(page.locator("html")).to_have_class(re.compile(r".*\bdark\b.*"))
    _assert_no_violations(page)


def test_a11y_lists_overview(page: Page, live_server):
    page.goto(f"{live_server.url}/lists/")
    _assert_no_violations(page)


def test_a11y_events(page: Page, live_server):
    page.goto(f"{live_server.url}/events/")
    _assert_no_violations(page)


def test_a11y_inline_edit_form(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.locator("#new-task-form").get_by_placeholder("New task").fill("Editable")
    page.locator("#new-task-form").get_by_role("button", name="Add").click()
    group = page.locator(".task-group").filter(has_text="Editable")
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and response.url.endswith("/edit/")
    ):
        group.get_by_role("button", name="Edit task").click()
    expect(page.locator("[data-edit-form]")).to_be_visible()
    _assert_no_violations(page)


def test_a11y_create_task_validation_error(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    form = page.locator("#new-task-form")
    form.get_by_placeholder("New task").fill("   ")
    form.get_by_role("button", name="Add").click()
    expect(form.locator("#new-task-form-errors")).to_be_visible()
    _assert_no_violations(page)


def test_a11y_keyboard_shortcuts_dialog(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    page.get_by_role("button", name="Keyboard shortcuts").click()
    dialog = page.locator("#keyboard-shortcuts-dialog")
    expect(dialog).to_be_visible()
    _assert_no_violations(page)
