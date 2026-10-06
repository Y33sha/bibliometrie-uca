"""Oneshot `backfill_name_form_splits` : découpage des formes de nom à verdict."""

from sqlalchemy import text

from interfaces.cli.oneshot.backfill_name_form_splits import backfill
from tests.integration.helpers.authorships import upsert_identity


def _person(conn, last: str, first: str) -> int:
    return conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).scalar_one()


def _form(conn, person_id: int, name_form: str, status: str) -> None:
    conn.execute(
        text(
            "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
            "VALUES (:f, :p, ARRAY['hal'], CAST(:s AS identifier_status))"
        ),
        {"f": name_form, "p": person_id, "s": status},
    )


def _split(conn, person_id: int, name_form: str):
    return tuple(
        conn.execute(
            text(
                "SELECT last_name_normalized, first_name_normalized FROM person_name_forms "
                "WHERE person_id = :p AND name_form = :f"
            ),
            {"p": person_id, "f": name_form},
        ).one()
    )


def test_forme_de_la_personne(sa_sync_conn):
    pid = _person(sa_sync_conn, "Dupont", "Marie")
    _form(sa_sync_conn, pid, "dupont marie", "confirmed")

    stats = backfill(sa_sync_conn, apply=True)

    assert stats["confirmed : fiche de la personne"] == 1
    assert _split(sa_sync_conn, pid, "dupont marie") == ("dupont", "marie")


def test_forme_d_une_seule_identite(sa_sync_conn):
    pid = _person(sa_sync_conn, "Dupont", "Marie")
    _form(sa_sync_conn, pid, "michel durand", "rejected")
    upsert_identity(sa_sync_conn, "michel durand")

    stats = backfill(sa_sync_conn, apply=True)

    assert stats["rejected : identité de signature, prénom nom"] == 1
    assert _split(sa_sync_conn, pid, "michel durand") == ("durand", "michel")


def test_forme_dans_l_ordre_nom_prenom(sa_sync_conn):
    pid = _person(sa_sync_conn, "Dupont", "Marie")
    _form(sa_sync_conn, pid, "durand michel", "confirmed")
    upsert_identity(sa_sync_conn, "michel durand")

    stats = backfill(sa_sync_conn, apply=True)

    assert stats["confirmed : identité de signature, nom prénom"] == 1
    assert _split(sa_sync_conn, pid, "durand michel") == ("durand", "michel")


def test_forme_sans_identite_supprimee(sa_sync_conn):
    pid = _person(sa_sync_conn, "Dupont", "Marie")
    _form(sa_sync_conn, pid, "zorglub inconnu", "rejected")

    stats = backfill(sa_sync_conn, apply=True)

    assert stats["rejected : aucune identité, supprimée"] == 1
    remaining = sa_sync_conn.execute(
        text("SELECT count(*) FROM person_name_forms WHERE person_id = :p"), {"p": pid}
    ).scalar_one()
    assert remaining == 0


def test_forme_en_attente_ignoree(sa_sync_conn):
    pid = _person(sa_sync_conn, "Dupont", "Marie")
    _form(sa_sync_conn, pid, "dupont marie", "pending")

    assert backfill(sa_sync_conn, apply=True) == {}
