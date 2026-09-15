"""Tests d'intégration de `PgJournalGatewayQueries` : files d'enrichissement et index DOAJ."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from infrastructure.pipeline.journals import PgJournalGatewayQueries


@pytest.fixture
def repo(sa_sync_conn):
    return PgJournalGatewayQueries(sa_sync_conn)


def _create_journal(conn, *, openalex_id=None, issn=None, eissn=None, issnl=None, imported_at=None):
    return conn.execute(
        text("""
            INSERT INTO journals (title, title_normalized, openalex_id,
                                  issn, eissn, issnl, doaj_imported_at)
            VALUES ('J', 'j', :openalex_id, :issn, :eissn, :issnl, :imported_at)
            RETURNING id
        """),
        {
            "openalex_id": openalex_id,
            "issn": issn,
            "eissn": eissn,
            "issnl": issnl,
            "imported_at": imported_at,
        },
    ).scalar_one()


class TestSudocCheck:
    def test_queue_holds_unchecked_journals_with_an_issn(self, sa_sync_conn, repo):
        with_issn = _create_journal(sa_sync_conn, issn="0028-0836")
        without_issn = _create_journal(sa_sync_conn)
        rejected_only = _create_journal(sa_sync_conn)
        checked = _create_journal(sa_sync_conn, issn="1476-4687")
        sa_sync_conn.execute(
            text("UPDATE journals SET rejected_issns = '{1950-2051}' WHERE id = :id"),
            {"id": rejected_only},
        )
        sa_sync_conn.execute(
            text("UPDATE journals SET sudoc_checked_at = now() WHERE id = :id"), {"id": checked}
        )
        rows = {r.id: r for r in repo.find_journals_to_check_in_sudoc()}
        assert with_issn in rows
        assert rows[rejected_only].rejected_issns == ("1950-2051",)
        assert without_issn not in rows
        assert checked not in rows

    def test_record_writes_issns_and_date(self, sa_sync_conn, repo):
        journal_id = _create_journal(sa_sync_conn, issn="1476-4687", issnl="0028-0836")
        at = datetime(2026, 9, 15, tzinfo=UTC)
        repo.record_sudoc_check(
            journal_id,
            issn="0028-0836",
            eissn="1476-4687",
            issnl="0028-0836",
            rejected_issns=(),
            checked_at=at,
        )
        row = sa_sync_conn.execute(
            text(
                "SELECT issn, eissn, issnl, rejected_issns, sudoc_checked_at "
                "FROM journals WHERE id = :id"
            ),
            {"id": journal_id},
        ).one()
        assert tuple(row) == ("0028-0836", "1476-4687", "0028-0836", [], at)


class TestFindJournalsOfUnknownType:
    def test_returns_id_and_openalex_id(self, sa_sync_conn, repo):
        _create_journal(sa_sync_conn, openalex_id="S1")  # journal_type 'unknown' par défaut
        rows = repo.find_journals_of_unknown_type()
        assert rows
        for journal_id, oa_id in rows:
            assert isinstance(journal_id, int)
            assert isinstance(oa_id, str)

    def test_returns_only_unknown_type_with_openalex(self, sa_sync_conn, repo):
        needs = _create_journal(sa_sync_conn, openalex_id="S1")
        typed = _create_journal(sa_sync_conn, openalex_id="S2")
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": typed}
        )
        _create_journal(sa_sync_conn, openalex_id=None)  # pas d'openalex_id

        ids = [jid for jid, _ in repo.find_journals_of_unknown_type()]
        assert needs in ids
        assert typed not in ids  # déjà typé → sorti de la file

    def test_respects_limit(self, sa_sync_conn, repo):
        for i in range(3):
            _create_journal(sa_sync_conn, openalex_id=f"S{i}")
        assert len(repo.find_journals_of_unknown_type(limit=2)) == 2

    def test_limit_zero_is_unlimited(self, sa_sync_conn, repo):
        for i in range(2):
            _create_journal(sa_sync_conn, openalex_id=f"S{i}")
        assert len(repo.find_journals_of_unknown_type(limit=0)) >= 2


class TestJournalIssnIndex:
    def test_exposes_all_issn_fields(self, sa_sync_conn, repo):
        jid = _create_journal(sa_sync_conn, issn="1111-1111", eissn="2222-2222")
        ours = [r for r in repo.find_journal_issn_index() if r.id == jid]
        assert ours and ours[0].issn == "1111-1111" and ours[0].eissn == "2222-2222"

    def test_excludes_journals_with_no_issn(self, sa_sync_conn, repo):
        jid = _create_journal(sa_sync_conn)  # les trois formes nulles
        assert jid not in [r.id for r in repo.find_journal_issn_index()]


class TestDoajImport:
    def test_reset_is_in_doaj_clears_true_flags(self, sa_sync_conn, repo):
        jid = _create_journal(sa_sync_conn, issn="3333-3333")
        sa_sync_conn.execute(
            text("UPDATE journals SET is_in_doaj = TRUE WHERE id = :id"), {"id": jid}
        )
        assert repo.reset_is_in_doaj() >= 1
        assert (
            sa_sync_conn.execute(
                text("SELECT is_in_doaj FROM journals WHERE id = :id"), {"id": jid}
            ).scalar_one()
            is False
        )

    def test_last_import_at_returns_a_value_when_imported(self, sa_sync_conn, repo):
        d = datetime.now(UTC) - timedelta(days=3)
        _create_journal(sa_sync_conn, issn="4444-4444", imported_at=d)
        last = repo.doaj_last_import_at()
        assert last is not None and last >= d - timedelta(seconds=1)
