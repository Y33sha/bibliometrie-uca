"""Tests d'intégration de `PublicationStore.get_monograph_journal_ids`."""

from pipeline.transformation.publications.reconciliation.refresh import PublicationStore
from tests.integration.helpers.journals import insert_journal, insert_monograph


def test_collection_de_chaque_monographie(sa_sync_conn):
    journal_id = insert_journal(sa_sync_conn, "C")
    with_collection, without = (
        insert_monograph(sa_sync_conn, title, journal_id=collection)
        for title, collection in (("Livre A", journal_id), ("Livre B", None))
    )
    repo = PublicationStore(sa_sync_conn)
    assert repo.get_monograph_journal_ids([with_collection, without]) == {
        with_collection: journal_id,
        without: None,
    }
