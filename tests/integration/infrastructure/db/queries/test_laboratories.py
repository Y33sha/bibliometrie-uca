"""Tests d'intégration pour `infrastructure.db.queries.laboratories` (§2.12 : async)."""

from infrastructure.db.queries.laboratories import (
    LabPersonsFilters,
    get_laboratory,
    get_laboratory_addresses,
    get_laboratory_dashboard,
    get_laboratory_persons,
    list_laboratories,
)


async def _create_structure(db, code, name=None, type_="labo", hal_collection=None):
    await db.execute(
        """
        INSERT INTO structures (code, name, structure_type, hal_collection)
        VALUES (%s, %s, %s::structure_type, %s) RETURNING id
        """,
        (code, name or code, type_, hal_collection),
    )
    row = await db.fetchone()
    return row["id"]


async def _setup_perimeter(db, lab_ids, code="uca"):
    root = await _create_structure(db, code=code.upper(), type_="universite")
    all_ids = [root] + list(lab_ids)
    await db.execute(
        "INSERT INTO perimeters (code, name, structure_ids) VALUES (%s, %s, %s)",
        (code, code.upper(), all_ids),
    )
    await db.execute(
        "INSERT INTO config (key, value) VALUES ('perimeter_persons', to_jsonb(%s::text))",
        (code,),
    )
    # relation est_tutelle_de pour les descendants
    for lab in lab_ids:
        await db.execute(
            "INSERT INTO structure_relations (parent_id, child_id, relation_type) "
            "VALUES (%s, %s, 'est_tutelle_de')",
            (root, lab),
        )
    return root


