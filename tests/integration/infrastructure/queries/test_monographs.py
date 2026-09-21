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


def test_recherche_par_titre_tous_editeurs(repo, sa_sync_conn):
    publisher = sa_sync_conn.execute(
        text("INSERT INTO publishers (name, name_normalized) VALUES ('P', 'p') RETURNING id")
    ).scalar_one()
    with_publisher = _create(repo, "Introduction", publisher_id=publisher, isbn=_PAPER)
    without_publisher = _create(repo, "Introduction")
    assert repo.find_monographs_by_title("introduction") == [
        (with_publisher, _PAPER, None, publisher),
        (without_publisher, None, None, None),
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


def test_fusion_reporte_enregistrements_et_isbn(repo, sa_sync_conn):
    source = _create(repo, "Pascal intempestif", isbn=_PAPER, year=2024)
    target = _create(repo, "Pascal intempestif")
    sa_sync_conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, monograph_id)"
            " VALUES ('hal', 'hal-fusion', 'Chapitre', :mid)"
        ),
        {"mid": source},
    )
    groups = [g for g in repo.find_monographs_sharing_a_title() if g.title == "Pascal intempestif"]
    assert [m.id for m in groups[0].monographs] == [source, target]

    repo.merge_monograph_into(target, source)

    assert tuple(_row(sa_sync_conn, target))[:3] == (_PAPER, None, 2024)
    moved = sa_sync_conn.execute(
        text("SELECT monograph_id FROM source_publications WHERE source_id = 'hal-fusion'")
    ).scalar_one()
    assert moved == target
    gone = sa_sync_conn.execute(
        text("SELECT count(*) FROM monographs WHERE id = :id"), {"id": source}
    ).scalar_one()
    assert gone == 0


def _journal(conn, title: str, issn: str | None = None) -> int:
    return conn.execute(
        text(
            "INSERT INTO journals (title, title_normalized, issn)"
            " VALUES (:t, lower(:t), :i) RETURNING id"
        ),
        {"t": title, "i": issn},
    ).scalar_one()


def _record(conn, source_id: str, monograph_id: int, journal_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, monograph_id, journal_id)"
            " VALUES ('crossref', :sid, 'Chapitre', :mid, :jid)"
        ),
        {"sid": source_id, "mid": monograph_id, "jid": journal_id},
    )


def test_candidats_par_niveau_et_ecriture(repo, sa_sync_conn):
    volume = _journal(sa_sync_conn, "NuFACT 2022")
    collection = _journal(sa_sync_conn, "Lecture notes test", issn="2999-0101")
    mid = _create(repo, "NuFACT 2022", journal_id=volume)
    _record(sa_sync_conn, "c-1", mid, collection)
    _record(sa_sync_conn, "c-2", mid, volume)
    sa_sync_conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, monograph_id)"
            " VALUES ('hal', 'c-3', 'Chapitre', :mid)"
        ),
        {"mid": mid},
    )

    candidates = {c.monograph_id: c for c in repo.find_monograph_journal_candidates()}
    found = candidates[mid]
    assert (found.journal_id, found.with_issn, found.without_issn) == (
        volume,
        (collection,),
        (volume,),
    )

    repo.set_monograph_journal(mid, collection)
    journal_id = sa_sync_conn.execute(
        text("SELECT journal_id FROM monographs WHERE id = :id"), {"id": mid}
    ).scalar_one()
    assert journal_id == collection


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
