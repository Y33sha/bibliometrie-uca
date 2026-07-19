"""Régression : la facette « À confirmer › Identifiants » n'écoute que les types publics.

Un `hal_person_id` en attente est interne (jamais présenté à l'arbitrage) : il ne doit
faire remonter la personne ni dans le compteur de la facette, ni dans la liste filtrée."""

from sqlalchemy import text

from application.ports.api.persons_queries import FacetFilters, ListFilters
from infrastructure.queries.api.persons.facets import persons_facets
from infrastructure.queries.api.persons.list import list_persons


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


def _person_ids(result):
    return {p["id"] for p in result["persons"]}


class TestPendingIdentifiersFacetPublicOnly:
    def test_hal_person_id_pending_excluded(self, sa_sync_conn):
        """Seul un `hal_person_id` en attente : hors facette et hors liste filtrée."""
        internal_only = _create_person(sa_sync_conn, last="Internal")
        _add_identifier(sa_sync_conn, internal_only, "hal_person_id", "12345", "pending")

        public_pending = _create_person(sa_sync_conn, last="Public")
        _add_identifier(sa_sync_conn, public_pending, "orcid", "0000-0001-2345-6789", "pending")

        listed = _person_ids(
            list_persons(
                sa_sync_conn,
                filters=ListFilters(has_pending_identifiers=True),
                page=1,
                per_page=1000,
                sort="name_asc",
            )
        )
        assert public_pending in listed
        assert internal_only not in listed

    def test_facet_count_ignores_hal_person_id(self, sa_sync_conn):
        """Le compteur `pending_identifiers.yes` ne compte que les types publics."""
        internal_only = _create_person(sa_sync_conn, last="InternalCount")
        _add_identifier(sa_sync_conn, internal_only, "hal_person_id", "67890", "pending")

        before = persons_facets(sa_sync_conn, filters=FacetFilters())["pending_identifiers"]["yes"]

        public_pending = _create_person(sa_sync_conn, last="PublicCount")
        _add_identifier(sa_sync_conn, public_pending, "idref", "123456789", "pending")

        after = persons_facets(sa_sync_conn, filters=FacetFilters())["pending_identifiers"]["yes"]
        # +1 pour la personne à identifiant public pending, +0 pour le hal_person_id interne.
        assert after == before + 1

    def test_public_confirmed_or_rejected_not_pending(self, sa_sync_conn):
        """Une personne dont les identifiants publics sont tous tranchés n'est pas à confirmer,
        même si elle porte par ailleurs un `hal_person_id` en attente."""
        person = _create_person(sa_sync_conn, last="Settled")
        _add_identifier(sa_sync_conn, person, "orcid", "0000-0002-1111-2222", "confirmed")
        _add_identifier(sa_sync_conn, person, "idref", "987654321", "rejected")
        _add_identifier(sa_sync_conn, person, "hal_person_id", "55555", "pending")

        listed = _person_ids(
            list_persons(
                sa_sync_conn,
                filters=ListFilters(has_pending_identifiers=True),
                page=1,
                per_page=1000,
                sort="name_asc",
            )
        )
        assert person not in listed
