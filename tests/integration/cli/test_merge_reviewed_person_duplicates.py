"""Oneshot `merge_reviewed_person_duplicates` : fusions relues, identifiants suivis à travers les fusions déjà faites."""

import pytest
from sqlalchemy import text

from interfaces.cli.oneshot.merge_reviewed_person_duplicates import merge_pairs
from tests.integration.helpers.persons import insert_person, insert_person_rh


@pytest.fixture
def conn(sa_sync_conn, monkeypatch):
    monkeypatch.setattr(sa_sync_conn, "commit", lambda: None)
    return sa_sync_conn


def _exists(conn, person_id):
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM persons WHERE id = :id)"), {"id": person_id}
    ).scalar_one()


def test_une_paire_relue_est_fusionnee(conn):
    kept, absorbed = (
        insert_person(conn, "Pincemin", first_name="Bénédicte"),
        insert_person(conn, "Pincemin", first_name="Benedict"),
    )

    outcomes = merge_pairs(conn, [(kept, absorbed)], apply=True)

    assert outcomes == {"fusionnées": 1}
    assert _exists(conn, kept) and not _exists(conn, absorbed)


def test_une_paire_deja_fusionnee_est_ignoree(conn):
    a, b, c = (insert_person(conn, "Reguig", first_name=f) for f in ("Delphine", "D", ""))
    merge_pairs(conn, [(a, b)], apply=True)

    outcomes = merge_pairs(conn, [(a, b), (b, c)], apply=True)

    assert outcomes == {"déjà fusionnées": 1, "fusionnées": 1}
    assert _exists(conn, a) and not _exists(conn, c)


def test_une_personne_disparue_sans_redirection_est_ignoree(conn):
    kept, absorbed = insert_person(conn, "Bayart"), insert_person(conn, "Bayart")
    conn.execute(text("DELETE FROM persons WHERE id = :id"), {"id": absorbed})

    assert merge_pairs(conn, [(kept, absorbed)], apply=True) == {"personne disparue": 1}


def test_deux_fiches_rh_sont_ignorees(conn):
    a, b = insert_person(conn, "Martin"), insert_person(conn, "Martin")
    insert_person_rh(conn, a)
    insert_person_rh(conn, b)

    assert merge_pairs(conn, [(a, b)], apply=True) == {"deux fiches RH": 1}
    assert _exists(conn, a) and _exists(conn, b)
