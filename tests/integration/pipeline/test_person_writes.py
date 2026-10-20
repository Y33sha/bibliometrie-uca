"""Tests d'intégration des écritures de la phase `persons` (`pipeline/transformation/persons/person_writes.py`)."""

from functools import partial

import pytest
from sqlalchemy import text

from domain.errors import ValidationError
from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.transformation.persons.cascade import link_authorship
from pipeline.transformation.persons.person_writes import (
    add_identifiers_from_authorships,
)
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication

# Personne « Dupont Jean » par défaut, normalisée par `lower`.
_person = partial(insert_person, last_name="Dupont", first_name="Jean", normalizer="lower")

# Signature de forme « jean dupont » par défaut.
_jean_dupont_signature = partial(insert_signature, author_name_normalized="jean dupont")

# Notice de titre « Test », d'identifiant « hal-1 » par défaut.
_notice = partial(insert_source_publication, source_id="hal-1", title="Test")


@pytest.fixture
def repo(sa_sync_conn):
    return PgPersonRepository(sa_sync_conn)


def _scalar(conn, sql_text: str, **params):
    return conn.execute(text(sql_text), params).scalar_one_or_none()


class TestLinkAuthorship:
    def test_rejects_unknown_source(self, sa_sync_conn, repo):
        """Source hors registre → `ValidationError` (mappée en 400 côté API)."""
        with pytest.raises(ValidationError):
            link_authorship(sa_sync_conn, 1, "invalid", 1, "name")

    def test_sets_person_id_on_source_authorship(self, sa_sync_conn, repo):
        person_id = _person(sa_sync_conn)
        pub_id = insert_publication(sa_sync_conn)
        sp_id = _notice(sa_sync_conn, pub_id)
        sa_id = _jean_dupont_signature(sa_sync_conn, sp_id)

        link_authorship(sa_sync_conn, person_id, "hal", sa_id, "name")

        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id)
            == person_id
        )
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT resolution_mode FROM source_authorships WHERE id = :i",
                i=sa_id,
            )
            == "name"
        )


class TestAddIdentifiersFromAuthorships:
    def test_adds_orcid_idhal_idref_once(self, sa_sync_conn, repo):
        person_id = _person(sa_sync_conn)
        authorships = [
            {"source": "hal", "orcid": "0000-0001-2345-6789", "idhal": "jdupont"},
            {"source": "scanr", "orcid": "0000-0001-2345-6789", "idref": "252404955"},
        ]
        add_identifiers_from_authorships(person_id, authorships, repo=repo)

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
        authorships = [
            {"source": "hal", "orcid": "pas-un-orcid", "idhal": "jdupont"},
        ]
        add_identifiers_from_authorships(person_id, authorships, repo=repo)

        rows = sa_sync_conn.execute(
            text("SELECT id_type FROM person_identifiers WHERE person_id = :pid ORDER BY id_type"),
            {"pid": person_id},
        ).all()
        assert [r.id_type for r in rows] == ["idhal"]
