"""Tests d'intégration pour `infrastructure.queries.pipeline.enrich`."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from infrastructure.queries.pipeline.enrich import (
    doaj_last_import_at,
    fetch_journal_issn_index,
    fetch_journals_of_unknown_type,
    fetch_publications_with_doi,
    reset_is_in_doaj,
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


def _set_checked(conn, pub_id, days_ago):
    conn.execute(
        text(
            "UPDATE publications SET unpaywall_checked_at = now() - make_interval(days => :d) "
            "WHERE id = :id"
        ),
        {"d": days_ago, "id": pub_id},
    )


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

    def test_sorts_never_checked_first(self, sa_sync_conn):
        # Tri `unpaywall_checked_at NULLS FIRST` : les jamais-vérifiés d'abord.
        checked = _create_pub(sa_sync_conn, doi="10.1/a", oa_status="closed")
        _set_checked(sa_sync_conn, checked, days_ago=1)
        never = _create_pub(sa_sync_conn, doi="10.1/b", oa_status="closed")
        rows = fetch_publications_with_doi(sa_sync_conn)
        ordered = [pid for pid, _, _ in rows if pid in (checked, never)]
        assert ordered[0] == never

    def test_staleness_excludes_stable_and_fresh(self, sa_sync_conn):
        # jamais vérifié → inclus (1× même gold, OpenAlex se trompe parfois)
        never_gold = _create_pub(sa_sync_conn, doi="10.1/n", oa_status="gold")
        # gold vérifié → exclu (stable, plus jamais re-vérifié)
        gold_checked = _create_pub(sa_sync_conn, doi="10.1/g", oa_status="gold")
        _set_checked(sa_sync_conn, gold_checked, days_ago=999)
        # closed vérifié récemment → exclu (frais)
        closed_fresh = _create_pub(sa_sync_conn, doi="10.1/cf", oa_status="closed")
        _set_checked(sa_sync_conn, closed_fresh, days_ago=1)
        # closed vérifié il y a longtemps → inclus (périmé)
        closed_stale = _create_pub(sa_sync_conn, doi="10.1/cs", oa_status="closed")
        _set_checked(sa_sync_conn, closed_stale, days_ago=999)

        ids = {pid for pid, _, _ in fetch_publications_with_doi(sa_sync_conn, staleness_days=30)}
        assert never_gold in ids
        assert gold_checked not in ids
        assert closed_fresh not in ids
        assert closed_stale in ids

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


class TestFetchJournalsOfUnknownType:
    def test_returns_tuples(self, sa_sync_conn):
        _create_journal(sa_sync_conn, openalex_id="S1")  # journal_type 'unknown' par défaut
        rows = fetch_journals_of_unknown_type(sa_sync_conn)
        assert rows
        for journal_id, oa_id in rows:
            assert isinstance(journal_id, int)
            assert isinstance(oa_id, str)

    def test_returns_only_unknown_type_with_openalex(self, sa_sync_conn):
        needs = _create_journal(sa_sync_conn, openalex_id="S1")  # unknown + openalex
        typed = _create_journal(sa_sync_conn, openalex_id="S2")
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": typed}
        )
        _create_journal(sa_sync_conn, openalex_id=None)  # pas d'openalex_id

        ids = [jid for jid, _ in fetch_journals_of_unknown_type(sa_sync_conn)]
        assert needs in ids
        assert typed not in ids  # déjà typé → exclu

    def test_respects_limit(self, sa_sync_conn):
        for i in range(3):
            _create_journal(sa_sync_conn, openalex_id=f"S{i}")
        assert len(fetch_journals_of_unknown_type(sa_sync_conn, limit=2)) == 2


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


class TestDoajDumpQueries:
    def test_issn_index_exposes_all_issn_fields(self, sa_sync_conn):
        jid = _create_journal_with_issn(sa_sync_conn, issn="1111-1111", eissn="2222-2222")
        ours = [r for r in fetch_journal_issn_index(sa_sync_conn) if r.id == jid]
        assert ours and ours[0].issn == "1111-1111" and ours[0].eissn == "2222-2222"

    def test_issn_index_excludes_journals_with_no_issn(self, sa_sync_conn):
        jid = _create_journal_with_issn(sa_sync_conn)  # tous NULL
        assert jid not in [r.id for r in fetch_journal_issn_index(sa_sync_conn)]

    def test_reset_is_in_doaj_clears_true_flags(self, sa_sync_conn):
        jid = _create_journal_with_issn(sa_sync_conn, issn="3333-3333")
        sa_sync_conn.execute(
            text("UPDATE journals SET is_in_doaj = TRUE WHERE id = :id"), {"id": jid}
        )
        assert reset_is_in_doaj(sa_sync_conn) >= 1
        val = sa_sync_conn.execute(
            text("SELECT is_in_doaj FROM journals WHERE id = :id"), {"id": jid}
        ).scalar_one()
        assert val is False

    def test_last_import_at_returns_a_value_when_imported(self, sa_sync_conn):
        d = datetime.now(UTC) - timedelta(days=3)
        _create_journal_with_issn(sa_sync_conn, issn="4444-4444", doaj_imported_at=d)
        last = doaj_last_import_at(sa_sync_conn)
        assert last is not None and last >= d - timedelta(seconds=1)
