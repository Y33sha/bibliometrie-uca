"""Tests d'intégration de `find_or_create_containers` : entrée de `journals` et monographie d'un document."""

import pytest
from sqlalchemy import text

from application.services.journals.core import find_or_create_journal
from application.services.monographs.containers import Containers, find_or_create_containers
from domain.journals.containers import ContainerDescription
from infrastructure.pipeline.containers import PgContainerGatewayQueries


@pytest.fixture
def repo(sa_sync_conn):
    return PgContainerGatewayQueries(sa_sync_conn)


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608


def test_article_revue_sans_monographie(sa_sync_conn, repo):
    facts = ContainerDescription(
        source="crossref", raw_doc_type="journal-article", journal_title="J. Things"
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    assert containers.journal_id is not None
    assert containers.monograph_id is None


def test_chapitre_monographie_et_son_entree_de_journals(sa_sync_conn, repo):
    facts = ContainerDescription(
        source="crossref",
        raw_doc_type="book-chapter",
        journal_title="IFIP Advances in Information and Communication Technology",
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
    facts = ContainerDescription(
        source="crossref", raw_doc_type="book-chapter", book_title="Le Paris du Moyen Âge"
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    assert containers.journal_id is None
    assert containers.monograph_id is not None
    assert _count(sa_sync_conn, "journals") == before


def test_article_de_congres_sans_issn_volume_seul(sa_sync_conn, repo):
    """Le volume d'actes devient une monographie, sans entrée dans `journals`."""
    before = _count(sa_sync_conn, "journals")
    facts = ContainerDescription(
        source="crossref",
        raw_doc_type="proceedings-article",
        journal_title="NuFACT 2022",
        book_title="NuFACT 2022",
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    row = sa_sync_conn.execute(
        text("SELECT proceedings, journal_id FROM monographs WHERE id = :id"),
        {"id": containers.monograph_id},
    ).one()
    assert containers.journal_id is None
    assert tuple(row) == (True, None)
    assert _count(sa_sync_conn, "journals") == before


def test_article_dans_un_conteneur_date_volume_seul(sa_sync_conn, repo):
    """Cas réel : OpenAlex classe en article une communication dont la source est le congrès daté."""
    before = _count(sa_sync_conn, "journals")
    facts = ContainerDescription(
        source="openalex", raw_doc_type="article", journal_title="2021 21st ICCAS"
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    assert containers.journal_id is None
    assert containers.monograph_id is not None
    assert _count(sa_sync_conn, "journals") == before


def test_serie_sans_titre_retrouvee_par_issn(sa_sync_conn, repo):
    collection = find_or_create_journal(
        "Lecture Notes in Computer Science", issn="0302-9743", repo=repo
    )
    facts = ContainerDescription(
        source="openalex",
        raw_doc_type="book-chapter",
        journal_title="ICORES 2023",
        book_title="ICORES 2023",
        issn="0302-9743",
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    assert containers.journal_id == collection
    journal_id = sa_sync_conn.execute(
        text("SELECT journal_id FROM monographs WHERE id = :id"), {"id": containers.monograph_id}
    ).scalar_one()
    assert journal_id == collection


def test_chapitre_sans_issn_ignore_une_revue_de_meme_titre(sa_sync_conn, repo):
    find_or_create_journal("Handbook of Things", repo=repo)
    facts = ContainerDescription(
        source="crossref",
        raw_doc_type="book-chapter",
        journal_title="Handbook of Things",
        book_title="Handbook of Things",
    )
    assert find_or_create_containers(facts, publisher_id=None, repo=repo).journal_id is None


def test_livre_monographie_a_son_titre(sa_sync_conn, repo):
    facts = ContainerDescription(
        source="openalex", raw_doc_type="book", document_title="Global Handbook of Health"
    )
    containers = find_or_create_containers(facts, publisher_id=None, repo=repo)
    title = sa_sync_conn.execute(
        text("SELECT title FROM monographs WHERE id = :id"), {"id": containers.monograph_id}
    ).scalar_one()
    assert title == "Global Handbook of Health"


def test_communication_parue_dans_une_revue_sans_monographie(sa_sync_conn, repo):
    """Cas réel : WoS type « Article; Proceedings Paper » un article de revue issu d'un congrès ; la source nomme la revue."""
    facts = ContainerDescription(
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


def test_idempotent(sa_sync_conn, repo):
    facts = ContainerDescription(
        source="hal",
        raw_doc_type="COUV",
        book_title="Le Paris du Moyen Âge",
        isbns=("9782410013221",),
    )
    first = find_or_create_containers(facts, publisher_id=None, repo=repo)
    assert find_or_create_containers(facts, publisher_id=None, repo=repo) == first
    assert isinstance(first, Containers)
