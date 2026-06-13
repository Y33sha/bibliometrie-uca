"""Tests d'intégration de l'import du dump DOAJ (`run_import_doaj_dump`)."""

import logging

from sqlalchemy import text

from application.pipeline.publishers_journals.import_journals_from_doaj_dump import (
    run_import_doaj_dump,
)
from infrastructure.queries.pipeline.enrich import PgEnrichQueries
from infrastructure.repositories import journal_repository


def _create_journal(conn, *, issn=None, eissn=None):
    return conn.execute(
        text(
            "INSERT INTO journals (title, title_normalized, issn, eissn) "
            "VALUES ('J', 'j', :issn, :eissn) RETURNING id"
        ),
        {"issn": issn, "eissn": eissn},
    ).scalar_one()


def _row(issn="", eissn="", **extra):
    r = {
        "Journal ISSN (print version)": issn,
        "Journal EISSN (online version)": eissn,
    }
    r.update(extra)
    return r


def _run(conn, rows, *, dry_run=False):
    # commit=False : le fixture sa_sync_conn est une transaction rollbackée.
    return run_import_doaj_dump(
        conn,
        PgEnrichQueries(),
        logging.getLogger("test"),
        journal_repo=journal_repository(conn),
        rows=rows,
        dry_run=dry_run,
        commit=False,
    )


def _is_in_doaj(conn, jid):
    return conn.execute(
        text("SELECT is_in_doaj FROM journals WHERE id = :id"), {"id": jid}
    ).scalar_one()


class TestImportDoajDump:
    def test_matches_by_issn_and_writes_payload(self, sa_sync_conn):
        jid = _create_journal(sa_sync_conn, issn="1234-5678")
        stats = _run(sa_sync_conn, [_row(issn="1234-5678", **{"Journal title": "Foo"})])
        assert stats.matched == 1
        row = sa_sync_conn.execute(
            text("SELECT is_in_doaj, doaj_payload FROM journals WHERE id = :id"), {"id": jid}
        ).one()
        assert row.is_in_doaj is True
        assert row.doaj_payload["Journal title"] == "Foo"

    def test_matches_on_eissn_when_print_absent(self, sa_sync_conn):
        jid = _create_journal(sa_sync_conn, eissn="2222-3333")
        stats = _run(sa_sync_conn, [_row(eissn="2222-3333")])
        assert stats.matched == 1
        assert _is_in_doaj(sa_sync_conn, jid) is True

    def test_reset_clears_journals_absent_from_dump(self, sa_sync_conn):
        # Un journal marqué is_in_doaj mais absent du dump repasse à FALSE.
        jid = _create_journal(sa_sync_conn, issn="9999-9999")
        sa_sync_conn.execute(
            text("UPDATE journals SET is_in_doaj = TRUE WHERE id = :id"), {"id": jid}
        )
        _run(sa_sync_conn, [_row(issn="0000-0000")])  # dump sans notre ISSN
        assert _is_in_doaj(sa_sync_conn, jid) is False

    def test_orphan_rows_counted_not_matched(self, sa_sync_conn):
        stats = _run(sa_sync_conn, [_row(issn="5555-5555")])  # ISSN inconnu en local
        assert stats.orphan_rows == 1
        assert stats.matched == 0

    def test_dry_run_counts_but_writes_nothing(self, sa_sync_conn):
        jid = _create_journal(sa_sync_conn, issn="1234-5678")
        stats = _run(sa_sync_conn, [_row(issn="1234-5678")], dry_run=True)
        assert stats.matched == 1  # compté
        assert _is_in_doaj(sa_sync_conn, jid) is False  # mais rien écrit
