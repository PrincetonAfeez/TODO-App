""" Guard against drift between Schema/ reference files and Django models """

from __future__ import annotations

from pathlib import Path

import pytest
from django.db import models

from tasks.models import Recurrence, Task, TaskEvent, TaskList

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = REPO_ROOT / "Schema" / "schema.postgres.sql"
SCHEMA_DBML = REPO_ROOT / "Schema" / "schema.dbml"


def _index_field_sets(meta: models.options.Options) -> set[tuple[str, ...]]:
    fields: set[tuple[str, ...]] = set()
    for index in meta.indexes:
        fields.add(tuple(index.fields))
    for field in meta.get_fields():
        if getattr(field, "db_index", False) and getattr(field, "column", None):
            fields.add((field.column,))
    return fields


def _meta_index_field_sets(meta: models.options.Options) -> set[tuple[str, ...]]:
    return {tuple(index.fields) for index in meta.indexes}


@pytest.mark.django_db
def test_tasklist_matches_reference_schema():
    meta = TaskList._meta
    assert meta.db_table == "tasks_tasklist"
    assert {f.name for f in meta.get_fields() if f.concrete and not f.many_to_many} == {
        "id",
        "name",
        "session_key",
        "created_at",
        "updated_at",
    }
    assert any(
        constraint.name == "unique_task_list_name_per_session"
        for constraint in meta.constraints
    )


@pytest.mark.django_db
def test_task_indexes_and_constraints_match_reference_schema():
    meta = Task._meta
    assert meta.db_table == "tasks_task"
    index_fields = _index_field_sets(meta)
    assert ("task_list_id",) in index_fields
    assert ("parent_id",) in index_fields
    assert ("status",) in index_fields
    assert ("due_date",) in index_fields
    assert ("deleted_at",) in index_fields
    assert ("task_list", "parent", "order") in _meta_index_field_sets(meta)
    constraint_names = {constraint.name for constraint in meta.constraints}
    assert constraint_names == {"task_status_valid", "task_priority_valid"}


@pytest.mark.django_db
def test_recurrence_has_no_db_constraints_or_indexes():
    meta = Recurrence._meta
    assert meta.db_table == "tasks_recurrence"
    assert meta.indexes == []
    assert meta.constraints == []


@pytest.mark.django_db
def test_taskevent_indexes_match_reference_schema():
    meta = TaskEvent._meta
    assert meta.db_table == "tasks_taskevent"
    index_fields = _index_field_sets(meta)
    assert ("session_key",) in index_fields
    assert ("created_at",) in index_fields
    assert ("task_id",) in index_fields
    assert ("task_list_id",) in index_fields
    assert meta.constraints == []


def test_schema_postgres_sql_matches_model_capabilities():
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "unique_task_list_name_per_session" in sql
    assert "task_status_valid" in sql
    assert "task_priority_valid" in sql
    assert "tasks_taskevent_task_id_idx" in sql
    assert "tasks_taskevent_task_list_id_idx" in sql
    assert "tasks_recurrence_created_at_idx" not in sql
    assert 'CHECK ("order" >= 0)' not in sql
    assert "recurrence_frequency_valid" not in sql
    assert "task_event_action_valid" not in sql


def test_schema_dbml_documents_taskevent_fk_indexes():
    dbml = SCHEMA_DBML.read_text(encoding="utf-8")
    taskevent_block = dbml.split("Table tasks_taskevent", 1)[1].split("Table ", 1)[0]
    indexes_block = taskevent_block.split("indexes", 1)[1]
    assert "task_id" in indexes_block
    assert "task_list_id" in indexes_block
