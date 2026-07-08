"""Réinitialisation nominale de la phase personnes : re-orphelinage des signatures à
forme de nom devenue ambiguë, puis GC des personnes vidées.
"""

from sqlalchemy import text

from infrastructure.queries.pipeline.persons_create import (
    delete_empty_persons,
    reorphan_ambiguous_nominal,
    reset_cross_source,
)
from tests.integration.helpers.authorships import upsert_identity


def _person(conn, last, first):
    return conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).scalar_one()


def _name_form(conn, form, person_id, status="pending"):
    conn.execute(
        text(
            "INSERT INTO person_name_forms (name_form, person_id, status) "
            "VALUES (:f, :p, CAST(:s AS identifier_status))"
        ),
        {"f": form, "p": person_id, "s": status},
    )


def _signature(conn, *, form, person_id, mode):
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
    identity = upsert_identity(conn, form, None)
    return conn.execute(
        text(
            "INSERT INTO source_authorships (source, source_publication_id, author_position, "
            "person_id, in_perimeter, raw_author_name, identity_id, resolution_mode) "
            "VALUES ('hal', :sp, 0, :pid, TRUE, :raw, :iid, CAST(:mode AS resolution_mode)) "
            "RETURNING id"
        ),
        {"sp": sp, "pid": person_id, "raw": form, "iid": identity, "mode": mode},
    ).scalar_one()


def _row(conn, sa_id):
    return conn.execute(
        text("SELECT person_id, resolution_mode FROM source_authorships WHERE id = :i"),
        {"i": sa_id},
    ).one()


def _person_exists(conn, person_id):
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM persons WHERE id = :i)"), {"i": person_id}
    ).scalar_one()


def test_reorphan_only_ambiguous_unpinned_nominal(sa_sync_conn):
    conn = sa_sync_conn
    a = _person(conn, "Martin", "Jean")
    b = _person(conn, "Martin", "Jeanne")
    # « j martin » désigne A et B → ambiguë ; « jean martin » ne désigne que B.
    _name_form(conn, "j martin", a)
    _name_form(conn, "j martin", b)
    _name_form(conn, "jean martin", b)

    ambiguous = _signature(conn, form="j martin", person_id=a, mode="name")
    unambiguous = _signature(conn, form="jean martin", person_id=b, mode="name")
    pinned = _signature(conn, form="j martin", person_id=a, mode="name")
    conn.execute(
        text("INSERT INTO confirmed_authorships (source_authorship_id, person_id) VALUES (:s, :p)"),
        {"s": pinned, "p": a},
    )
    by_identifier = _signature(conn, form="j martin", person_id=a, mode="identifier")

    assert reorphan_ambiguous_nominal(conn) == 1

    assert _row(conn, ambiguous) == (None, None)  # forme ambiguë, nominale, non épinglée
    assert _row(conn, unambiguous).person_id == b  # forme non ambiguë
    assert _row(conn, pinned).person_id == a  # épinglé par l'admin
    assert _row(conn, by_identifier).person_id == a  # résolu par identifiant


def test_reset_cross_source_detaches_only_cross_source(sa_sync_conn):
    conn = sa_sync_conn
    p = _person(conn, "Zhang", "Wei")
    cross = _signature(conn, form="wei zhang", person_id=p, mode="cross_source")
    nominal = _signature(conn, form="wei zhang", person_id=p, mode="name")
    pinned_cross = _signature(conn, form="wei zhang", person_id=p, mode="cross_source")
    conn.execute(
        text("INSERT INTO confirmed_authorships (source_authorship_id, person_id) VALUES (:s, :p)"),
        {"s": pinned_cross, "p": p},
    )

    assert reset_cross_source(conn) == 1

    assert _row(conn, cross) == (None, None)  # recompute complet
    assert _row(conn, nominal).person_id == p  # canal nominal intact
    assert _row(conn, pinned_cross).person_id == p  # épinglé admin


def test_delete_empty_persons_spares_signed_and_rh(sa_sync_conn):
    conn = sa_sync_conn
    empty = _person(conn, "Ghost", "G")
    signed = _person(conn, "Real", "R")
    _signature(conn, form="real r", person_id=signed, mode="name")
    rh = _person(conn, "Prof", "P")
    conn.execute(text("INSERT INTO persons_rh (person_id) VALUES (:p)"), {"p": rh})

    delete_empty_persons(conn)

    assert _person_exists(conn, empty) is False
    assert _person_exists(conn, signed) is True
    assert _person_exists(conn, rh) is True
