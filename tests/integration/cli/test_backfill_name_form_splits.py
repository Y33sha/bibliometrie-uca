"""Oneshot `backfill_name_form_splits` : découpage des formes de nom à verdict."""

from itertools import count

from sqlalchemy import text

from interfaces.cli.oneshot.backfill_name_form_splits import backfill

_SOURCE_IDS = count()


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


def _signature(conn, last: str, first: str) -> None:
    """Signature d'identité (`last`, `first`), sur une notice à elle."""
    identity = conn.execute(
        text(
            "INSERT INTO author_identifying_keys (last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f) ON CONFLICT DO NOTHING RETURNING id"
        ),
        {"l": last, "f": first},
    ).scalar_one()
    sp = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title) VALUES ('hal', :s, 't') RETURNING id"
        ),
        {"s": f"hal-formes-{next(_SOURCE_IDS)}"},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO source_authorships "
            "(source, source_publication_id, author_position, raw_author_name, identity_id) "
            "VALUES ('hal', :sp, 0, 'x', :iid)"
        ),
        {"sp": sp, "iid": identity},
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
    _signature(sa_sync_conn, "durand", "michel")

    stats = backfill(sa_sync_conn, apply=True)

    assert stats["rejected : identité de signature, prénom nom"] == 1
    assert _split(sa_sync_conn, pid, "michel durand") == ("durand", "michel")


def test_forme_dans_l_ordre_nom_prenom(sa_sync_conn):
    pid = _person(sa_sync_conn, "Dupont", "Marie")
    _form(sa_sync_conn, pid, "durand michel", "confirmed")
    _signature(sa_sync_conn, "durand", "michel")

    stats = backfill(sa_sync_conn, apply=True)

    assert stats["confirmed : identité de signature, nom prénom"] == 1
    assert _split(sa_sync_conn, pid, "durand michel") == ("durand", "michel")


def test_plusieurs_decoupages_le_nom_de_la_fiche_tranche(sa_sync_conn):
    pid = _person(sa_sync_conn, "Brugnon", "Florence")
    _form(sa_sync_conn, pid, "florence baume brugnon", "confirmed")
    _signature(sa_sync_conn, "brugnon", "florence baume")
    _signature(sa_sync_conn, "baume brugnon", "florence")

    stats = backfill(sa_sync_conn, apply=True)

    assert stats["confirmed : plusieurs découpages, nom de la fiche"] == 1
    assert _split(sa_sync_conn, pid, "florence baume brugnon") == ("brugnon", "florence baume")


def test_forme_sans_signature_supprimee(sa_sync_conn):
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
