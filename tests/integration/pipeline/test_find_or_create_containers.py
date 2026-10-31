"""Monographie d'un enregistrement source (`find_or_create_containers`). La normalisation crée aucune revue."""

import pytest
from sqlalchemy import text

from domain.serials.containers import ContainerDescription, determine_container_type
from domain.serials.issns import source_issns
from pipeline.transformation.publishing.find_or_create import (
    Containers,
    find_or_create_containers,
)
from pipeline.transformation.publishing.monographs.store import MonographStore


@pytest.fixture
def monographs(sa_sync_conn):
    return MonographStore(sa_sync_conn)


def _containers(facts: ContainerDescription, monographs: MonographStore) -> Containers:
    return find_or_create_containers(
        *determine_container_type(facts), publisher_id=None, monographs=monographs
    )


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608


def test_article_revue_sans_monographie(sa_sync_conn, monographs):
    before = _count(sa_sync_conn, "serials")
    facts = ContainerDescription(
        source="crossref", raw_doc_type="journal-article", journal_title="J. Things"
    )
    assert _containers(facts, monographs) == Containers(True, None)
    assert _count(sa_sync_conn, "serials") == before


def test_chapitre_d_une_collection_a_issn(sa_sync_conn, monographs):
    facts = ContainerDescription(
        source="crossref",
        raw_doc_type="book-chapter",
        journal_title="IFIP Advances in Information and Communication Technology",
        collection_title="IFIP Advances in Information and Communication Technology",
        book_title="Advances in Production Management Systems",
        issns=source_issns(print_issn="1868-4238"),
        isbns=("9783030580803",),
        year=2020,
    )
    containers = _containers(facts, monographs)
    assert containers.has_series
    row = sa_sync_conn.execute(
        text("SELECT title, isbn, serial_id, proceedings, year FROM monographs WHERE id = :id"),
        {"id": containers.monograph_id},
    ).one()
    assert tuple(row) == (
        "Advances in Production Management Systems",
        "9783030580803",
        None,
        False,
        2020,
    )


def test_chapitre_sans_issn_sans_serie(sa_sync_conn, monographs):
    facts = ContainerDescription(
        source="crossref", raw_doc_type="book-chapter", book_title="Le Paris du Moyen Âge"
    )
    containers = _containers(facts, monographs)
    assert not containers.has_series
    assert containers.monograph_id is not None


def test_article_de_congres_sans_issn_volume_d_actes(sa_sync_conn, monographs):
    facts = ContainerDescription(
        source="crossref",
        raw_doc_type="proceedings-article",
        journal_title="NuFACT 2022",
        book_title="NuFACT 2022",
    )
    containers = _containers(facts, monographs)
    assert not containers.has_series
    proceedings = sa_sync_conn.execute(
        text("SELECT proceedings FROM monographs WHERE id = :id"), {"id": containers.monograph_id}
    ).scalar_one()
    assert proceedings is True


def test_article_dans_un_conteneur_date_volume_seul(sa_sync_conn, monographs):
    """Cas réel : OpenAlex classe en article une communication dont la source est le congrès daté."""
    facts = ContainerDescription(
        source="openalex", raw_doc_type="article", journal_title="2021 21st ICCAS"
    )
    containers = _containers(facts, monographs)
    assert not containers.has_series
    assert containers.monograph_id is not None


def test_livre_monographie_a_son_titre(sa_sync_conn, monographs):
    facts = ContainerDescription(
        source="openalex", raw_doc_type="book", document_title="Global Handbook of Health"
    )
    containers = _containers(facts, monographs)
    title = sa_sync_conn.execute(
        text("SELECT title FROM monographs WHERE id = :id"), {"id": containers.monograph_id}
    ).scalar_one()
    assert title == "Global Handbook of Health"


def test_communication_parue_dans_une_revue_sans_monographie(sa_sync_conn, monographs):
    """Cas réel : WoS type « Article; Proceedings Paper » un article de revue issu d'un congrès ; la source nomme la revue."""
    facts = ContainerDescription(
        source="wos",
        raw_doc_type="Article; Proceedings Paper",
        journal_title="Physical Review D",
        collection_title="Physical Review D",
        book_title="Physical Review D",
        issns=source_issns(print_issn="2470-0010"),
    )
    assert _containers(facts, monographs) == Containers(True, None)


def test_idempotent(sa_sync_conn, monographs):
    facts = ContainerDescription(
        source="hal",
        raw_doc_type="COUV",
        book_title="Le Paris du Moyen Âge",
        isbns=("9782410013221",),
    )
    assert _containers(facts, monographs) == _containers(facts, monographs)
