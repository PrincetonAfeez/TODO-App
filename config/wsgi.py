""" WSGI configuration for the project """

import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[1]
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

# Defaults to dev for local runserver; production hosts should set
# DJANGO_SETTINGS_MODULE=config.settings.prod in .env or the process env.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
