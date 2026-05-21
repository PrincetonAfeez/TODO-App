from .base import *  # noqa: F403

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405

# Production requires PostgreSQL (or any DB) via DATABASE_URL, e.g.:
# postgres://USER:PASSWORD@HOST:5432/DBNAME
DATABASES = {  # noqa: F405
    "default": env.db("DATABASE_URL"),  # noqa: F405
}
