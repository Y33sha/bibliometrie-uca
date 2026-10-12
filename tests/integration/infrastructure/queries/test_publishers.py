"""Tests d'intégration de `PublisherGatewayQueries` : suppression des éditeurs vides."""

from __future__ import annotations

from pipeline.containers.publishers import PublisherGatewayQueries
from tests.integration.helpers.journals import (
    insert_doi_prefix,
    insert_journal,
    insert_journal_name_form,
    insert_monograph,
    insert_publisher,
)


class TestDeleteEmptyPublishers:
    def test_seuls_les_editeurs_sans_rien_sont_supprimes(self, sa_sync_conn):
        empty = insert_publisher(sa_sync_conn, "Elsevier [1981-....]")
        with_journal = insert_publisher(sa_sync_conn, "Elsevier BV")
        insert_journal(sa_sync_conn, "Revue", publisher_id=with_journal)
        with_prefix = insert_publisher(sa_sync_conn, "Informa UK Limited")
        insert_doi_prefix(sa_sync_conn, "10.99998", ra="Crossref", publisher_id=with_prefix)
        with_form = insert_publisher(
            sa_sync_conn, "Elsevier on behalf of the American College of Cardiology"
        )
        other_journal = insert_journal(
            sa_sync_conn, "Journal of the American College of Cardiology"
        )
        insert_journal_name_form(
            sa_sync_conn,
            other_journal,
            form_normalized="journal of the american college of cardiology",
            publisher_id=with_form,
        )

        with_monograph = insert_publisher(sa_sync_conn, "Presses universitaires de Rennes")
        insert_monograph(sa_sync_conn, "Livre", publisher_id=with_monograph)

        deleted = PublisherGatewayQueries(sa_sync_conn).delete_empty_publishers()

        ids = {publisher_id for publisher_id, _ in deleted}
        assert empty in ids
        assert not ids & {with_journal, with_prefix, with_form, with_monograph}
