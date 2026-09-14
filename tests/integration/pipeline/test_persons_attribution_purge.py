"""Purge des attributions d'identifiant automatiques qu'aucune signature de leur personne ne porte."""

import json

from sqlalchemy import text

from infrastructure.pipeline.persons.matching import PgPersonsMatchingQueries
from tests.integration.helpers.authorships import upsert_identity

_ORCID = "0000-0001-2345-6789"


def _person(conn, last):
    return conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (:l, 'Jean', lower(:l), 'jean') RETURNING id"
        ),
        {"l": last},
    ).scalar_one()


def _attribution(conn, person_id, *, status="pending", source="auto"):
    conn.execute(
        text(
            "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
            "VALUES (:pid, 'orcid', :v, :src, CAST(:st AS identifier_status))"
        ),
        {"pid": person_id, "v": _ORCID, "src": source, "st": status},
    )


def _signature(conn, person_id, name, *, neutralized=None):
    pub = conn.execute(
        text("INSERT INTO publications (title, pub_year) VALUES ('t', 2024) RETURNING id")
    ).scalar_one()
    sp = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES ('hal', :sid, 't', :p) RETURNING id"
        ),
        {"sid": f"hal-{pub}", "p": pub},
    ).scalar_one()
    identity = upsert_identity(conn, name, {"orcid": _ORCID})
    conn.execute(
        text(
            "INSERT INTO source_authorships (source, source_publication_id, author_position, "
            "person_id, in_perimeter, raw_author_name, identity_id, resolution_mode, "
            "neutralized_identifiers) "
            "VALUES ('hal', :sp, 0, :pid, TRUE, :raw, :iid, 'name', CAST(:neu AS jsonb))"
        ),
        {
            "sp": sp,
            "pid": person_id,
            "raw": name,
            "iid": identity,
            "neu": json.dumps(neutralized) if neutralized else None,
        },
    )


def _attribution_remaining(conn, person_id):
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM person_identifiers WHERE person_id = :pid)"),
        {"pid": person_id},
    ).scalar_one()


def test_attribution_automatique_sans_signature_supprimee(sa_sync_conn):
    person = _person(sa_sync_conn, "Monteil")
    _attribution(sa_sync_conn, person)
    assert PgPersonsMatchingQueries().delete_unsupported_identifier_attributions(sa_sync_conn) >= 1
    assert not _attribution_remaining(sa_sync_conn, person)


def test_signature_qui_neutralise_l_identifiant_ne_le_porte_pas(sa_sync_conn):
    person = _person(sa_sync_conn, "Monteil")
    _attribution(sa_sync_conn, person)
    _signature(sa_sync_conn, person, "monteil jean", neutralized={"orcid": "misplaced"})
    PgPersonsMatchingQueries().delete_unsupported_identifier_attributions(sa_sync_conn)
    assert not _attribution_remaining(sa_sync_conn, person)


def test_attribution_portee_par_une_signature_conservee(sa_sync_conn):
    person = _person(sa_sync_conn, "Monteil")
    _attribution(sa_sync_conn, person)
    _signature(sa_sync_conn, person, "monteil jean")
    PgPersonsMatchingQueries().delete_unsupported_identifier_attributions(sa_sync_conn)
    assert _attribution_remaining(sa_sync_conn, person)


def test_attribution_confirmee_conservee(sa_sync_conn):
    person = _person(sa_sync_conn, "Monteil")
    _attribution(sa_sync_conn, person, status="confirmed")
    PgPersonsMatchingQueries().delete_unsupported_identifier_attributions(sa_sync_conn)
    assert _attribution_remaining(sa_sync_conn, person)


def test_attribution_manuelle_conservee(sa_sync_conn):
    person = _person(sa_sync_conn, "Monteil")
    _attribution(sa_sync_conn, person, source="manual")
    PgPersonsMatchingQueries().delete_unsupported_identifier_attributions(sa_sync_conn)
    assert _attribution_remaining(sa_sync_conn, person)
