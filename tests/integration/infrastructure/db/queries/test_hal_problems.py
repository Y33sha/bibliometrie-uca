"""Tests d'intégration pour `infrastructure.db.queries.hal_problems` (§2.12 : async)."""

from infrastructure.db.queries.hal_problems import (
    hal_affiliation_conflicts,
    hal_duplicate_pubs_by_doi,
    hal_duplicate_pubs_by_metadata,
    hal_missing_collections,
    hal_missing_collections_labs,
)


async def _create_pub(db, title="T", doi=None, pub_year=2024, title_normalized=None):
    await db.execute(
        """
        INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
        VALUES (%s, %s, %s, 'article', %s) RETURNING id
        """,
        (title, title_normalized or title.lower(), pub_year, doi),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_hal_sd(
    db, pub_id, source_id, doi=None, hal_collections=None, pub_year=2024, title="T"
):
    await db.execute(
        """
        INSERT INTO source_publications
            (source, source_id, title, publication_id, doi, hal_collections, pub_year)
        VALUES ('hal', %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (source_id, title, pub_id, doi, hal_collections, pub_year),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_lab(db, code="LAB", hal_collection=None):
    await db.execute(
        """
        INSERT INTO structures (code, name, structure_type, hal_collection)
        VALUES (%s, 'L', 'labo', %s) RETURNING id
        """,
        (code, hal_collection),
    )
    row = await db.fetchone()
    return row["id"]


class TestHalDuplicatePubsByDoi:
    async def test_detects_two_hal_deposits_same_doi(self, async_db):
        pub = await _create_pub(async_db)
        await _create_hal_sd(async_db, pub, "h-1", doi="10.1/shared")
        await _create_hal_sd(async_db, pub, "h-2", doi="10.1/shared")

        res = await hal_duplicate_pubs_by_doi(async_db, page=1, per_page=50)
        assert res["total"] >= 1
        assert any(len(p["halids"]) >= 2 for p in res["pairs"])

    async def test_noop_without_duplicates(self, async_db):
        pub = await _create_pub(async_db)
        await _create_hal_sd(async_db, pub, "h-uniq", doi="10.1/u")
        res = await hal_duplicate_pubs_by_doi(async_db, page=1, per_page=50)
        assert res["total"] == 0


class TestHalDuplicatePubsByMetadata:
    async def test_detects_pair_with_same_title_and_year(self, async_db):
        # Titre > 30 chars + même année + même doc_type + taille auteurs ±2
        title = "Article Title That Is Long Enough To Trigger Metadata Detection"
        title_norm = title.lower()
        p1 = await _create_pub(async_db, title=title, title_normalized=title_norm)
        p2 = await _create_pub(async_db, title=title, title_normalized=title_norm)
        await _create_hal_sd(async_db, p1, "h-meta-1")
        await _create_hal_sd(async_db, p2, "h-meta-2")

        res = await hal_duplicate_pubs_by_metadata(async_db, page=1, per_page=50)
        assert res["total"] >= 1


class TestHalMissingCollectionsLabs:
    async def test_lists_labs_with_hal_collection(self, async_db):
        lab = await _create_lab(async_db, code="LAB-1", hal_collection="COLL-X")
        await _create_lab(async_db, code="LAB-NO", hal_collection=None)

        labs = await hal_missing_collections_labs(async_db)
        ids = [lab_["id"] for lab_ in labs]
        assert lab in ids
        assert all(lab_["hal_collection"] for lab_ in labs)


class TestHalMissingCollections:
    async def test_returns_error_for_lab_without_collection(self, async_db):
        lab = await _create_lab(async_db, code="LAB-NO-COL", hal_collection=None)
        res = await hal_missing_collections(async_db, lab_id=lab, page=1, per_page=50)
        assert res == {"error": "no_collection"}

    async def test_returns_empty_when_no_missing(self, async_db):
        lab = await _create_lab(async_db, code="LAB-X", hal_collection="COLL-X")
        res = await hal_missing_collections(async_db, lab_id=lab, page=1, per_page=50)
        assert res["total"] == 0
        assert res["lab_acronym"] is None  # structure sans acronyme


async def _create_other_sd(db, pub_id, source, source_id, pub_year=2024, title="T"):
    await db.execute(
        """
        INSERT INTO source_publications
            (source, source_id, title, publication_id, pub_year)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        (source, source_id, title, pub_id, pub_year),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_authorship_uca(db, pub_id, lab_id, position=0):
    await db.execute(
        """
        INSERT INTO authorships (publication_id, author_position, structure_ids, in_perimeter, roles)
        VALUES (%s, %s, ARRAY[%s]::int[], TRUE, ARRAY['author']) RETURNING id
        """,
        (pub_id, position, lab_id),
    )
    return (await db.fetchone())["id"]


async def _create_source_authorship(
    db, source, sd_id, position, *, in_perimeter, authorship_id=None
):
    await db.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, author_position, in_perimeter, authorship_id)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        (source, sd_id, position, in_perimeter, authorship_id),
    )
    return (await db.fetchone())["id"]


