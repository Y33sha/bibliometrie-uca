"""Tests d'intégration de `find_or_create_containers` : revue, monographie et collection d'un document."""

import pytest
from sqlalchemy import text

from application.services.monographs.containers import (
    ContainerFacts,
    Containers,
    find_or_create_containers,
)
from infrastructure.pipeline.containers import PgContainerGatewayQueries


@pytest.fixture
def repo(sa_sync_conn):
    return PgContainerGatewayQueries(sa_sync_conn)


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608


def test_article_revue_sans_monographie(sa_sync_conn, repo):
    facts = ContainerFacts(
        source="crossref", raw_doc_type="journal-article", journal_title="J. Things"
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    assert containers.journal_id is not None
    assert containers.monograph_id is None


def test_chapitre_monographie_et_collection(sa_sync_conn, repo):
    facts = ContainerFacts(
        source="crossref",
        raw_doc_type="book-chapter",
        collection_title="IFIP Advances in Information and Communication Technology",
        book_title="Advances in Production Management Systems",
        issn="1868-4238",
        isbns=("9783030580803",),
        year=2020,
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    row = sa_sync_conn.execute(
        text("SELECT title, isbn, journal_id, proceedings, year FROM monographs WHERE id = :id"),
        {"id": containers.monograph_id},
    ).one()
    assert tuple(row) == (
        "Advances in Production Management Systems",
        "9783030580803",
        containers.journal_id,
        False,
        2020,
    )


def test_chapitre_sans_issn_aucune_revue(sa_sync_conn, repo):
    before = _count(sa_sync_conn, "journals")
    facts = ContainerFacts(
        source="crossref", raw_doc_type="book-chapter", book_title="Le Paris du Moyen Âge"
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    assert containers.journal_id is None
    assert containers.monograph_id is not None
    assert _count(sa_sync_conn, "journals") == before


def test_article_de_congres_volume_d_actes(sa_sync_conn, repo):
    facts = ContainerFacts(
        source="crossref", raw_doc_type="proceedings-article", book_title="NuFACT 2022"
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    proceedings = sa_sync_conn.execute(
        text("SELECT proceedings FROM monographs WHERE id = :id"), {"id": containers.monograph_id}
    ).scalar_one()
    assert proceedings is True
    assert containers.journal_id is None


def test_livre_monographie_a_son_titre(sa_sync_conn, repo):
    facts = ContainerFacts(
        source="openalex", raw_doc_type="book", document_title="Global Handbook of Health"
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    title = sa_sync_conn.execute(
        text("SELECT title FROM monographs WHERE id = :id"), {"id": containers.monograph_id}
    ).scalar_one()
    assert title == "Global Handbook of Health"


def test_communication_parue_dans_une_revue_sans_monographie(sa_sync_conn, repo):
    """Cas réel : WoS type « Article; Proceedings Paper » un article de revue issu d'un congrès ; la source nomme la revue."""
    facts = ContainerFacts(
        source="wos",
        raw_doc_type="Article; Proceedings Paper",
        journal_title="Physical Review D",
        collection_title="Physical Review D",
        book_title="Physical Review D",
        issn="2470-0010",
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    assert containers.journal_id is not None
    assert containers.monograph_id is None


def test_collection_cherchee_par_issn_sans_titre(sa_sync_conn, repo):
    collection = find_or_create_containers(
        ContainerFacts(
            source="crossref",
            raw_doc_type="journal-article",
            journal_title="UNCECOMP Proceedings",
            issn="2623-3339",
        ),
        publisher_id=None,
        repo=repo,
    ).journal_id
    facts = ContainerFacts(
        source="crossref",
        raw_doc_type="proceedings-article",
        book_title="Proceedings of UNCECOMP 2019",
        issn="2623-3339",
    )
    assert find_or_create_containers(facts, publisher_id=None, repo=repo).journal_id == collection


def test_idempotent(sa_sync_conn, repo):
    facts = ContainerFacts(
        source="hal",
        raw_doc_type="COUV",
        book_title="Le Paris du Moyen Âge",
        isbns=("9782410013221",),
    )
    first = find_or_create_containers(facts, publisher_id=None, repo=repo)
    assert find_or_create_containers(facts, publisher_id=None, repo=repo) == first
    assert isinstance(first, Containers)
