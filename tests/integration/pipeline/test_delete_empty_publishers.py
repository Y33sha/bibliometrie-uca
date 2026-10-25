"""Tests d'intégration de la suppression des éditeurs vides (`delete_empty_publishers`)."""

from sqlalchemy import text

from pipeline.transformation.publishing.publishers.delete_empty_publishers import (
    delete_empty_publishers,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.serials import insert_publisher
from tests.integration.helpers.sources import insert_source_record


def test_l_editeur_d_un_enregistrement_source_ou_d_une_publication_reste(sa_sync_conn):
    of_record = insert_publisher(sa_sync_conn, "Armand Colin")
    of_publication = insert_publisher(sa_sync_conn, "Elsevier")
    empty = insert_publisher(sa_sync_conn, "Zenodo")
    insert_source_record(sa_sync_conn, publisher_id=of_record)
    publication_id = insert_publication(sa_sync_conn)
    sa_sync_conn.execute(
        text("UPDATE publications SET publisher_id = :p WHERE id = :id"),
        {"p": of_publication, "id": publication_id},
    )

    deleted = {publisher_id for publisher_id, _ in delete_empty_publishers(sa_sync_conn)}

    assert empty in deleted
    assert not {of_record, of_publication} & deleted
