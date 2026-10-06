"""Oneshot `delete_initials_last_name_persons` : suppression des personnes au nom de famille fait d'initiales."""

from sqlalchemy import text

from interfaces.cli.oneshot.delete_initials_last_name_persons import delete_persons


def _person(conn, last: str, first: str) -> int:
    return conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, normalize_name_form(:l), normalize_name_form(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).scalar_one()


def _exists(conn, person_id: int) -> bool:
    return (
        conn.execute(text("SELECT 1 FROM persons WHERE id = :p"), {"p": person_id}).first()
        is not None
    )


def test_supprime_la_personne_au_nom_fait_d_initiales(sa_sync_conn):
    inverted = _person(sa_sync_conn, "P.P.", "Lechalard")
    regular = _person(sa_sync_conn, "Lechalard", "P.P.")

    assert delete_persons(sa_sync_conn, apply=True) == [inverted]
    assert not _exists(sa_sync_conn, inverted)
    assert _exists(sa_sync_conn, regular)


def test_epargne_une_personne_a_verdict(sa_sync_conn):
    pid = _person(sa_sync_conn, "D.", "Lancierini")
    sa_sync_conn.execute(
        text(
            "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
            "VALUES ('lancierini d', :p, ARRAY['hal'], 'confirmed')"
        ),
        {"p": pid},
    )

    assert delete_persons(sa_sync_conn, apply=True) == []
    assert _exists(sa_sync_conn, pid)


def test_dry_run_n_ecrit_rien(sa_sync_conn):
    pid = _person(sa_sync_conn, "G.", "Giuli")

    assert delete_persons(sa_sync_conn, apply=False) == [pid]
    assert _exists(sa_sync_conn, pid)
