"""Tests d'intégration de `PgMonographGatewayQueries`."""

import pytest
from sqlalchemy import text

from infrastructure.pipeline.monographs import PgMonographGatewayQueries

_PAPER = "9783030580803"
_ELECTRONIC = "9783030580810"


@pytest.fixture
def repo(sa_sync_conn):
    return PgMonographGatewayQueries(sa_sync_conn)


def _create(repo, title="Livre", **fields):
    defaults = {
        "proceedings": False,
        "year": None,
        "isbn": None,
        "eisbn": None,
        "publisher_id": None,
        "journal_id": None,
    }
    defaults.update(fields)
    return repo.create_monograph(title=title, title_normalized=title.lower(), **defaults)


def _row(conn, monograph_id):
    return conn.execute(
        text("SELECT isbn, eisbn, year, proceedings FROM monographs WHERE id = :id"),
        {"id": monograph_id},
    ).one()


def test_recherche_par_isbn_papier_ou_electronique(repo):
    mid = _create(repo, isbn=_PAPER, eisbn=_ELECTRONIC)
    assert repo.find_monograph_by_isbn(_PAPER) == mid
    assert repo.find_monograph_by_isbn(_ELECTRONIC) == mid


def test_recherche_par_titre_editeur_absent_tolere(repo, sa_sync_conn):
    publisher = sa_sync_conn.execute(
        text("INSERT INTO publishers (name, name_normalized) VALUES ('P', 'p') RETURNING id")
    ).scalar_one()
    other = sa_sync_conn.execute(
        text("INSERT INTO publishers (name, name_normalized) VALUES ('Q', 'q') RETURNING id")
    ).scalar_one()
    with_publisher = _create(repo, "Introduction", publisher_id=publisher)
    with_other = _create(repo, "Introduction", publisher_id=other)
    without_publisher = _create(repo, "Introduction")
    assert [m.id for m in repo.find_monographs_by_title("introduction", publisher)] == [
        with_publisher,
        without_publisher,
    ]
    assert [m.id for m in repo.find_monographs_by_title("introduction", None)] == [
        with_publisher,
        with_other,
        without_publisher,
    ]


def test_enrichissement_complete_les_champs_vides(repo, sa_sync_conn):
    mid = _create(repo, year=2020)
    repo.enrich_monograph(
        mid,
        proceedings=True,
        year=2021,
        isbn=_PAPER,
        eisbn=None,
        publisher_id=None,
        journal_id=None,
    )
    assert tuple(_row(sa_sync_conn, mid)) == (_PAPER, None, 2020, True)


def test_suppression_des_monographies_vides(repo, sa_sync_conn):
    empty = _create(repo, "Vide")
    held = _create(repo, "Portée")
    sa_sync_conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, monograph_id)"
            " VALUES ('hal', 'hal-monographie', 'Chapitre', :mid)"
        ),
        {"mid": held},
    )
    deleted = [mid for mid, _ in repo.delete_empty_monographs()]
    assert empty in deleted
    assert held not in deleted


def test_isbn_d_une_autre_monographie_hors_des_colonnes(repo, sa_sync_conn):
    """Deux monographies en double : l'ISBN de l'une ne va pas dans l'autre, la contrainte d'unicité le refuserait."""
    holder = _create(repo, "Livre A", eisbn=_ELECTRONIC)
    other = _create(repo, "Livre B", isbn=_PAPER)
    repo.enrich_monograph(
        other,
        proceedings=False,
        year=None,
        isbn=None,
        eisbn=_ELECTRONIC,
        publisher_id=None,
        journal_id=None,
    )
    assert tuple(_row(sa_sync_conn, other))[:2] == (_PAPER, None)
    assert tuple(_row(sa_sync_conn, holder))[:2] == (None, _ELECTRONIC)
