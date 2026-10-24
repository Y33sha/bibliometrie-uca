"""Oneshot `delete_initials_last_name_persons` : suppression des personnes au nom de famille fait d'initiales."""

from sqlalchemy import text

from interfaces.cli.oneshot.delete_initials_last_name_persons import delete_persons
from tests.integration.helpers.contributions import group_id_of, insert_contribution
from tests.integration.helpers.persons import insert_person, insert_person_name_form
from tests.integration.helpers.publications import insert_publication


def _exists(conn, person_id: int) -> bool:
    return (
        conn.execute(text("SELECT 1 FROM persons WHERE id = :p"), {"p": person_id}).first()
        is not None
    )


def test_supprime_la_personne_au_nom_fait_d_initiales(sa_sync_conn):
    inverted = insert_person(sa_sync_conn, "P.P.", first_name="Lechalard")
    regular = insert_person(sa_sync_conn, "Lechalard", first_name="P.P.")

    assert delete_persons(sa_sync_conn, apply=True) == [inverted]
    assert not _exists(sa_sync_conn, inverted)
    assert _exists(sa_sync_conn, regular)


def test_epargne_une_personne_a_verdict(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "D.", first_name="Lancierini")
    insert_person_name_form(
        sa_sync_conn, pid, name_form="lancierini d", sources=["hal"], status="confirmed"
    )

    assert delete_persons(sa_sync_conn, apply=True) == []
    assert _exists(sa_sync_conn, pid)


def test_dry_run_n_ecrit_rien(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "G.", first_name="Giuli")

    assert delete_persons(sa_sync_conn, apply=False) == [pid]
    assert _exists(sa_sync_conn, pid)


def test_vide_les_groupes_de_la_personne_supprimee(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "P.P.", first_name="Lechalard")
    publication_id = insert_publication(sa_sync_conn)
    insert_contribution(sa_sync_conn, publication_id, person_id=pid)
    contribution_id = group_id_of(sa_sync_conn, publication_id, pid)

    assert delete_persons(sa_sync_conn, apply=True) == [pid]
    assert sa_sync_conn.execute(
        text("SELECT person_id, resolution_mode FROM contributions WHERE id = :g"),
        {"g": contribution_id},
    ).one() == (None, None)
