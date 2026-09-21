"""Tests d'intégration de `PgPublicationRepository.get_monograph_journal_ids`."""

from sqlalchemy import text

from infrastructure.repositories.publication_repository import PgPublicationRepository


def test_collection_de_chaque_monographie(sa_sync_conn):
    journal_id = sa_sync_conn.execute(
        text("INSERT INTO journals (title, title_normalized) VALUES ('C', 'c') RETURNING id")
    ).scalar_one()
    with_collection, without = (
        sa_sync_conn.execute(
            text(
                "INSERT INTO monographs (title, title_normalized, journal_id)"
                " VALUES (:t, lower(:t), :j) RETURNING id"
            ),
            {"t": title, "j": collection},
        ).scalar_one()
        for title, collection in (("Livre A", journal_id), ("Livre B", None))
    )
    repo = PgPublicationRepository(sa_sync_conn)
    assert repo.get_monograph_journal_ids([with_collection, without]) == {
        with_collection: journal_id,
        without: None,
    }
