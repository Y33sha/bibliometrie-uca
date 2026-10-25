"""Les étapes de fusion d'une entité couvrent toutes ses données, et la fusion redirige l'identifiant absorbé.

Une table ajoutée avec une clé étrangère vers l'entité, ou une colonne ajoutée à sa table, sans étape de fusion fait échouer ce test : sa donnée serait perdue à la fusion.
"""

import pytest
from sqlalchemy import text

from domain.merge import MergedEntity
from infrastructure.repositories import publisher_merge
from infrastructure.repositories.merge_steps import record_redirect
from infrastructure.repositories.person_repository import _merge as person_merge
from pipeline.transformation.publishing.monographs import monograph_merge
from pipeline.transformation.publishing.serials import serial_merge
from tests.integration.helpers.redirects import redirect_of

_ENTITIES = [
    pytest.param("persons", person_merge.MERGE_STEPS, id="persons"),
    pytest.param("serials", serial_merge.MERGE_STEPS, id="serials"),
    pytest.param("publishers", publisher_merge.MERGE_STEPS, id="publishers"),
    pytest.param("monographs", monograph_merge.MERGE_STEPS, id="monographs"),
]


@pytest.mark.parametrize(("table", "steps"), _ENTITIES)
def test_steps_cover_schema(sa_sync_conn, table, steps):
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
            WHERE table_schema::text = (
                SELECT relnamespace::regnamespace::text FROM pg_class
                WHERE oid = CAST(:table AS regclass)
            )
              AND table_name::text = CAST(:table AS text) AND column_name <> 'id'
        """),
        {"table": table},
    ).all()
    declared = {column for step in steps.values() for column in step.columns}

    assert {tuple(r) for r in foreign_keys} | {tuple(r) for r in entity_columns} == declared


def test_chained_redirect_leads_to_last_kept(sa_sync_conn):
    """A absorbé par B, puis B par C : A et B mènent à C. Le même identifiant d'une autre entité garde sa redirection."""
    a, b, c = 900001, 900002, 900003
    record_redirect(sa_sync_conn, MergedEntity.SERIAL, b, a)
    record_redirect(sa_sync_conn, MergedEntity.PUBLISHER, b, a)
    record_redirect(sa_sync_conn, MergedEntity.SERIAL, c, b)

    assert redirect_of(sa_sync_conn, MergedEntity.SERIAL, a) == c
    assert redirect_of(sa_sync_conn, MergedEntity.SERIAL, b) == c
    assert redirect_of(sa_sync_conn, MergedEntity.PUBLISHER, a) == b