async def _create_person(db, last="A", first="Z"):
    await db.execute(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
        "VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id",
        (last, first, last, first),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_pub_with_authorship(
    db, person_id, lab_id, doc_type="article", pub_year=2024, in_perimeter=True
):
    await db.execute(
        "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
        "VALUES ('X', 'x', %s, %s::doc_type) RETURNING id",
        (pub_year, doc_type),
    )
    row = await db.fetchone()
    pub_id = row["id"]
    await db.execute(
        """
        INSERT INTO authorships (publication_id, person_id, structure_ids, in_perimeter, roles)
        VALUES (%s, %s, %s, %s, ARRAY['author']::text[]) RETURNING id
        """,
        (pub_id, person_id, [lab_id], in_perimeter),
    )
    return pub_id


class TestListLaboratories:
    async def test_lists_labos_in_perimeter(self, async_db):
        lab = await _create_structure(async_db, code="LAB-1", name="Lab 1")
        await _setup_perimeter(async_db, [lab])
        labs = await list_laboratories(async_db)
        ids = [lab_["id"] for lab_ in labs]
        assert lab in ids

    async def test_excludes_root_as_tutelle(self, async_db):
        lab = await _create_structure(async_db, code="LAB-2")
        await _setup_perimeter(async_db, [lab])
        labs = await list_laboratories(async_db)
        for lab_ in labs:
            if lab_["id"] == lab:
                # La racine est filtrée des tutelles
                tutelles_ids = [t["id"] for t in (lab_["tutelles"] or [])]
                assert all(t != lab for t in tutelles_ids)


class TestGetLaboratory:
    async def test_returns_none_for_missing(self, async_db):
        assert await get_laboratory(async_db, 999_999) is None

    async def test_returns_full_profile(self, async_db):
        lab = await _create_structure(
            async_db, code="LAB", name="Le labo", hal_collection="LAB-COL"
        )
        res = await get_laboratory(async_db, lab)
        assert res is not None
        assert res["structure"]["code"] == "LAB"
        assert res["structure"]["hal_collection"] == "LAB-COL"
        assert isinstance(res["parents"], list)
        assert isinstance(res["children"], list)
        assert isinstance(res["theses_count"], int)


class TestGetLaboratoryPersons:
    async def test_returns_linked_persons(self, async_db):
        lab = await _create_structure(async_db, code="LAB")
        pid = await _create_person(async_db)
        await _create_pub_with_authorship(async_db, pid, lab)

        res = await get_laboratory_persons(
            async_db, lab, filters=LabPersonsFilters(), page=1, per_page=50, sort="name"
        )
        assert res["total_persons"] == 1
        assert res["persons"][0]["id"] == pid

    async def test_search_filters_by_name(self, async_db):
        lab = await _create_structure(async_db, code="LAB")
        p_match = await _create_person(async_db, last="Dupond", first="Jean")
        p_other = await _create_person(async_db, last="Autre", first="Zed")
        await _create_pub_with_authorship(async_db, p_match, lab)
        await _create_pub_with_authorship(async_db, p_other, lab)

        res = await get_laboratory_persons(
            async_db,
            lab,
            filters=LabPersonsFilters(search="Dupond"),
            page=1,
            per_page=50,
            sort="name",
        )
        ids = [p["id"] for p in res["persons"]]
        assert p_match in ids and p_other not in ids

    async def test_counts_orphan_authorships(self, async_db):
        lab = await _create_structure(async_db, code="LAB")
        await async_db.execute(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', 2024, 'article') RETURNING id"
        )
        row = await async_db.fetchone()
        pub = row["id"]
        await async_db.execute(
            """
            INSERT INTO authorships (publication_id, person_id, structure_ids, roles)
            VALUES (%s, NULL, %s, ARRAY['author']::text[])
            """,
            (pub, [lab]),
        )

        res = await get_laboratory_persons(
            async_db, lab, filters=LabPersonsFilters(), page=1, per_page=50, sort="name"
        )
        assert res["orphan_authorships"]["total"] == 1


class TestGetLaboratoryAddresses:
    async def test_lists_linked_addresses(self, async_db):
        lab = await _create_structure(async_db, code="LAB")
        await async_db.execute(
            "INSERT INTO addresses (raw_text, normalized_text) VALUES ('A', 'a') RETURNING id"
        )
        row = await async_db.fetchone()
        addr = row["id"]
        await async_db.execute(
            "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
            "VALUES (%s, %s, TRUE)",
            (addr, lab),
        )

        res = await get_laboratory_addresses(async_db, lab, page=1, per_page=50)
        ids = [a["id"] for a in res["addresses"]]
        assert addr in ids

    async def test_excludes_rejected_links(self, async_db):
        lab = await _create_structure(async_db, code="LAB")
        await async_db.execute(
            "INSERT INTO addresses (raw_text, normalized_text) VALUES ('R', 'r') RETURNING id"
        )
        row = await async_db.fetchone()
        addr = row["id"]
        await async_db.execute(
            "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
            "VALUES (%s, %s, FALSE)",
            (addr, lab),
        )
        res = await get_laboratory_addresses(async_db, lab, page=1, per_page=50)
        ids = [a["id"] for a in res["addresses"]]
        assert addr not in ids


class TestGetLaboratoryDashboard:
    async def test_returns_structure_even_when_empty(self, async_db):
        lab = await _create_structure(async_db, code="LAB")
        res = await get_laboratory_dashboard(async_db, lab)
        assert "pubs_by_year" in res
        assert "oa" in res
        assert "collab" in res
        assert "top_countries" in res
        assert res["oa"]["total"] == 0

    async def test_aggregates_oa_and_countries(self, async_db):
        await async_db.execute(
            "INSERT INTO countries (code, name) VALUES ('us', 'USA') ON CONFLICT DO NOTHING"
        )
        lab = await _create_structure(async_db, code="LAB")
        pid = await _create_person(async_db)
        await async_db.execute(
            """
            INSERT INTO publications (title, title_normalized, pub_year, doc_type, oa_status, countries)
            VALUES ('X', 'x', 2024, 'article', 'gold', ARRAY['fr', 'us'])
            RETURNING id
            """
        )
        row = await async_db.fetchone()
        pub_id = row["id"]
        await async_db.execute(
            """
            INSERT INTO authorships (publication_id, person_id, structure_ids, in_perimeter, roles)
            VALUES (%s, %s, %s, TRUE, ARRAY['author']::text[])
            """,
            (pub_id, pid, [lab]),
        )

        res = await get_laboratory_dashboard(async_db, lab)
        assert res["oa"]["open_access"] == 1
        assert res["collab"]["international"] == 1
        assert any(c["code"] == "us" for c in res["top_countries"])
