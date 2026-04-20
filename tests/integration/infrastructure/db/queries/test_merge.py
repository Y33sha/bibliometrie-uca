"""Tests d'intégration pour `infrastructure.db.queries.merge`."""

import json

from infrastructure.db.queries.merge import (
    fetch_hal_source_publications,
    fetch_source_publications_with_hal_external_id,
    find_nnt_duplicates,
    link_source_publication_to_publication,
    rank_publications_by_merge_priority,
)


def _create_pub(db, doi=None, pub_year=2024):
    db.execute(
        """
        INSERT INTO publications (title, pub_year, doc_type, doi)
        VALUES ('X', %s, 'article', %s) RETURNING id
        """,
        (pub_year, doi),
    )
    return db.fetchone()["id"]


def _create_sd(db, source, source_id, pub_id, external_ids=None):
    db.execute(
        """
        INSERT INTO source_publications (source, source_id, title, publication_id, external_ids)
        VALUES (%s, %s, 'X', %s, %s::jsonb) RETURNING id
        """,
        (source, source_id, pub_id, json.dumps(external_ids) if external_ids else None),
    )
    return db.fetchone()["id"]


class TestFindNntDuplicates:
    def test_detects_nnt_pointing_to_two_publications(self, db):
        p1 = _create_pub(db)
        p2 = _create_pub(db)
        _create_sd(db, "hal", "h-1", p1, external_ids={"nnt": "2023UCFA0001"})
        _create_sd(db, "theses", "t-1", p2, external_ids={"nnt": "2023UCFA0001"})

        dups = find_nnt_duplicates(db)
        ours = [d for d in dups if d["nnt"] == "2023UCFA0001"]
        assert len(ours) == 1
        assert sorted(ours[0]["pub_ids"]) == sorted([p1, p2])
        assert set(ours[0]["sources"]) == {"hal", "theses"}

    def test_ignores_nnt_on_single_publication(self, db):
        p1 = _create_pub(db)
        _create_sd(db, "hal", "h-2", p1, external_ids={"nnt": "UNIQUE_NNT"})

        dups = find_nnt_duplicates(db)
        assert not any(d["nnt"] == "UNIQUE_NNT" for d in dups)


class TestRankPublicationsByMergePriority:
    def test_prefers_publication_with_real_doi(self, db):
        p_no_doi = _create_pub(db)
        p_bad_doi = _create_pub(db, doi="not-a-doi")
        p_good = _create_pub(db, doi="10.1/abc")

        rows = rank_publications_by_merge_priority(db, [p_no_doi, p_bad_doi, p_good])
        assert rows[0]["id"] == p_good

    def test_tiebreaks_by_source_publication_count(self, db):
        p_a = _create_pub(db, doi="10.1/a")
        p_b = _create_pub(db, doi="10.1/b")
        _create_sd(db, "hal", "s-a-1", p_a)
        _create_sd(db, "openalex", "s-a-2", p_a)
        _create_sd(db, "hal", "s-b-1", p_b)

        rows = rank_publications_by_merge_priority(db, [p_a, p_b])
        assert rows[0]["id"] == p_a  # 2 source_publications
        assert rows[1]["id"] == p_b

    def test_tiebreaks_by_lowest_id(self, db):
        p1 = _create_pub(db)
        p2 = _create_pub(db)
        rows = rank_publications_by_merge_priority(db, [p2, p1])
        assert rows[0]["id"] == p1


class TestFetchSourcePublicationsWithHalExternalId:
    def test_returns_openalex_and_scanr_with_hal_external(self, db):
        p = _create_pub(db)
        oa = _create_sd(db, "openalex", "oa-1", p, external_ids={"hal": "hal-X1"})
        sc = _create_sd(db, "scanr", "sc-1", p, external_ids={"hal": "hal-X2"})
        _create_sd(db, "hal", "h-1", p)  # HAL lui-même exclu
        _create_sd(db, "openalex", "oa-2", p)  # sans external.hal

        rows = fetch_source_publications_with_hal_external_id(db)
        ids = {r["src_doc_id"] for r in rows}
        assert oa in ids and sc in ids
        assert all(r["hal_id"] in ("hal-X1", "hal-X2") for r in rows if r["src_doc_id"] in (oa, sc))


class TestFetchHalSourcePublications:
    def test_returns_only_hal_entries_with_halid(self, db):
        p = _create_pub(db)
        h = _create_sd(db, "hal", "hal-999", p)
        _create_sd(db, "openalex", "oa-999", p)

        rows = fetch_hal_source_publications(db)
        halids = [r["halid"] for r in rows if r["hal_doc_id"] == h]
        assert halids == ["hal-999"]


class TestLinkSourcePublicationToPublication:
    def test_updates_publication_id(self, db):
        p_new = _create_pub(db)
        sd = _create_sd(db, "hal", "h-orphan", None)

        link_source_publication_to_publication(db, sd, p_new)

        db.execute("SELECT publication_id FROM source_publications WHERE id = %s", (sd,))
        assert db.fetchone()["publication_id"] == p_new
