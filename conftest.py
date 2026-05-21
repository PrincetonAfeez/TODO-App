""" pytest configuration for To-Do app """

import os

import pytest

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

pytest_plugins = ("pytest_playwright",)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "e2e: browser integration tests (Playwright)"
    )


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
    }
