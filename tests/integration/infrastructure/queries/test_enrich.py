"""Tests d'intégration pour `infrastructure.queries.pipeline.enrich`."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from infrastructure.queries.pipeline.enrich import (
    fetch_journals_needing_apc,
    fetch_journals_needing_doaj_fetch,
    fetch_publications_with_doi,
)


def _create_pub(conn, doi=None, pub_year=2024, oa_status=None):
    return conn.execute(
        text("""
            INSERT INTO publications (title, pub_year, doc_type, doi, oa_status)
            VALUES ('X', :pub_year, 'article', :doi, CAST(:oa_status AS oa_type))
            RETURNING id
        """),
        {"pub_year": pub_year, "doi": doi, "oa_status": oa_status},
    ).scalar_one()


def _create_journal(conn, openalex_id=None, apc_amount=None):
    return conn.execute(
        text("""
            INSERT INTO journals (title, title_normalized, openalex_id, apc_amount)
            VALUES ('J', 'j', :openalex_id, :apc_amount) RETURNING id
        """),
        {"openalex_id": openalex_id, "apc_amount": apc_amount},
    ).scalar_one()


class TestFetchPublicationsWithDoi:
    def test_returns_tuples(self, sa_sync_conn):
        """La fonction retourne des tuples conformes au type hint, pour que
        les callers puissent unpacker `(pub_id, doi, status)`."""
        _create_pub(sa_sync_conn, doi="10.1/a", oa_status="gold")
        rows = fetch_publications_with_doi(sa_sync_conn)
        assert rows
        assert all(isinstance(r, tuple) for r in rows)
        # Forme du tuple : (id, doi, oa_status)
        for pub_id, doi, oa_status in rows:
            assert isinstance(pub_id, int)
            assert isinstance(doi, str)
            assert oa_status is None or isinstance(oa_status, str)

    def test_returns_only_pubs_with_doi(self, sa_sync_conn):
        with_doi = _create_pub(sa_sync_conn, doi="10.1/a")
        _create_pub(sa_sync_conn, doi=None)

        rows = fetch_publications_with_doi(sa_sync_conn)
        ids = [pid for pid, _doi, _oa in rows]
        assert with_doi in ids
        # Pas de pub sans DOI
        assert all(doi is not None for _pid, doi, _oa in rows)

    def test_sorts_by_pub_year_desc(self, sa_sync_conn):
        p_2020 = _create_pub(sa_sync_conn, doi="10.1/a", pub_year=2020)
        p_2024 = _create_pub(sa_sync_conn, doi="10.1/b", pub_year=2024)

        rows = fetch_publications_with_doi(sa_sync_conn)
        ordered_ids = [pid for pid, _, _ in rows if pid in (p_2020, p_2024)]
        # Plus récent en premier
        assert ordered_ids == [p_2024, p_2020]

    def test_respects_limit(self, sa_sync_conn):
        for i in range(3):
            _create_pub(sa_sync_conn, doi=f"10.1/{i}")
        rows = fetch_publications_with_doi(sa_sync_conn, limit=2)
        assert len(rows) == 2

    def test_limit_zero_is_unlimited(self, sa_sync_conn):
        _create_pub(sa_sync_conn, doi="10.1/a")
        _create_pub(sa_sync_conn, doi="10.1/b")
        rows = fetch_publications_with_doi(sa_sync_conn, limit=0)
        assert len(rows) >= 2

    def test_returns_oa_status(self, sa_sync_conn):
        _create_pub(sa_sync_conn, doi="10.1/a", oa_status="gold")
        rows = fetch_publications_with_doi(sa_sync_conn)
        assert any(oa == "gold" for _pid, _doi, oa in rows)


class TestFetchJournalsNeedingApc:
    def test_returns_tuples(self, sa_sync_conn):
        _create_journal(sa_sync_conn, openalex_id="S1", apc_amount=None)
        rows = fetch_journals_needing_apc(sa_sync_conn)
        assert rows
        assert all(isinstance(r, tuple) for r in rows)
        for journal_id, oa_id in rows:
            assert isinstance(journal_id, int)
            assert isinstance(oa_id, str)

    def test_returns_only_journals_with_openalex_and_no_apc(self, sa_sync_conn):
        needs = _create_journal(sa_sync_conn, openalex_id="S1", apc_amount=None)
        _create_journal(sa_sync_conn, openalex_id="S2", apc_amount=1500)  # déjà APC
        _create_journal(sa_sync_conn, openalex_id=None, apc_amount=None)  # pas d'openalex

        rows = fetch_journals_needing_apc(sa_sync_conn)
        ids = [jid for jid, _ in rows]
        assert needs in ids
        assert len(ids) == 1

    def test_respects_limit(self, sa_sync_conn):
        for i in range(3):
            _create_journal(sa_sync_conn, openalex_id=f"S{i}")
        rows = fetch_journals_needing_apc(sa_sync_conn, limit=2)
        assert len(rows) == 2


def _create_journal_with_issn(
    conn,
    *,
    issn=None,
    eissn=None,
    issnl=None,
    doaj_imported_at=None,
):
    return conn.execute(
        text("""
            INSERT INTO journals (title, title_normalized, issn, eissn, issnl, doaj_imported_at)
            VALUES ('J', 'j', :issn, :eissn, :issnl, :imported_at)
            RETURNING id
        """),
        {
            "issn": issn,
            "eissn": eissn,
            "issnl": issnl,
            "imported_at": doaj_imported_at,
        },
    ).scalar_one()


class TestFetchJournalsNeedingDoajFetch:
    def test_returns_tuples_of_id_and_issns(self, sa_sync_conn):
        jid = _create_journal_with_issn(sa_sync_conn, issn="1111-1111", eissn="2222-2222")
        rows = fetch_journals_needing_doaj_fetch(sa_sync_conn, stale_days=30)
        ours = [r for r in rows if r[0] == jid]
        assert ours == [(jid, "1111-1111", "2222-2222", None)]

    def test_excludes_journals_with_no_issn(self, sa_sync_conn):
        jid = _create_journal_with_issn(sa_sync_conn)  # tous NULL
        rows = fetch_journals_needing_doaj_fetch(sa_sync_conn, stale_days=30)
        assert jid not in [r[0] for r in rows]

    def test_includes_when_imported_at_is_null(self, sa_sync_conn):
        jid = _create_journal_with_issn(sa_sync_conn, issn="3333-3333")
        rows = fetch_journals_needing_doaj_fetch(sa_sync_conn, stale_days=30)
        assert jid in [r[0] for r in rows]

    def test_excludes_recently_imported(self, sa_sync_conn):
        recent = datetime.now(UTC) - timedelta(days=5)
        jid = _create_journal_with_issn(sa_sync_conn, issn="4444-4444", doaj_imported_at=recent)
        rows = fetch_journals_needing_doaj_fetch(sa_sync_conn, stale_days=30)
        assert jid not in [r[0] for r in rows]

    def test_includes_stale_beyond_window(self, sa_sync_conn):
        old = datetime.now(UTC) - timedelta(days=45)
        jid = _create_journal_with_issn(sa_sync_conn, issn="5555-5555", doaj_imported_at=old)
        rows = fetch_journals_needing_doaj_fetch(sa_sync_conn, stale_days=30)
        assert jid in [r[0] for r in rows]

    def test_stale_days_is_configurable(self, sa_sync_conn):
        recent = datetime.now(UTC) - timedelta(days=10)
        jid = _create_journal_with_issn(sa_sync_conn, issn="6666-6666", doaj_imported_at=recent)
        # Fenêtre 30j : exclu (récent)
        rows30 = fetch_journals_needing_doaj_fetch(sa_sync_conn, stale_days=30)
        assert jid not in [r[0] for r in rows30]
        # Fenêtre 5j : inclus (10j > 5j → stale)
        rows5 = fetch_journals_needing_doaj_fetch(sa_sync_conn, stale_days=5)
        assert jid in [r[0] for r in rows5]

    def test_respects_limit(self, sa_sync_conn):
        for i in range(3):
            _create_journal_with_issn(sa_sync_conn, issn=f"777{i}-000{i}")
        rows = fetch_journals_needing_doaj_fetch(sa_sync_conn, stale_days=30, limit=2)
        assert len(rows) == 2
