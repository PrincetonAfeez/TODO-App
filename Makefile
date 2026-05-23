PYTHON ?= python

.PHONY: run test cov lint format js-test e2e migrate seed typecheck

run:
	$(PYTHON) manage.py runserver

test:
	$(PYTHON) -m pytest -m "not e2e"

cov:
	$(PYTHON) -m pytest -m "not e2e" --cov=tasks --cov-report=term-missing --cov-fail-under=90

typecheck:
	$(PYTHON) -m mypy tasks/services.py tasks/models.py

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m black --check config tasks
	$(PYTHON) -m mypy tasks/services.py tasks/models.py

js-test:
	node --test static/tasks/toggle-helpers.test.js static/tasks/theme-helpers.test.js

e2e:
	$(PYTHON) -m playwright install chromium
	$(PYTHON) -m pytest tasks/tests_e2e.py -m e2e

format:
	$(PYTHON) -m black config tasks

migrate:
	$(PYTHON) manage.py migrate

seed:
	$(PYTHON) manage.py seed

