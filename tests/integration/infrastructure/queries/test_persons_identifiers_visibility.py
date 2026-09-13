"""Visibilité des identifiants de personne.

L'administration voit et arbitre tous les types, `hal_person_id` compris. Le profil public rend seulement les types publics non rejetés."""

from sqlalchemy import text

from application.ports.read_models.persons_queries import PersonFilters
from infrastructure.read_models.persons.detail import person_profile
from infrastructure.read_models.persons.facets import persons_facets
from infrastructure.read_models.persons.list import list_persons, person_curation


def _create_person(conn, last, first="Z"):
    return (
        conn.execute(
            text(
                "INSERT INTO persons "
                "(last_name, first_name, last_name_normalized, first_name_normalized) "
                "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
            ),
            {"l": last, "f": first},
        )
        .one()
        .id
    )


def _add_identifier(conn, person_id, id_type, id_value, status):
    conn.execute(
        text(
            "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
            "VALUES (:pid, :t, :v, 'auto', CAST(:s AS identifier_status))"
        ),
        {"pid": person_id, "t": id_type, "v": id_value, "s": status},
    )


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
        person = _create_person(sa_sync_conn, last="Administered")
        _add_identifier(sa_sync_conn, person, "hal_person_id", "12345", "pending")

        out = person_curation(sa_sync_conn, person)

        assert [(i.id_type, i.id_value, i.status) for i in out.identifiers] == [
            ("hal_person_id", "12345", "pending")
        ]

    def test_public_profile_hides_hal_person_id(self, sa_sync_conn):
        """Le profil public écarte le `hal_person_id` et les attributions rejetées."""
        person = _create_person(sa_sync_conn, last="Profiled")
        _add_identifier(sa_sync_conn, person, "hal_person_id", "12345", "confirmed")
        _add_identifier(sa_sync_conn, person, "orcid", "0000-0001-2345-6789", "pending")
        _add_identifier(sa_sync_conn, person, "idref", "123456789", "rejected")

        profile = person_profile(sa_sync_conn, person)

        assert [i.id_type for i in profile.identifiers] == ["orcid"]


class TestPendingIdentifiersQueue:
    def test_pending_hal_person_id_is_listed(self, sa_sync_conn):
        """Un `hal_person_id` en attente fait remonter la personne dans la file « à confirmer »."""
        person = _create_person(sa_sync_conn, last="HalOnly")
        _add_identifier(sa_sync_conn, person, "hal_person_id", "12345", "pending")

        assert person in _pending_identifier_person_ids(sa_sync_conn)

    def test_facet_counts_pending_hal_person_id(self, sa_sync_conn):
        """Le compteur `pending_identifiers.yes` compte un `hal_person_id` en attente."""
        before = persons_facets(sa_sync_conn, filters=PersonFilters()).pending_identifiers.yes

        person = _create_person(sa_sync_conn, last="HalCount")
        _add_identifier(sa_sync_conn, person, "hal_person_id", "67890", "pending")

        after = persons_facets(sa_sync_conn, filters=PersonFilters()).pending_identifiers.yes
        assert after == before + 1

    def test_settled_identifiers_not_pending(self, sa_sync_conn):
        """Une personne dont les identifiants sont tous tranchés est absente de la file « à confirmer »."""
        person = _create_person(sa_sync_conn, last="Settled")
        _add_identifier(sa_sync_conn, person, "orcid", "0000-0002-1111-2222", "confirmed")
        _add_identifier(sa_sync_conn, person, "idref", "987654321", "rejected")
        _add_identifier(sa_sync_conn, person, "hal_person_id", "55555", "confirmed")

        assert person not in _pending_identifier_person_ids(sa_sync_conn)
