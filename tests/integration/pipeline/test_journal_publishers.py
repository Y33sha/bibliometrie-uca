"""Tests d'intégration de l'éditeur d'une revue calculé d'après ses publications (`journal_publishers`)."""

from sqlalchemy import text

from pipeline.transformation.publishing.journals.journal_publishers import (
    refresh_journal_publishers,
)
from tests.integration.helpers.journals import insert_journal, insert_publisher
from tests.integration.helpers.publications import insert_publication


def _publications(conn, journal_id: int, publisher_id: int, year: int, n: int = 1) -> None:
    for _ in range(n):
        publication = insert_publication(conn, journal_id=journal_id, publication_year=year)
        conn.execute(
            text("UPDATE publications SET publisher_id = :p WHERE id = :id"),
            {"p": publisher_id, "id": publication},
        )


def _publisher_of(conn, journal_id: int) -> int | None:
    return conn.execute(
        text("SELECT publisher_id FROM journals WHERE id = :id"), {"id": journal_id}
    ).scalar_one()


def test_l_editeur_de_la_derniere_annee_l_emporte(sa_sync_conn):
    """*animal* : Cambridge jusqu'en 2020, Elsevier ensuite."""
    cambridge = insert_publisher(sa_sync_conn, "Cambridge")
    elsevier = insert_publisher(sa_sync_conn, "Elsevier")
    journal = insert_journal(sa_sync_conn, "animal", publisher_id=cambridge)
    _publications(sa_sync_conn, journal, cambridge, 2019, n=5)
    _publications(sa_sync_conn, journal, elsevier, 2023)

    assert refresh_journal_publishers(sa_sync_conn) >= 1
    assert _publisher_of(sa_sync_conn, journal) == elsevier
    assert refresh_journal_publishers(sa_sync_conn) == 0


def test_a_egalite_le_plus_frequent_sur_toutes_les_annees(sa_sync_conn):
    first = insert_publisher(sa_sync_conn, "A")
    second = insert_publisher(sa_sync_conn, "B")
    journal = insert_journal(sa_sync_conn, "Revue")
    _publications(sa_sync_conn, journal, second, 2020, n=3)
    _publications(sa_sync_conn, journal, first, 2023)
    _publications(sa_sync_conn, journal, second, 2023)

    refresh_journal_publishers(sa_sync_conn, journal)

    assert _publisher_of(sa_sync_conn, journal) == second


def test_sans_publication_a_editeur_la_revue_n_en_a_pas(sa_sync_conn):
    publisher = insert_publisher(sa_sync_conn, "A")
    journal = insert_journal(sa_sync_conn, "Revue", publisher_id=publisher)
    insert_publication(sa_sync_conn, journal_id=journal)

    refresh_journal_publishers(sa_sync_conn)

    assert _publisher_of(sa_sync_conn, journal) is None
