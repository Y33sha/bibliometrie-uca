"""Tests d'intégration pour `infrastructure.db.queries.enrich`."""

from sqlalchemy import text

from infrastructure.db.queries.enrich import (
    fetch_journals_needing_apc,
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
