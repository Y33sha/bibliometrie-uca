"""Les étapes de la fusion de personnes couvrent toutes les données d'une personne.

Une table ajoutée avec une clé étrangère vers `persons`, ou une colonne ajoutée à `persons`, sans étape de fusion fait échouer ce test : sa donnée serait perdue à la fusion.
"""

from sqlalchemy import text

from domain.persons.merge import PERSON_DATA
from infrastructure.repositories.person_repository._merge import MERGE_STEPS


def test_one_step_per_person_data():
    assert set(MERGE_STEPS) == set(PERSON_DATA)


def test_steps_cover_schema(sa_sync_conn):
    foreign_keys = sa_sync_conn.execute(
        text("""
            SELECT c.conrelid::regclass::text, a.attname
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.contype = 'f' AND c.confrelid = 'persons'::regclass
        """)
    ).all()
    person_columns = sa_sync_conn.execute(
        text("""
            SELECT 'persons', column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'persons' AND column_name <> 'id'
        """)
    ).all()
    declared = {column for step in MERGE_STEPS.values() for column in step.columns}

    assert {tuple(r) for r in foreign_keys} | {tuple(r) for r in person_columns} == declared
