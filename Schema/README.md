# TODO-App Schema

This folder contains a simple database schema reference for the Django TODO app.
It mirrors the current `tasks.models` structure: task lists, tasks, recurrence
rules, and task audit events.

## Files

- `model-summary.md` — quick reference for models, relationships, field choices, and indexes.
- `er-diagram.mmd` — Mermaid ER diagram you can paste into GitHub Markdown or Mermaid Live Editor.
- `schema.postgres.sql` — PostgreSQL-oriented SQL schema for production-style deployments.
- `schema.dbml` — DBML version for dbdiagram.io or similar diagramming tools.

## Notes

The app uses SQLite for local development and PostgreSQL in production. The SQL
file is intended as documentation/reference, not a replacement for Django
migrations. Continue using `python manage.py makemigrations` and
`python manage.py migrate` as the source of truth for database changes.
