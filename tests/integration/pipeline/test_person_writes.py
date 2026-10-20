"""Tests d'intégration des écritures de la phase `persons` (`pipeline/transformation/persons/person_writes.py`)."""

from functools import partial

import pytest
from sqlalchemy import text

from domain.errors import ValidationError
from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.transformation.persons.cascade import link_contribution
from pipeline.transformation.persons.person_writes import (
    add_identifiers_from_contributions,
)
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

# Personne « Dupont Jean » par défaut, normalisée par `lower`.
_person = partial(insert_person, last_name="Dupont", first_name="Jean", normalizer="lower")

# Contribution source de forme « jean dupont » par défaut.
_jean_dupont_source_contribution = partial(
    insert_source_contribution, author_name_normalized="jean dupont"
)

# Enregistrement source de titre « Test », d'identifiant « hal-1 » par défaut.
_source_record = partial(insert_source_record, source_id="hal-1", title="Test")


@pytest.fixture
def repo(sa_sync_conn):
    return PgPersonRepository(sa_sync_conn)


def _scalar(conn, sql_text: str, **params):
    return conn.execute(text(sql_text), params).scalar_one_or_none()


class TestLinkContribution:
    def test_rejects_unknown_source(self, sa_sync_conn, repo):
        """Source hors registre → `ValidationError` (mappée en 400 côté API)."""
        with pytest.raises(ValidationError):
            link_contribution(sa_sync_conn, 1, "invalid", 1, "name")

    def test_sets_person_id_on_source_contribution(self, sa_sync_conn, repo):
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        source_contribution_id = _jean_dupont_source_contribution(sa_sync_conn, source_record_id)

        link_contribution(sa_sync_conn, person_id, "hal", source_contribution_id, "name")

        assert (
            _scalar(
                sa_sync_conn,
                "SELECT person_id FROM source_contributions WHERE id = :i",
                i=source_contribution_id,
            )
            == person_id
        )
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT resolution_mode FROM source_contributions WHERE id = :i",
                i=source_contribution_id,
            )
            == "name"
        )


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
        """Un identifiant source mal formé est ignoré (log, pas d'exception) ; la
        promotion continue pour les identifiants valides du même lot."""
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
