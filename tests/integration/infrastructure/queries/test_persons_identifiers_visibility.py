"""Visibilité des identifiants de personne.

L'administration voit et arbitre tous les types, `hal_person_id` compris. Le profil public rend seulement les types publics non rejetés."""

from infrastructure.read_models.persons.detail import person_profile
from infrastructure.read_models.persons.facets import persons_facets
from infrastructure.read_models.persons.list import list_persons, person_curation
from infrastructure.read_models.persons.models import PersonFilters
from tests.integration.helpers.persons import insert_person, insert_person_identifier


def _pending_identifier_person_ids(conn):
    result = list_persons(
        conn,
        filters=PersonFilters(has_pending_identifiers=True),
        page=1,
        per_page=1000,
        sort="name_asc",
    )
    return {p.id for p in result.persons}


class TestHalPersonIdVisibility:
    def test_administration_reads_hal_person_id(self, sa_sync_conn):
        """La lecture d'administration rend le `hal_person_id` avec son statut."""
        person = insert_person(sa_sync_conn, "Administered")
        insert_person_identifier(
            sa_sync_conn, person, id_type="hal_person_id", id_value="12345", status="pending"
        )

        out = person_curation(sa_sync_conn, person)

        assert [(i.id_type, i.id_value, i.status) for i in out.identifiers] == [
            ("hal_person_id", "12345", "pending")
        ]

    def test_public_profile_hides_hal_person_id(self, sa_sync_conn):
        """Le profil public écarte le `hal_person_id` et les attributions rejetées."""
        person = insert_person(sa_sync_conn, "Profiled")
        insert_person_identifier(
            sa_sync_conn, person, id_type="hal_person_id", id_value="12345", status="confirmed"
        )
        insert_person_identifier(
            sa_sync_conn, person, id_type="orcid", id_value="0000-0001-2345-6789", status="pending"
        )
        insert_person_identifier(
            sa_sync_conn, person, id_type="idref", id_value="123456789", status="rejected"
        )

        profile = person_profile(sa_sync_conn, person)

        assert [i.id_type for i in profile.identifiers] == ["orcid"]


class TestPendingIdentifiersQueue:
    def test_pending_hal_person_id_is_listed(self, sa_sync_conn):
        """Un `hal_person_id` en attente fait remonter la personne dans la file « à confirmer »."""
        person = insert_person(sa_sync_conn, "HalOnly")
        insert_person_identifier(
            sa_sync_conn, person, id_type="hal_person_id", id_value="12345", status="pending"
        )

        assert person in _pending_identifier_person_ids(sa_sync_conn)

    def test_facet_counts_pending_hal_person_id(self, sa_sync_conn):
        """Le compteur `pending_identifiers.yes` compte un `hal_person_id` en attente."""
        before = persons_facets(sa_sync_conn, filters=PersonFilters()).pending_identifiers.yes

        person = insert_person(sa_sync_conn, "HalCount")
        insert_person_identifier(
            sa_sync_conn, person, id_type="hal_person_id", id_value="67890", status="pending"
        )

        after = persons_facets(sa_sync_conn, filters=PersonFilters()).pending_identifiers.yes
        assert after == before + 1

    def test_settled_identifiers_not_pending(self, sa_sync_conn):
        """Une personne dont les identifiants sont tous tranchés est absente de la file « à confirmer »."""
        person = insert_person(sa_sync_conn, "Settled")
        insert_person_identifier(
            sa_sync_conn,
            person,
            id_type="orcid",
            id_value="0000-0002-1111-2222",
            status="confirmed",
        )
        insert_person_identifier(
            sa_sync_conn, person, id_type="idref", id_value="987654321", status="rejected"
        )
        insert_person_identifier(
            sa_sync_conn, person, id_type="hal_person_id", id_value="55555", status="confirmed"
        )

        assert person not in _pending_identifier_person_ids(sa_sync_conn)
