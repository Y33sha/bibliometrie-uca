"""Tests d'intégration de `find_or_create_containers` : entrée de `serials` et monographie d'un document."""

import pytest
from sqlalchemy import text

from domain.serials.containers import ContainerDescription
from domain.serials.issns import source_issns
from pipeline.transformation.publishing.containers import ContainerStores
from pipeline.transformation.publishing.find_or_create import (
    Containers,
    find_or_create_containers,
    find_or_create_serial,
)


@pytest.fixture
def stores(sa_sync_conn):
    return ContainerStores.of(sa_sync_conn)


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608


def test_article_revue_sans_monographie(sa_sync_conn, stores):
    facts = ContainerDescription(
        source="crossref", raw_doc_type="journal-article", journal_title="J. Things"
    )
    containers = find_or_create_containers(facts, publisher_id=None, stores=stores)
    assert containers.serial_id is not None
    assert containers.monograph_id is None


def test_chapitre_monographie_et_son_entree_de_journals(sa_sync_conn, stores):
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
    containers = find_or_create_containers(facts, publisher_id=None, stores=stores)
    row = sa_sync_conn.execute(
        text("SELECT title, isbn, serial_id, proceedings, year FROM monographs WHERE id = :id"),
        {"id": containers.monograph_id},
    ).one()
    assert tuple(row) == (
        "Advances in Production Management Systems",
        "9783030580803",
        containers.serial_id,
        False,
        2020,
    )


def test_chapitre_sans_issn_aucune_revue(sa_sync_conn, stores):
    before = _count(sa_sync_conn, "serials")
    facts = ContainerDescription(
        source="crossref", raw_doc_type="book-chapter", book_title="Le Paris du Moyen Âge"
    )
    containers = find_or_create_containers(facts, publisher_id=None, stores=stores)
    assert containers.serial_id is None
    assert containers.monograph_id is not None
    assert _count(sa_sync_conn, "serials") == before


def test_article_de_congres_sans_issn_volume_seul(sa_sync_conn, stores):
    """Le volume d'actes devient une monographie, sans entrée dans `serials`."""
    before = _count(sa_sync_conn, "serials")
    facts = ContainerDescription(
        source="crossref",
        raw_doc_type="proceedings-article",
        journal_title="NuFACT 2022",
        book_title="NuFACT 2022",
    )
    containers = find_or_create_containers(facts, publisher_id=None, stores=stores)
    row = sa_sync_conn.execute(
        text("SELECT proceedings, serial_id FROM monographs WHERE id = :id"),
        {"id": containers.monograph_id},
    ).one()
    assert containers.serial_id is None
    assert tuple(row) == (True, None)
    assert _count(sa_sync_conn, "serials") == before


def test_article_dans_un_conteneur_date_volume_seul(sa_sync_conn, stores):
    """Cas réel : OpenAlex classe en article une communication dont la source est le congrès daté."""
    before = _count(sa_sync_conn, "serials")
    facts = ContainerDescription(
        source="openalex", raw_doc_type="article", journal_title="2021 21st ICCAS"
    )
    containers = find_or_create_containers(facts, publisher_id=None, stores=stores)
    assert containers.serial_id is None
    assert containers.monograph_id is not None
    assert _count(sa_sync_conn, "serials") == before


def test_serie_sans_titre_retrouvee_par_issn(sa_sync_conn, stores):
    collection = find_or_create_serial(
        "Lecture Notes in Computer Science",
        issns=source_issns(print_issn="0302-9743"),
        repo=stores.serials,
    )
    facts = ContainerDescription(
        source="openalex",
        raw_doc_type="book-chapter",
        journal_title="ICORES 2023",
        book_title="ICORES 2023",
        issns=source_issns(print_issn="0302-9743"),
    )
    containers = find_or_create_containers(facts, publisher_id=None, stores=stores)
    assert containers.serial_id == collection
    serial_id = sa_sync_conn.execute(
        text("SELECT serial_id FROM monographs WHERE id = :id"), {"id": containers.monograph_id}
    ).scalar_one()
    assert serial_id == collection


def test_chapitre_sans_issn_ignore_une_revue_de_meme_titre(sa_sync_conn, stores):
    find_or_create_serial("Handbook of Things", repo=stores.serials)
    facts = ContainerDescription(
        source="crossref",
        raw_doc_type="book-chapter",
        journal_title="Handbook of Things",
        book_title="Handbook of Things",
    )
    assert find_or_create_containers(facts, publisher_id=None, stores=stores).serial_id is None


def test_livre_monographie_a_son_titre(sa_sync_conn, stores):
    facts = ContainerDescription(
        source="openalex", raw_doc_type="book", document_title="Global Handbook of Health"
    )
    containers = find_or_create_containers(facts, publisher_id=None, stores=stores)
    title = sa_sync_conn.execute(
        text("SELECT title FROM monographs WHERE id = :id"), {"id": containers.monograph_id}
    ).scalar_one()
    assert title == "Global Handbook of Health"


def test_communication_parue_dans_une_revue_sans_monographie(sa_sync_conn, stores):
    """Cas réel : WoS type « Article; Proceedings Paper » un article de revue issu d'un congrès ; la source nomme la revue."""
    facts = ContainerDescription(
        source="wos",
        raw_doc_type="Article; Proceedings Paper",
        journal_title="Physical Review D",
        collection_title="Physical Review D",
        book_title="Physical Review D",
        issns=source_issns(print_issn="2470-0010"),
    )
    containers = find_or_create_containers(facts, publisher_id=None, stores=stores)
    assert containers.serial_id is not None
    assert containers.monograph_id is None


def test_idempotent(sa_sync_conn, stores):
    facts = ContainerDescription(
        source="hal",
        raw_doc_type="COUV",
        book_title="Le Paris du Moyen Âge",
        isbns=("9782410013221",),
    )
    first = find_or_create_containers(facts, publisher_id=None, stores=stores)
    assert find_or_create_containers(facts, publisher_id=None, stores=stores) == first
    assert isinstance(first, Containers)


def test_issn_mal_forme_garde_dans_la_revue(sa_sync_conn, stores):
    facts = ContainerDescription(
        source="crossref",
        raw_doc_type="journal-article",
        journal_title="J. Rejects",
        issns=source_issns(print_issn="1234-5670"),
    )
    serial_id = find_or_create_containers(facts, publisher_id=None, stores=stores).serial_id
    rows = sa_sync_conn.execute(
        text("SELECT issn, status::text FROM serial_issns WHERE serial_id = :id"),
        {"id": serial_id},
    ).all()
    assert [tuple(r) for r in rows] == [("1234-5670", "malformed")]
