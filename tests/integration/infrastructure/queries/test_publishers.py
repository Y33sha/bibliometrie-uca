"""Tests d'intégration de la suppression des éditeurs vides."""

from __future__ import annotations

from sqlalchemy import text

from pipeline.transformation.publishing.publishers.delete_empty_publishers import (
    delete_empty_publishers,
)
from tests.integration.helpers.serials import (
    insert_doi_prefix,
    insert_monograph,
    insert_publisher,
    insert_serial,
)


class TestDeleteEmptyPublishers:
    def test_seuls_les_editeurs_sans_rien_sont_supprimes(self, sa_sync_conn):
        empty = insert_publisher(sa_sync_conn, "Elsevier [1981-....]")
        with_serial = insert_publisher(sa_sync_conn, "Elsevier BV")
        insert_serial(sa_sync_conn, "Revue", publisher_id=with_serial)
        with_prefix = insert_publisher(sa_sync_conn, "Informa UK Limited")
        insert_doi_prefix(sa_sync_conn, "10.99998", ra="Crossref", publisher_id=with_prefix)
        with_form = insert_publisher(
            sa_sync_conn, "Elsevier on behalf of the American College of Cardiology"
        )
        other_serial = insert_serial(sa_sync_conn, "Journal of the American College of Cardiology")
        sa_sync_conn.execute(
            text(
                "INSERT INTO serial_title_decisions (title_normalized, publisher_id, serial_id)"
                " VALUES ('journal of the american college of cardiology', :p, :s)"
            ),
            {"p": with_form, "s": other_serial},
        )

        with_monograph = insert_publisher(sa_sync_conn, "Presses universitaires de Rennes")
        insert_monograph(sa_sync_conn, "Livre", publisher_id=with_monograph)

        deleted = delete_empty_publishers(sa_sync_conn)

        ids = {publisher_id for publisher_id, _ in deleted}
        assert empty in ids
        assert not ids & {with_serial, with_prefix, with_form, with_monograph}
