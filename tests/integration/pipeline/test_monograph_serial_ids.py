"""Tests d'intégration de `consolidation.monograph_serial_ids`."""

from pipeline.transformation.publications.consolidation import monograph_serial_ids
from tests.integration.helpers.serials import insert_monograph, insert_serial


def test_collection_de_chaque_monographie(sa_sync_conn):
    serial_id = insert_serial(sa_sync_conn, "C")
    with_collection, without = (
        insert_monograph(sa_sync_conn, title, serial_id=collection)
        for title, collection in (("Livre A", serial_id), ("Livre B", None))
    )
    assert monograph_serial_ids(sa_sync_conn, [with_collection, without]) == {
        with_collection: serial_id,
        without: None,
    }
