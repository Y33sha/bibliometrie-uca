"""Tests d'intégration de `PgPublicationRepository.get_monograph_journal_ids`."""

from infrastructure.repositories.publication_repository import PgPublicationRepository
from tests.integration.helpers.journals import insert_journal, insert_monograph


def test_collection_de_chaque_monographie(sa_sync_conn):
    journal_id = insert_journal(sa_sync_conn, "C")
    with_collection, without = (
        insert_monograph(sa_sync_conn, title, journal_id=collection)
        for title, collection in (("Livre A", journal_id), ("Livre B", None))
    )
    repo = PgPublicationRepository(sa_sync_conn)
    assert repo.get_monograph_journal_ids([with_collection, without]) == {
        with_collection: journal_id,
        without: None,
    }
