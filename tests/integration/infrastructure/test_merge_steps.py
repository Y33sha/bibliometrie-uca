"""Les étapes de fusion d'une entité couvrent toutes ses données.

Une table ajoutée avec une clé étrangère vers l'entité, ou une colonne ajoutée à sa table, sans étape de fusion fait échouer ce test : sa donnée serait perdue à la fusion.
"""

import pytest
from sqlalchemy import text

from domain.journals.merge import JOURNAL_DATA
from domain.persons.merge import PERSON_DATA
from infrastructure.repositories import journal_merge
from infrastructure.repositories.person_repository import _merge as person_merge

_ENTITIES = [
    pytest.param("persons", PERSON_DATA, person_merge.MERGE_STEPS, id="persons"),
    pytest.param("journals", JOURNAL_DATA, journal_merge.MERGE_STEPS, id="journals"),
]


@pytest.mark.parametrize(("table", "data", "steps"), _ENTITIES)
def test_one_step_per_data(table, data, steps):
    assert set(steps) == set(data)


@pytest.mark.parametrize(("table", "data", "steps"), _ENTITIES)
def test_steps_cover_schema(sa_sync_conn, table, data, steps):
    foreign_keys = sa_sync_conn.execute(
        text("""
            SELECT c.conrelid::regclass::text, a.attname
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.contype = 'f' AND c.confrelid = CAST(:table AS regclass)
        """),
        {"table": table},
    ).all()
    entity_columns = sa_sync_conn.execute(
        text("""
            SELECT table_name::text, column_name::text FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = :table AND column_name <> 'id'
        """),
        {"table": table},
    ).all()
    declared = {column for step in steps.values() for column in step.columns}

    assert {tuple(r) for r in foreign_keys} | {tuple(r) for r in entity_columns} == declared
