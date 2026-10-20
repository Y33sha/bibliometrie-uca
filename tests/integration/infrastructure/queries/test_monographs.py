"""Tests d'intégration du SQL des monographies : store et étapes."""

import logging
from functools import partial

import pytest
from sqlalchemy import text

from domain.merge import MergedEntity
from pipeline.transformation.publishing.monographs.delete_empty_monographs import (
    delete_empty_monographs,
)
from pipeline.transformation.publishing.monographs.link_monographs_to_collections import (
    find_monograph_journal_candidates,
    set_monograph_journal,
)
from pipeline.transformation.publishing.monographs.merge_duplicate_monographs import (
    find_monographs_sharing_a_title,
    merge_monograph_into,
)
from pipeline.transformation.publishing.monographs.store import MonographStore
from pipeline.transformation.publishing.monographs.type_proceedings_volumes import (
    run_type_proceedings_volumes,
)
from tests.integration.helpers.journals import insert_journal, insert_journal_issn, insert_publisher
from tests.integration.helpers.redirects import redirect_of
from tests.integration.helpers.sources import insert_source_publication

# Notice de titre « Chapitre ».
_chapter = partial(insert_source_publication, title="Chapitre")

_PAPER = "9783030580803"
_ELECTRONIC = "9783030580810"


@pytest.fixture
def repo(sa_sync_conn):
    return MonographStore(sa_sync_conn)


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
    publisher = insert_publisher(sa_sync_conn, "P")
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
    _chapter(sa_sync_conn, source_id="hal-fusion", monograph_id=source)
    groups = [
        g for g in find_monographs_sharing_a_title(sa_sync_conn) if g.title == "Pascal intempestif"
    ]
    assert [m.id for m in groups[0].monographs] == [source, target]

    merge_monograph_into(sa_sync_conn, target, source)

    assert tuple(_row(sa_sync_conn, target))[:3] == (_PAPER, None, 2024)
    moved = sa_sync_conn.execute(
        text("SELECT monograph_id FROM source_publications WHERE source_id = 'hal-fusion'")
    ).scalar_one()
    assert moved == target
    gone = sa_sync_conn.execute(
        text("SELECT count(*) FROM monographs WHERE id = :id"), {"id": source}
    ).scalar_one()
    assert gone == 0
    assert redirect_of(sa_sync_conn, MergedEntity.MONOGRAPH, source) == target


def _journal(conn, title: str, issn: str | None = None) -> int:
    journal_id = insert_journal(conn, title)
    if issn:
        insert_journal_issn(conn, journal_id, issn=issn, support="print")
    return journal_id


def test_candidats_par_niveau_et_ecriture(repo, sa_sync_conn):
    volume = _journal(sa_sync_conn, "NuFACT 2022")
    collection = _journal(sa_sync_conn, "Lecture notes test", issn="2999-0101")
    mid = _create(repo, "NuFACT 2022", journal_id=volume)
    _chapter(
        sa_sync_conn, source="crossref", source_id="c-1", journal_id=collection, monograph_id=mid
    )
    _chapter(sa_sync_conn, source="crossref", source_id="c-2", journal_id=volume, monograph_id=mid)
    _chapter(sa_sync_conn, source_id="c-3", monograph_id=mid)

    candidates = {c.monograph_id: c for c in find_monograph_journal_candidates(sa_sync_conn)}
    found = candidates[mid]
    assert (found.journal_id, found.with_issn, found.without_issn) == (
        volume,
        (collection,),
        (volume,),
    )

    set_monograph_journal(sa_sync_conn, mid, collection)
    journal_id = sa_sync_conn.execute(
        text("SELECT journal_id FROM monographs WHERE id = :id"), {"id": mid}
    ).scalar_one()
    assert journal_id == collection


def test_suppression_des_monographies_vides(repo, sa_sync_conn):
    empty = _create(repo, "Vide")
    held = _create(repo, "Portée")
    _chapter(sa_sync_conn, source_id="hal-monographie", monograph_id=held)
    deleted = [mid for mid, _ in delete_empty_monographs(sa_sync_conn)]
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


def test_nature_recalculee_dans_les_deux_sens(repo, sa_sync_conn):
    """Un volume LNCS marqué livre devient volume d'actes par sa collection ; un livre marqué volume d'actes sans aucun signal redevient livre."""
    series = _journal(sa_sync_conn, "Lecture notes test proceedings")
    sa_sync_conn.execute(
        text("UPDATE journals SET journal_type = 'proceedings' WHERE id = :j"), {"j": series}
    )
    lncs = _create(repo, "Fun with Algorithms", journal_id=series)
    livre = _create(repo, "Un livre", proceedings=True)
    for source_id, mid in (("c-lncs", lncs), ("c-livre", livre)):
        _chapter(
            sa_sync_conn,
            source="crossref",
            source_id=source_id,
            doc_type="book-chapter",
            monograph_id=mid,
        )

    metrics = run_type_proceedings_volumes(sa_sync_conn, logging.getLogger("test"))

    assert tuple(_row(sa_sync_conn, lncs))[3] is True
    assert tuple(_row(sa_sync_conn, livre))[3] is False
    assert metrics.extras == {"monographs_to_proceedings": 1, "monographs_to_books": 1}
