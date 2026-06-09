"""Tests d'intégration pour `infrastructure.queries.pipeline.merge`."""

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.queries.pipeline.merge import (
    fetch_hal_source_publications,
    fetch_source_publications_with_hal_external_id,
    find_nnt_duplicates,
    link_source_publication_to_publication,
)


def _create_pub(conn, doi=None, pub_year=2024):
    return conn.execute(
        text("""
            INSERT INTO publications (title, pub_year, doc_type, doi)
            VALUES ('X', :pub_year, 'article', :doi) RETURNING id
        """),
        {"pub_year": pub_year, "doi": doi},
    ).scalar_one()


def _create_sd(conn, source, source_id, pub_id, external_ids=None):
    stmt = text("""
        INSERT INTO source_publications (source, source_id, title, publication_id, external_ids)
        VALUES (:source, :source_id, 'X', :pub_id, :external_ids) RETURNING id
    """).bindparams(bindparam("external_ids", type_=JSONB))
    return conn.execute(
        stmt,
        {
            "source": source,
            "source_id": source_id,
            "pub_id": pub_id,
            "external_ids": external_ids or {},
        },
    ).scalar_one()


class TestFindNntDuplicates:
    def test_detects_nnt_pointing_to_two_publications(self, sa_sync_conn):
        p1 = _create_pub(sa_sync_conn)
        p2 = _create_pub(sa_sync_conn)
        _create_sd(sa_sync_conn, "hal", "h-1", p1, external_ids={"nnt": "2023UCFA0001"})
        _create_sd(sa_sync_conn, "theses", "t-1", p2, external_ids={"nnt": "2023UCFA0001"})

        dups = find_nnt_duplicates(sa_sync_conn)
        ours = [d for d in dups if d.nnt == "2023UCFA0001"]
        assert len(ours) == 1
        assert sorted(ours[0].pub_ids) == sorted([p1, p2])
        assert set(ours[0].sources) == {"hal", "theses"}

    def test_ignores_nnt_on_single_publication(self, sa_sync_conn):
        p1 = _create_pub(sa_sync_conn)
        _create_sd(sa_sync_conn, "hal", "h-2", p1, external_ids={"nnt": "UNIQUE_NNT"})

        dups = find_nnt_duplicates(sa_sync_conn)
        assert not any(d.nnt == "UNIQUE_NNT" for d in dups)


class TestFetchSourcePublicationsWithHalExternalId:
    def test_returns_openalex_and_scanr_with_hal_external(self, sa_sync_conn):
        p = _create_pub(sa_sync_conn)
        oa = _create_sd(sa_sync_conn, "openalex", "oa-1", p, external_ids={"hal_id": ["hal-X1"]})
        sc = _create_sd(sa_sync_conn, "scanr", "sc-1", p, external_ids={"hal_id": ["hal-X2"]})
        _create_sd(sa_sync_conn, "hal", "h-1", p)  # HAL lui-même exclu
        _create_sd(sa_sync_conn, "openalex", "oa-2", p)  # sans external.hal_id

        rows = fetch_source_publications_with_hal_external_id(sa_sync_conn)
        ids = {r.src_doc_id for r in rows}
        assert oa in ids and sc in ids
        assert all(r.hal_id in ("hal-X1", "hal-X2") for r in rows if r.src_doc_id in (oa, sc))


class TestFetchHalSourcePublications:
    def test_returns_only_hal_entries_with_halid(self, sa_sync_conn):
        p = _create_pub(sa_sync_conn)
        h = _create_sd(sa_sync_conn, "hal", "hal-999", p)
        _create_sd(sa_sync_conn, "openalex", "oa-999", p)

        rows = fetch_hal_source_publications(sa_sync_conn)
        halids = [r.halid for r in rows if r.hal_doc_id == h]
        assert halids == ["hal-999"]


class TestLinkSourcePublicationToPublication:
    def test_updates_publication_id(self, sa_sync_conn):
        p_new = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, "hal", "h-orphan", None)

        link_source_publication_to_publication(sa_sync_conn, sd, p_new)

        result = sa_sync_conn.execute(
            text("SELECT publication_id FROM source_publications WHERE id = :sd"),
            {"sd": sd},
        ).scalar_one()
        assert result == p_new
