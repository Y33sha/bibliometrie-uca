"""Tests d'intégration de l'import du dump DOAJ (`run_import_doaj_dump`)."""

import logging

from sqlalchemy import text

from application.pipeline.publishers_journals.import_journals_from_doaj_dump import (
    run_import_doaj_dump,
)
from infrastructure.pipeline.journals import PgJournalGatewayQueries


def _create_journal(conn, *, issn=None, eissn=None):
    journal_id = conn.execute(
        text("INSERT INTO journals (title, title_normalized) VALUES ('J', 'j') RETURNING id")
    ).scalar_one()
    for value, support in ((issn, "print"), (eissn, "electronic")):
        if value:
            conn.execute(
                text(
                    "INSERT INTO journal_issns (issn, journal_id, support)"
                    " VALUES (:i, :j, CAST(:s AS issn_support))"
                ),
                {"i": value, "j": journal_id, "s": support},
            )
    return journal_id


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
        logging.getLogger("test"),
        journal_repo=PgJournalGatewayQueries(conn),
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
        jid = _create_journal(sa_sync_conn, issn="0028-0836")
        stats = _run(sa_sync_conn, [_row(issn="0028-0836", **{"Journal title": "Foo"})])
        assert stats.matched == 1
        row = sa_sync_conn.execute(
            text("SELECT is_in_doaj, doaj_payload FROM journals WHERE id = :id"), {"id": jid}
        ).one()
        assert row.is_in_doaj is True
        assert row.doaj_payload["Journal title"] == "Foo"

    def test_matches_on_eissn_when_print_absent(self, sa_sync_conn):
        jid = _create_journal(sa_sync_conn, eissn="1476-4687")
        stats = _run(sa_sync_conn, [_row(eissn="1476-4687")])
        assert stats.matched == 1
        assert _is_in_doaj(sa_sync_conn, jid) is True

    def test_matches_on_normalized_issn(self, sa_sync_conn):
        """Un ISSN du dump est normalisé avant d'être comparé aux ISSN des revues."""
        jid = _create_journal(sa_sync_conn, issn="0071-190X")
        stats = _run(sa_sync_conn, [_row(issn="0071190X")])
        assert stats.matched == 1
        assert _is_in_doaj(sa_sync_conn, jid) is True

    def test_invalid_issn_counted_as_absent(self, sa_sync_conn):
        stats = _run(sa_sync_conn, [_row(issn="1234-5678")])  # clé de contrôle fausse
        assert stats.no_issn_rows == 1

    def test_reset_clears_journals_absent_from_dump(self, sa_sync_conn):
        # Un journal marqué is_in_doaj mais absent du dump repasse à FALSE.
        jid = _create_journal(sa_sync_conn, issn="0036-8075")
        sa_sync_conn.execute(
            text("UPDATE journals SET is_in_doaj = TRUE WHERE id = :id"), {"id": jid}
        )
        _run(sa_sync_conn, [_row(issn="1095-9203")])  # dump sans notre ISSN
        assert _is_in_doaj(sa_sync_conn, jid) is False

    def test_orphan_rows_counted_not_matched(self, sa_sync_conn):
        stats = _run(sa_sync_conn, [_row(issn="2049-3630")])  # ISSN inconnu en local
        assert stats.orphan_rows == 1
        assert stats.matched == 0

    def test_dry_run_counts_but_writes_nothing(self, sa_sync_conn):
        jid = _create_journal(sa_sync_conn, issn="0028-0836")
        stats = _run(sa_sync_conn, [_row(issn="0028-0836")], dry_run=True)
        assert stats.matched == 1  # compté
        assert _is_in_doaj(sa_sync_conn, jid) is False  # mais rien écrit
