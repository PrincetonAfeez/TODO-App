"""axe-core accessibility scans for key pages."""

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _assert_no_violations(page: Page) -> None:
    page.wait_for_load_state("domcontentloaded")
    page.locator("body").wait_for(state="visible")
    results = Axe().run(page)
    assert results.violations_count == 0, results.generate_report()


def test_a11y_list_detail(page: Page, live_server):
    page.goto(f"{live_server.url}/")
    _assert_no_violations(page)


def test_a11y_lists_overview(page: Page, live_server):
    page.goto(f"{live_server.url}/lists/")
    _assert_no_violations(page)


def test_a11y_events(page: Page, live_server):
    page.goto(f"{live_server.url}/events/")
    _assert_no_violations(page)
