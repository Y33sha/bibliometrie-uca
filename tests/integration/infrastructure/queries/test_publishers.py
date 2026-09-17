"""Tests d'intégration de `PgPublisherGatewayQueries` : suppression des éditeurs vides."""

from __future__ import annotations

from sqlalchemy import text

from infrastructure.pipeline.publishers import PgPublisherGatewayQueries


def _publisher(conn, name: str) -> int:
    return conn.execute(
        text("INSERT INTO publishers (name, name_normalized) VALUES (:n, lower(:n)) RETURNING id"),
        {"n": name},
    ).scalar_one()


def _journal(conn, publisher_id: int | None, title: str = "Revue") -> int:
    return conn.execute(
        text(
            "INSERT INTO journals (title, title_normalized, publisher_id)"
            " VALUES (:t, lower(:t), :p) RETURNING id"
        ),
        {"t": title, "p": publisher_id},
    ).scalar_one()


class TestDeleteEmptyPublishers:
    def test_seuls_les_editeurs_sans_rien_sont_supprimes(self, sa_sync_conn):
        empty = _publisher(sa_sync_conn, "Elsevier [1981-....]")
        with_journal = _publisher(sa_sync_conn, "Elsevier BV")
        _journal(sa_sync_conn, with_journal)
        with_prefix = _publisher(sa_sync_conn, "Informa UK Limited")
        sa_sync_conn.execute(
            text(
                "INSERT INTO doi_prefixes (prefix, ra, publisher_id) VALUES ('10.99998', 'Crossref', :p)"
            ),
            {"p": with_prefix},
        )
        with_form = _publisher(
            sa_sync_conn, "Elsevier on behalf of the American College of Cardiology"
        )
        other_journal = _journal(
            sa_sync_conn, None, "Journal of the American College of Cardiology"
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO journal_name_forms (journal_id, form_normalized, publisher_id)"
                " VALUES (:j, 'journal of the american college of cardiology', :p)"
            ),
            {"j": other_journal, "p": with_form},
        )

        deleted = PgPublisherGatewayQueries(sa_sync_conn).delete_empty_publishers()

        ids = {publisher_id for publisher_id, _ in deleted}
        assert empty in ids
        assert not ids & {with_journal, with_prefix, with_form}
