# TODO-App Schema

This folder contains a database schema reference for the Django TODO app.
It mirrors `tasks/migrations/0001_initial.py` — not every Python validation rule
is duplicated as a SQL CHECK constraint.

## Files

- `model-summary.md` — quick reference for models, relationships, field choices, and indexes.
- `er-diagram.mmd` — Mermaid ER diagram you can paste into GitHub Markdown or Mermaid Live Editor.
- `schema.postgres.sql` — PostgreSQL-oriented SQL schema for production-style deployments.
- `schema.dbml` — DBML version for dbdiagram.io or similar diagramming tools.

## Keeping docs aligned

1. Change models and run `makemigrations` / `migrate` first.
2. Update the files in this folder to match the migration.
3. Run `python -m pytest tasks/test_schema_reference.py` — it fails if reference
   SQL/DBML document indexes or constraints Django does not create.

See also `docs/edge-cases.md` for behavioral invariants that are not visible in
the ER diagram alone, and `docs/START_HERE.md` for the evaluator quick path.

## Notes

The app uses SQLite for local development and PostgreSQL in production. The SQL
file is documentation/reference, not a replacement for Django migrations.
