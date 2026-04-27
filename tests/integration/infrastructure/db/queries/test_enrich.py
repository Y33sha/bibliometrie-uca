"""Tests d'intégration pour `infrastructure.db.queries.enrich`."""

from infrastructure.db.queries.enrich import (
    fetch_journals_needing_apc,
    fetch_publications_with_doi,
)


def _create_pub(db, doi=None, pub_year=2024, oa_status=None):
    db.execute(
        """
        INSERT INTO publications (title, pub_year, doc_type, doi, oa_status)
        VALUES ('X', %s, 'article', %s, %s::oa_type)
        RETURNING id
        """,
        (pub_year, doi, oa_status),
    )
    return db.fetchone()["id"]


def _create_journal(db, openalex_id=None, apc_amount=None):
    db.execute(
        """
        INSERT INTO journals (title, title_normalized, openalex_id, apc_amount)
        VALUES ('J', 'j', %s, %s) RETURNING id
        """,
        (openalex_id, apc_amount),
    )
    return db.fetchone()["id"]


class TestFetchPublicationsWithDoi:
    def test_returns_tuples_with_dict_cursor(self, db):
        """La fixture `db` est un curseur dict_row (cas pipeline). La
        fonction doit malgré tout retourner des tuples conformes au type
        hint, pour que les callers puissent unpacker `(pub_id, doi, status)`."""
        _create_pub(db, doi="10.1/a", oa_status="gold")
        rows = fetch_publications_with_doi(db)
        assert rows
        assert all(isinstance(r, tuple) for r in rows)
        # Forme du tuple : (id, doi, oa_status)
        for pub_id, doi, oa_status in rows:
            assert isinstance(pub_id, int)
            assert isinstance(doi, str)
            assert oa_status is None or isinstance(oa_status, str)

    def test_returns_only_pubs_with_doi(self, db):
        with_doi = _create_pub(db, doi="10.1/a")
        _create_pub(db, doi=None)

        rows = fetch_publications_with_doi(db)
        ids = [pid for pid, _doi, _oa in rows]
        assert with_doi in ids
        # Pas de pub sans DOI
        assert all(doi is not None for _pid, doi, _oa in rows)

    def test_sorts_by_pub_year_desc(self, db):
        p_2020 = _create_pub(db, doi="10.1/a", pub_year=2020)
        p_2024 = _create_pub(db, doi="10.1/b", pub_year=2024)

        rows = fetch_publications_with_doi(db)
        ordered_ids = [pid for pid, _, _ in rows if pid in (p_2020, p_2024)]
        # Plus récent en premier
        assert ordered_ids == [p_2024, p_2020]

    def test_respects_limit(self, db):
        for i in range(3):
            _create_pub(db, doi=f"10.1/{i}")
        rows = fetch_publications_with_doi(db, limit=2)
        assert len(rows) == 2

    def test_limit_zero_is_unlimited(self, db):
        _create_pub(db, doi="10.1/a")
        _create_pub(db, doi="10.1/b")
        rows = fetch_publications_with_doi(db, limit=0)
        assert len(rows) >= 2

    def test_returns_oa_status(self, db):
        _create_pub(db, doi="10.1/a", oa_status="gold")
        rows = fetch_publications_with_doi(db)
        assert any(oa == "gold" for _pid, _doi, oa in rows)


class TestFetchJournalsNeedingApc:
    def test_returns_tuples_with_dict_cursor(self, db):
        """Même invariant que `fetch_publications_with_doi` — voir ci-dessus."""
        _create_journal(db, openalex_id="S1", apc_amount=None)
        rows = fetch_journals_needing_apc(db)
        assert rows
        assert all(isinstance(r, tuple) for r in rows)
        for journal_id, oa_id in rows:
            assert isinstance(journal_id, int)
            assert isinstance(oa_id, str)

    def test_returns_only_journals_with_openalex_and_no_apc(self, db):
        needs = _create_journal(db, openalex_id="S1", apc_amount=None)
        _create_journal(db, openalex_id="S2", apc_amount=1500)  # déjà APC
        _create_journal(db, openalex_id=None, apc_amount=None)  # pas d'openalex

        rows = fetch_journals_needing_apc(db)
        ids = [jid for jid, _ in rows]
        assert needs in ids
        assert len(ids) == 1

    def test_respects_limit(self, db):
        for i in range(3):
            _create_journal(db, openalex_id=f"S{i}")
        rows = fetch_journals_needing_apc(db, limit=2)
        assert len(rows) == 2
