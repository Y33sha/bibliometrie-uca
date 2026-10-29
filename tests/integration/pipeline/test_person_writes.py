"""Écritures de la phase `persons` (`pipeline/transformation/persons/person_writes.py`)."""

from functools import partial

import pytest
from sqlalchemy import text

from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.transformation.persons.person_writes import (
    add_identifiers_from_contributions,
)
from tests.integration.helpers.persons import insert_person

# Personne « Dupont Jean » par défaut, normalisée par `lower`.
_person = partial(insert_person, last_name="Dupont", first_name="Jean", normalizer="lower")


@pytest.fixture
def repo(sa_sync_conn):
    return PgPersonRepository(sa_sync_conn)


class TestAddIdentifiersFromContributions:
    def test_adds_orcid_idhal_idref_once(self, sa_sync_conn, repo):
        person_id = _person(sa_sync_conn)
        contributions = [
            {"source": "hal", "orcid": "0000-0001-2345-6789", "idhal": "jdupont"},
            {"source": "scanr", "orcid": "0000-0001-2345-6789", "idref": "252404955"},
        ]
        add_identifiers_from_contributions(person_id, contributions, repo=repo)

        rows = sa_sync_conn.execute(
            text(
                "SELECT id_type, id_value, source FROM person_identifiers "
                "WHERE person_id = :pid ORDER BY id_type"
            ),
            {"pid": person_id},
        ).all()
        id_types = [r.id_type for r in rows]
        assert id_types == ["idhal", "idref", "orcid"]

    def test_skips_malformed_and_keeps_valid(self, sa_sync_conn, repo):
        """Un identifiant mal formé est journalisé et ignoré, sans exception ; les identifiants valides du même lot sont ajoutés à la personne."""
        person_id = _person(sa_sync_conn)
        contributions = [
            {"source": "hal", "orcid": "pas-un-orcid", "idhal": "jdupont"},
        ]
        add_identifiers_from_contributions(person_id, contributions, repo=repo)

        rows = sa_sync_conn.execute(
            text("SELECT id_type FROM person_identifiers WHERE person_id = :pid ORDER BY id_type"),
            {"pid": person_id},
        ).all()
        assert [r.id_type for r in rows] == ["idhal"]
