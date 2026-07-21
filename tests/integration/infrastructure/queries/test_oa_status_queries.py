"""Tests d'intégration pour `infrastructure.queries.pipeline.oa_status` : la file de vérification Unpaywall et les compteurs du bilan de phase."""

from sqlalchemy import text

from infrastructure.queries.pipeline.oa_status import (
    count_publications_by_oa_status,
    count_stale_publications,
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


def _set_checked(conn, pub_id, days_ago):
    conn.execute(
        text(
            "UPDATE publications SET unpaywall_checked_at = now() - make_interval(days => :d) "
            "WHERE id = :id"
        ),
        {"d": days_ago, "id": pub_id},
    )


class TestFetchPublicationsWithDoi:
    def test_returns_tuples(self, sa_sync_conn):
        """La fonction retourne des `PublicationOaCheck`, pour que les callers puissent unpacker
        `(pub_id, doi, oa_status, has_open_deposit)`."""
        _create_pub(sa_sync_conn, doi="10.1/a", oa_status="gold")
        rows = fetch_publications_with_doi(sa_sync_conn)
        assert rows
        assert all(isinstance(r, tuple) for r in rows)
        # Forme du tuple : (id, doi, oa_status, has_open_deposit)
        for pub_id, doi, oa_status, has_open_deposit in rows:
            assert isinstance(pub_id, int)
            assert isinstance(doi, str)
            assert oa_status is None or isinstance(oa_status, str)
            assert isinstance(has_open_deposit, bool)

    def test_returns_only_pubs_with_doi(self, sa_sync_conn):
        with_doi = _create_pub(sa_sync_conn, doi="10.1/a")
        _create_pub(sa_sync_conn, doi=None)

        rows = fetch_publications_with_doi(sa_sync_conn)
        ids = [r.id for r in rows]
        assert with_doi in ids
        # Pas de pub sans DOI
        assert all(r.doi is not None for r in rows)

    def test_sorts_never_checked_first(self, sa_sync_conn):
        # Tri `unpaywall_checked_at NULLS FIRST` : les jamais-vérifiés d'abord.
        checked = _create_pub(sa_sync_conn, doi="10.1/a", oa_status="closed")
        _set_checked(sa_sync_conn, checked, days_ago=1)
        never = _create_pub(sa_sync_conn, doi="10.1/b", oa_status="closed")
        rows = fetch_publications_with_doi(sa_sync_conn)
        ordered = [r.id for r in rows if r.id in (checked, never)]
        assert ordered[0] == never

    def test_staleness_excludes_only_the_fresh(self, sa_sync_conn):
        """La péremption ne regarde que la date : le statut courant n'exempte personne."""
        # jamais interrogé → inclus
        never_gold = _create_pub(sa_sync_conn, doi="10.1/n", oa_status="gold")
        # gold périmé → inclus : son statut peut venir d'une source, sans qu'Unpaywall
        # ait jamais confirmé (publication absente de son index à l'interrogation)
        gold_stale = _create_pub(sa_sync_conn, doi="10.1/g", oa_status="gold")
        _set_checked(sa_sync_conn, gold_stale, days_ago=999)
        # gold interrogé récemment → exclu (frais)
        gold_fresh = _create_pub(sa_sync_conn, doi="10.1/gf", oa_status="gold")
        _set_checked(sa_sync_conn, gold_fresh, days_ago=1)
        # closed interrogé récemment → exclu (frais)
        closed_fresh = _create_pub(sa_sync_conn, doi="10.1/cf", oa_status="closed")
        _set_checked(sa_sync_conn, closed_fresh, days_ago=1)
        # closed périmé → inclus
        closed_stale = _create_pub(sa_sync_conn, doi="10.1/cs", oa_status="closed")
        _set_checked(sa_sync_conn, closed_stale, days_ago=999)

        ids = {r.id for r in fetch_publications_with_doi(sa_sync_conn, staleness_days=30)}
        assert never_gold in ids
        assert gold_stale in ids
        assert gold_fresh not in ids
        assert closed_fresh not in ids
        assert closed_stale in ids

    def test_respects_limit(self, sa_sync_conn):
        for i in range(3):
            _create_pub(sa_sync_conn, doi=f"10.1/{i}")
        rows = fetch_publications_with_doi(sa_sync_conn, limit=2)
        assert len(rows) == 2

    def test_returns_oa_status(self, sa_sync_conn):
        _create_pub(sa_sync_conn, doi="10.1/a", oa_status="gold")
        rows = fetch_publications_with_doi(sa_sync_conn)
        assert any(r.oa_status == "gold" for r in rows)


class TestCounters:
    def test_count_stale_publications_matches_the_queue(self, sa_sync_conn):
        """Même prédicat que `fetch_publications_with_doi`, sans cap : le backlog avant plafonnement."""
        _create_pub(sa_sync_conn, doi="10.1/a", oa_status="closed")
        _create_pub(sa_sync_conn, doi=None)  # sans DOI → hors file
        assert count_stale_publications(sa_sync_conn) == 1

    def test_count_publications_by_oa_status_groups_the_stock(self, sa_sync_conn):
        _create_pub(sa_sync_conn, doi="10.1/a", oa_status="gold")
        _create_pub(sa_sync_conn, doi="10.1/b", oa_status="gold")
        _create_pub(sa_sync_conn, doi="10.1/c", oa_status="closed")
        assert count_publications_by_oa_status(sa_sync_conn) == {"gold": 2, "closed": 1}
