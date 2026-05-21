PYTHON ?= python

.PHONY: run test cov lint format js-test e2e migrate seed

run:
	$(PYTHON) manage.py runserver

test:
	$(PYTHON) -m pytest -m "not e2e"

cov:
	$(PYTHON) -m pytest --cov=tasks --cov-report=term-missing

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m black --check config tasks

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

