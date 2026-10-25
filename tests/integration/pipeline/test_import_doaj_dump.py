"""Tests d'intégration de l'import du dump DOAJ (`run_import_doaj_dump`)."""

import logging

from sqlalchemy import text

from pipeline.transformation.publishing.serials.enrich_serials_from_doaj import (
    run_import_doaj_dump,
)
from tests.integration.helpers.serials import insert_serial, insert_serial_issn


def _create_serial(conn, *, issn=None, eissn=None):
    serial_id = insert_serial(conn, "J")
    for value, support in ((issn, "print"), (eissn, "electronic")):
        if value:
            insert_serial_issn(conn, serial_id, issn=value, support=support)
    return serial_id


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
        rows=rows,
        dry_run=dry_run,
        commit=False,
    )


def _is_in_doaj(conn, jid):
    return conn.execute(
        text("SELECT is_in_doaj FROM serials WHERE id = :id"), {"id": jid}
    ).scalar_one()


class TestImportDoajDump:
    def test_matches_by_issn_and_writes_payload(self, sa_sync_conn):
        jid = _create_serial(sa_sync_conn, issn="0028-0836")
        stats = _run(sa_sync_conn, [_row(issn="0028-0836", **{"Journal title": "Foo"})])
        assert stats.matched == 1
        row = sa_sync_conn.execute(
            text("SELECT is_in_doaj, doaj_payload FROM serials WHERE id = :id"), {"id": jid}
        ).one()
        assert row.is_in_doaj is True
        assert row.doaj_payload["Journal title"] == "Foo"

    def test_matches_on_eissn_when_print_absent(self, sa_sync_conn):
        jid = _create_serial(sa_sync_conn, eissn="1476-4687")
        stats = _run(sa_sync_conn, [_row(eissn="1476-4687")])
        assert stats.matched == 1
        assert _is_in_doaj(sa_sync_conn, jid) is True

    def test_matches_on_normalized_issn(self, sa_sync_conn):
        """Un ISSN du dump est normalisé avant d'être comparé aux ISSN des revues."""
        jid = _create_serial(sa_sync_conn, issn="0071-190X")
        stats = _run(sa_sync_conn, [_row(issn="0071190X")])
        assert stats.matched == 1
        assert _is_in_doaj(sa_sync_conn, jid) is True

    def test_invalid_issn_counted_as_absent(self, sa_sync_conn):
        stats = _run(sa_sync_conn, [_row(issn="1234-5678")])  # clé de contrôle fausse
        assert stats.no_issn_rows == 1

    def test_reset_clears_serials_absent_from_dump(self, sa_sync_conn):
        # Un journal marqué is_in_doaj mais absent du dump repasse à FALSE.
        jid = _create_serial(sa_sync_conn, issn="0036-8075")
        _create_serial(sa_sync_conn, issn="0028-0836")
        sa_sync_conn.execute(
            text("UPDATE serials SET is_in_doaj = TRUE WHERE id = :id"), {"id": jid}
        )
        _run(sa_sync_conn, [_row(issn="0028-0836")])  # dump sans notre premier ISSN
        assert _is_in_doaj(sa_sync_conn, jid) is False

    def test_dump_without_recognized_serial_changes_nothing(self, sa_sync_conn):
        """Aucune revue reconnue (format du dump changé, par exemple) : les revues restent en l'état."""
        jid = _create_serial(sa_sync_conn, issn="0036-8075")
        sa_sync_conn.execute(
            text("UPDATE serials SET is_in_doaj = TRUE WHERE id = :id"), {"id": jid}
        )
        stats = _run(sa_sync_conn, [{"Colonne renommée": "0036-8075"}])
        assert stats.matched == 0
        assert _is_in_doaj(sa_sync_conn, jid) is True

    def test_orphan_rows_counted_not_matched(self, sa_sync_conn):
        stats = _run(sa_sync_conn, [_row(issn="2049-3630")])  # ISSN inconnu en local
        assert stats.orphan_rows == 1
        assert stats.matched == 0

    def test_dry_run_counts_but_writes_nothing(self, sa_sync_conn):
        jid = _create_serial(sa_sync_conn, issn="0028-0836")
        stats = _run(sa_sync_conn, [_row(issn="0028-0836")], dry_run=True)
        assert stats.matched == 1  # compté
        assert _is_in_doaj(sa_sync_conn, jid) is False  # mais rien écrit