async def _create_address_for_sa(db, sa_id):
    await db.execute(
        "INSERT INTO addresses (raw_text, normalized_text) VALUES ('A', 'a') RETURNING id"
    )
    addr_id = (await db.fetchone())["id"]
    await db.execute(
        "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) VALUES (%s, %s)",
        (sa_id, addr_id),
    )
    return addr_id


class TestHalAffiliationConflicts:
    async def test_noop_when_no_data(self, async_db):
        res = await hal_affiliation_conflicts(async_db, page=1, per_page=50)
        assert res["total"] == 0
        assert res["publications"] == []

    async def test_detects_conflict_with_openalex(self, async_db):
        pub = await _create_pub(async_db, title="Conflict OA")
        lab = await _create_lab(async_db, code="LAB-OA")
        hal_sd = await _create_hal_sd(async_db, pub, "h-oa-1")
        a_uca = await _create_authorship_uca(async_db, pub, lab, position=0)
        await _create_source_authorship(
            async_db, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        oa_sd = await _create_other_sd(async_db, pub, "openalex", "oa-1")
        oa_sa = await _create_source_authorship(async_db, "openalex", oa_sd, 0, in_perimeter=False)
        await _create_address_for_sa(async_db, oa_sa)

        res = await hal_affiliation_conflicts(async_db, page=1, per_page=50)
        assert pub in [p["id"] for p in res["publications"]]

    async def test_detects_conflict_with_non_oa_wos_source(self, async_db):
        # Élargissement : la détection couvre toutes les sources non-HAL (ici scanr).
        pub = await _create_pub(async_db, title="Conflict scanR")
        lab = await _create_lab(async_db, code="LAB-SCANR")
        hal_sd = await _create_hal_sd(async_db, pub, "h-scanr-1")
        a_uca = await _create_authorship_uca(async_db, pub, lab, position=0)
        await _create_source_authorship(
            async_db, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        sr_sd = await _create_other_sd(async_db, pub, "scanr", "sr-1")
        sr_sa = await _create_source_authorship(async_db, "scanr", sr_sd, 0, in_perimeter=False)
        await _create_address_for_sa(async_db, sr_sa)

        res = await hal_affiliation_conflicts(async_db, page=1, per_page=50)
        assert pub in [p["id"] for p in res["publications"]]

    async def test_ignores_when_other_source_has_no_address(self, async_db):
        # Sans adresse, la source n'a pas "examiné l'affiliation" → pas un conflit.
        pub = await _create_pub(async_db, title="No address")
        lab = await _create_lab(async_db, code="LAB-NOADDR")
        hal_sd = await _create_hal_sd(async_db, pub, "h-noaddr-1")
        a_uca = await _create_authorship_uca(async_db, pub, lab, position=0)
        await _create_source_authorship(
            async_db, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        oa_sd = await _create_other_sd(async_db, pub, "openalex", "oa-noaddr")
        await _create_source_authorship(async_db, "openalex", oa_sd, 0, in_perimeter=False)

        res = await hal_affiliation_conflicts(async_db, page=1, per_page=50)
        assert pub not in [p["id"] for p in res["publications"]]

    async def test_ignores_position_mismatch(self, async_db):
        # HAL atteste position 0, OA hors-UCA position 1 → pas de conflit.
        pub = await _create_pub(async_db, title="Position mismatch")
        lab = await _create_lab(async_db, code="LAB-POS")
        hal_sd = await _create_hal_sd(async_db, pub, "h-pos-1")
        a_uca = await _create_authorship_uca(async_db, pub, lab, position=0)
        await _create_source_authorship(
            async_db, "hal", hal_sd, 0, in_perimeter=True, authorship_id=a_uca
        )
        oa_sd = await _create_other_sd(async_db, pub, "openalex", "oa-pos")
        oa_sa = await _create_source_authorship(async_db, "openalex", oa_sd, 1, in_perimeter=False)
        await _create_address_for_sa(async_db, oa_sa)

        res = await hal_affiliation_conflicts(async_db, page=1, per_page=50)
        assert pub not in [p["id"] for p in res["publications"]]
