"""Tests d'intégration pour `infrastructure.db.queries.authorships` (§2.12 : async)."""

from infrastructure.db.queries.authorships import (
    authorships_facets,
    authorships_stats,
    list_authorships,
)


async def _create_person(db):
    await db.execute(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
        "VALUES ('X', 'Y', 'x', 'y') RETURNING id"
    )
    row = await db.fetchone()
    return row["id"]


async def _create_pub(db):
    await db.execute(
        "INSERT INTO publications (title, pub_year, doc_type) VALUES ('X', 2024, 'article') RETURNING id"
    )
    row = await db.fetchone()
    return row["id"]


async def _create_sd(db, pub_id, source="hal", source_id="h1"):
    await db.execute(
        "INSERT INTO source_publications (source, source_id, title, publication_id) "
        "VALUES (%s, %s, 'X', %s) RETURNING id",
        (source, source_id, pub_id),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_sp(db, source="hal", source_id="sp1", orcid=None, idhal=None, full_name="X"):
    import json as _json

    source_ids = {}
    if idhal:
        source_ids["idhal"] = idhal
    await db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name, orcid, source_ids)
        VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id
        """,
        (source, source_id, full_name, orcid, _json.dumps(source_ids) if source_ids else None),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_sa(
    db, sd, sp, source="hal", person_id=None, in_perimeter=True, structure_ids=None
):
    await db.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             person_id, in_perimeter, structure_ids)
        VALUES (%s, %s, %s, 0, %s, %s, %s) RETURNING id
        """,
        (source, sd, sp, person_id, in_perimeter, structure_ids),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_lab(db, code="LAB"):
    await db.execute(
        "INSERT INTO structures (code, name, structure_type) VALUES (%s, 'L', 'labo') RETURNING id",
        (code,),
    )
    row = await db.fetchone()
    return row["id"]


class TestAuthorshipsStats:
    async def test_counts_uca_authors(self, async_db):
        pid = await _create_person(async_db)
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp_linked = await _create_sp(async_db, source_id="sp-linked", orcid="0000-1", idhal="IDH1")
        sp_other = await _create_sp(async_db, source_id="sp-other")
        await _create_sa(async_db, sd, sp_linked, person_id=pid)
        await _create_sa(async_db, sd, sp_other)

        stats = await authorships_stats(async_db, lab_id=0)
        assert stats["total_uca_authors"] >= 2
        assert stats["linked_to_person"] >= 1
        assert stats["with_orcid"] >= 1
        assert stats["with_idhal"] >= 1

    async def test_filters_by_lab(self, async_db):
        lab = await _create_lab(async_db)
        other_lab = await _create_lab(async_db, code="OTHER")
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp_in = await _create_sp(async_db, source_id="sp-in")
        sp_out = await _create_sp(async_db, source_id="sp-out")
        await _create_sa(async_db, sd, sp_in, structure_ids=[lab])
        await _create_sa(async_db, sd, sp_out, structure_ids=[other_lab])

        stats = await authorships_stats(async_db, lab_id=lab)
        assert stats["total_uca_authors"] == 1


class TestAuthorshipsFacets:
    async def test_returns_all_facet_keys(self, async_db):
        pid = await _create_person(async_db)
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp = await _create_sp(async_db, orcid="O", idhal="H")
        await _create_sa(async_db, sd, sp, person_id=pid)

        facets = await authorships_facets(async_db, linked="", has_orcid="", has_idhal="", lab_id=0)
        assert set(facets.keys()) == {"linked", "orcid", "idhal", "labs"}

    async def test_excludes_own_filter(self, async_db):
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp_orcid = await _create_sp(async_db, source_id="with-o", orcid="0000")
        sp_no = await _create_sp(async_db, source_id="no-o")
        await _create_sa(async_db, sd, sp_orcid)
        await _create_sa(async_db, sd, sp_no)

        facets = await authorships_facets(
            async_db, linked="", has_orcid="yes", has_idhal="", lab_id=0
        )
        # La facette orcid ignore son propre filtre : yes + no tous deux comptés
        assert facets["orcid"]["yes"] >= 1
        assert facets["orcid"]["no"] >= 1


class TestListAuthorships:
    async def test_lists_uca_authors(self, async_db):
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp = await _create_sp(async_db, full_name="Dupond Jean")
        await _create_sa(async_db, sd, sp)

        res = await list_authorships(
            async_db,
            search="",
            linked="",
            has_orcid="",
            has_idhal="",
            lab_id=0,
            page=1,
            per_page=50,
        )
        assert res["total"] >= 1
        assert any(a["id"] == sp for a in res["authors"])

    async def test_search_filters_by_name(self, async_db):
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp_match = await _create_sp(async_db, source_id="sp-m", full_name="SpecialName Z")
        sp_other = await _create_sp(async_db, source_id="sp-o", full_name="Autre")
        await _create_sa(async_db, sd, sp_match)
        await _create_sa(async_db, sd, sp_other)

        res = await list_authorships(
            async_db,
            search="SpecialName",
            linked="",
            has_orcid="",
            has_idhal="",
            lab_id=0,
            page=1,
            per_page=50,
        )
        ids = [a["id"] for a in res["authors"]]
        assert sp_match in ids
        assert sp_other not in ids
