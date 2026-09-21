"""Tests d'intégration de `find_or_create_containers` : entrée de `journals` et monographie d'un document."""

import pytest
from sqlalchemy import text

from application.services.journals.core import find_or_create_journal
from application.services.monographs.containers import Containers, find_or_create_containers
from domain.journals.containers import ContainerDescription
from domain.journals.journal import JournalType
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


def test_article_de_congres_volume_et_son_recueil_dans_journals(sa_sync_conn, repo):
    """Le recueil d'actes reste dans `journals`, et la monographie du volume le désigne."""
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
    assert containers.journal_id is not None
    assert tuple(row) == (True, containers.journal_id)


def test_chapitre_sans_issn_rejoint_un_recueil_d_actes(sa_sync_conn, repo):
    """Cas réel : chapitres Crossref des actes SODA, typés proceedings par l'administration."""
    title = "Proceedings of the 2025 Annual ACM-SIAM Symposium on Discrete Algorithms (SODA)"
    proceedings = find_or_create_journal(title, repo=repo)
    repo.set_journal_type(proceedings, JournalType.PROCEEDINGS)
    facts = ContainerDescription(
        source="crossref", raw_doc_type="book-chapter", journal_title=title, book_title=title
    )
    assert find_or_create_containers(facts, publisher_id=None, repo=repo).journal_id == proceedings


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
