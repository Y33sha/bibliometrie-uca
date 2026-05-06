"""Tests d'intégration pour `infrastructure.db.queries.laboratories` (async)."""

import json

from sqlalchemy import text

from infrastructure.db.queries.laboratories import (
    LabPersonsFilters,
    get_laboratory,
    get_laboratory_addresses,
    get_laboratory_dashboard,
    get_laboratory_persons,
    get_laboratory_subjects,
    list_laboratories,
)


async def _create_structure(conn, code, name=None, type_="labo", hal_collection=None):
    row = (
        await conn.execute(
            text(
                "INSERT INTO structures (code, name, structure_type, hal_collection) "
                "VALUES (:code, :name, CAST(:tp AS structure_type), :col) RETURNING id"
            ),
            {"code": code, "name": name or code, "tp": type_, "col": hal_collection},
        )
    ).one()
    return row.id


async def _setup_perimeter(conn, lab_ids, code="uca"):
    root = await _create_structure(conn, code=code.upper(), type_="universite")
    all_ids = [root] + list(lab_ids)
    await conn.execute(
        text("INSERT INTO perimeters (code, name, structure_ids) VALUES (:c, :n, :ids)"),
        {"c": code, "n": code.upper(), "ids": all_ids},
    )
    await conn.execute(
        text(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', to_jsonb(CAST(:c AS text)))"
        ),
        {"c": code},
    )
    # relation est_tutelle_de pour les descendants
    for lab in lab_ids:
        await conn.execute(
            text(
                "INSERT INTO structure_relations (parent_id, child_id, relation_type) "
                "VALUES (:p, :c, 'est_tutelle_de')"
            ),
            {"p": root, "c": lab},
        )
    return root


async def _create_person(conn, last="A", first="Z"):
    row = (
        await conn.execute(
            text(
                "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
                "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
            ),
            {"l": last, "f": first},
        )
    ).one()
    return row.id


async def _create_pub_with_authorship(
    conn, person_id, lab_id, doc_type="article", pub_year=2024, in_perimeter=True
):
    pub_row = (
        await conn.execute(
            text(
                "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
                "VALUES ('X', 'x', :y, CAST(:dt AS doc_type)) RETURNING id"
            ),
            {"y": pub_year, "dt": doc_type},
        )
    ).one()
    pub_id = pub_row.id
    await conn.execute(
        text(
            "INSERT INTO authorships (publication_id, person_id, structure_ids, in_perimeter, roles) "
            "VALUES (:pid, :perid, :sids, :inp, ARRAY['author']::text[]) RETURNING id"
        ),
        {"pid": pub_id, "perid": person_id, "sids": [lab_id], "inp": in_perimeter},
    )
    return pub_id


class TestListLaboratories:
    async def test_lists_labos_in_perimeter(self, sa_conn):
        lab = await _create_structure(sa_conn, code="LAB-1", name="Lab 1")
        root = await _setup_perimeter(sa_conn, [lab])
        labs = await list_laboratories(sa_conn, [root, lab], [root])
        ids = [lab_["id"] for lab_ in labs]
        assert lab in ids

    async def test_excludes_root_as_tutelle(self, sa_conn):
        lab = await _create_structure(sa_conn, code="LAB-2")
        root = await _setup_perimeter(sa_conn, [lab])
        labs = await list_laboratories(sa_conn, [root, lab], [root])
        for lab_ in labs:
            if lab_["id"] == lab:
                # La racine est filtrée des tutelles
                tutelles_ids = [t["id"] for t in (lab_["tutelles"] or [])]
                assert root not in tutelles_ids


class TestGetLaboratory:
    async def test_returns_none_for_missing(self, sa_conn):
        assert await get_laboratory(sa_conn, 999_999) is None

    async def test_returns_full_profile(self, sa_conn):
        lab = await _create_structure(sa_conn, code="LAB", name="Le labo", hal_collection="LAB-COL")
        res = await get_laboratory(sa_conn, lab)
        assert res is not None
        assert res["structure"]["code"] == "LAB"
        assert res["structure"]["hal_collection"] == "LAB-COL"
        assert isinstance(res["parents"], list)
        assert isinstance(res["children"], list)
        assert isinstance(res["theses_count"], int)


class TestGetLaboratoryPersons:
    async def test_returns_linked_persons(self, sa_conn):
        lab = await _create_structure(sa_conn, code="LAB")
        pid = await _create_person(sa_conn)
        await _create_pub_with_authorship(sa_conn, pid, lab)

        res = await get_laboratory_persons(
            sa_conn, lab, filters=LabPersonsFilters(), page=1, per_page=50, sort="name"
        )
        assert res["total_persons"] == 1
        assert res["persons"][0]["id"] == pid

    async def test_search_filters_by_name(self, sa_conn):
        lab = await _create_structure(sa_conn, code="LAB")
        p_match = await _create_person(sa_conn, last="Dupond", first="Jean")
        p_other = await _create_person(sa_conn, last="Autre", first="Zed")
        await _create_pub_with_authorship(sa_conn, p_match, lab)
        await _create_pub_with_authorship(sa_conn, p_other, lab)

        res = await get_laboratory_persons(
            sa_conn,
            lab,
            filters=LabPersonsFilters(search="Dupond"),
            page=1,
            per_page=50,
            sort="name",
        )
        ids = [p["id"] for p in res["persons"]]
        assert p_match in ids and p_other not in ids

    async def test_counts_orphan_authorships(self, sa_conn):
        lab = await _create_structure(sa_conn, code="LAB")
        pub_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
                    "VALUES ('X', 'x', 2024, 'article') RETURNING id"
                )
            )
        ).one()
        pub = pub_row.id
        await sa_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id, structure_ids, roles) "
                "VALUES (:pid, NULL, :sids, ARRAY['author']::text[])"
            ),
            {"pid": pub, "sids": [lab]},
        )

        res = await get_laboratory_persons(
            sa_conn, lab, filters=LabPersonsFilters(), page=1, per_page=50, sort="name"
        )
        assert res["orphan_authorships"]["total"] == 1


class TestGetLaboratoryAddresses:
    async def test_lists_linked_addresses(self, sa_conn):
        lab = await _create_structure(sa_conn, code="LAB")
        addr_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO addresses (raw_text, normalized_text) "
                    "VALUES ('A', 'a') RETURNING id"
                )
            )
        ).one()
        addr = addr_row.id
        await sa_conn.execute(
            text(
                "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
                "VALUES (:a, :s, TRUE)"
            ),
            {"a": addr, "s": lab},
        )

        res = await get_laboratory_addresses(sa_conn, lab, page=1, per_page=50)
        ids = [a["id"] for a in res["addresses"]]
        assert addr in ids

    async def test_excludes_rejected_links(self, sa_conn):
        lab = await _create_structure(sa_conn, code="LAB")
        addr_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO addresses (raw_text, normalized_text) "
                    "VALUES ('R', 'r') RETURNING id"
                )
            )
        ).one()
        addr = addr_row.id
        await sa_conn.execute(
            text(
                "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
                "VALUES (:a, :s, FALSE)"
            ),
            {"a": addr, "s": lab},
        )
        res = await get_laboratory_addresses(sa_conn, lab, page=1, per_page=50)
        ids = [a["id"] for a in res["addresses"]]
        assert addr not in ids


class TestGetLaboratoryDashboard:
    async def test_returns_structure_even_when_empty(self, sa_conn):
        lab = await _create_structure(sa_conn, code="LAB")
        res = await get_laboratory_dashboard(sa_conn, lab)
        assert "pubs_by_year" in res
        assert "oa" in res
        assert "collab" in res
        assert "top_countries" in res
        assert res["oa"]["total"] == 0

    async def test_aggregates_oa_and_countries(self, sa_conn):
        await sa_conn.execute(
            text("INSERT INTO countries (code, name) VALUES ('us', 'USA') ON CONFLICT DO NOTHING")
        )
        lab = await _create_structure(sa_conn, code="LAB")
        pid = await _create_person(sa_conn)
        pub_row = (
            await sa_conn.execute(
                text("""
                    INSERT INTO publications (title, title_normalized, pub_year, doc_type, oa_status, countries)
                    VALUES ('X', 'x', 2024, 'article', 'gold', ARRAY['fr', 'us'])
                    RETURNING id
                """)
            )
        ).one()
        pub_id = pub_row.id
        await sa_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id, structure_ids, in_perimeter, roles) "
                "VALUES (:pid, :perid, :sids, TRUE, ARRAY['author']::text[])"
            ),
            {"pid": pub_id, "perid": pid, "sids": [lab]},
        )

        res = await get_laboratory_dashboard(sa_conn, lab)
        assert res["oa"]["open_access"] == 1
        assert res["collab"]["international"] == 1
        assert any(c["code"] == "us" for c in res["top_countries"])

    async def test_excludes_non_applicable_country(self, sa_conn):
        """`xx` (Non applicable) ne doit ni gonfler le compte international
        ni apparaître dans le top pays."""
        lab = await _create_structure(sa_conn, code="LAB")
        pid = await _create_person(sa_conn)
        pub_row = (
            await sa_conn.execute(
                text("""
                    INSERT INTO publications (title, title_normalized, pub_year, doc_type, oa_status, countries)
                    VALUES ('Y', 'y', 2024, 'article', 'closed', ARRAY['fr', 'xx'])
                    RETURNING id
                """)
            )
        ).one()
        pub_id = pub_row.id
        await sa_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id, structure_ids, in_perimeter, roles) "
                "VALUES (:pid, :perid, :sids, TRUE, ARRAY['author']::text[])"
            ),
            {"pid": pub_id, "perid": pid, "sids": [lab]},
        )

        res = await get_laboratory_dashboard(sa_conn, lab)
        assert res["collab"]["total_articles"] == 1
        assert res["collab"]["international"] == 0
        assert res["collab"]["domestic"] == 1
        assert not any(c["code"] == "xx" for c in res["top_countries"])


class TestGetLaboratorySubjects:
    async def test_top_subjects_by_frequency(self, sa_conn):
        lab = await _create_structure(sa_conn, "L1")
        await _setup_perimeter(sa_conn, [lab])

        # 3 publications du labo avec sujets variables.
        async def _create_pub(title="X", doc_type="article"):
            row = (
                await sa_conn.execute(
                    text(
                        "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
                        "VALUES (:t, lower(:t), 2024, CAST(:dt AS doc_type)) RETURNING id"
                    ),
                    {"t": title, "dt": doc_type},
                )
            ).one()
            return row.id

        async def _create_subject(label, ontologies=None):
            row = (
                await sa_conn.execute(
                    text("INSERT INTO subjects (label, ontologies) VALUES (:l, :o) RETURNING id"),
                    {"l": label, "o": json.dumps(ontologies or {})},
                )
            ).one()
            return row.id

        async def _link(pub_id, sid):
            await sa_conn.execute(
                text(
                    "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                    "VALUES (:p, :s, 'hal')"
                ),
                {"p": pub_id, "s": sid},
            )

        async def _attach(pub_id):
            await sa_conn.execute(
                text(
                    "INSERT INTO authorships (publication_id, structure_ids, in_perimeter, roles) "
                    "VALUES (:p, :sids, TRUE, ARRAY['author']::text[])"
                ),
                {"p": pub_id, "sids": [lab]},
            )

        p1 = await _create_pub("p1")
        p2 = await _create_pub("p2")
        p3 = await _create_pub("p3")
        for p in (p1, p2, p3):
            await _attach(p)

        ai = await _create_subject("AI")
        bio = await _create_subject("Biology")
        # AI sur 3 publis ; Biology sur 1.
        for p in (p1, p2, p3):
            await _link(p, ai)
        await _link(p1, bio)

        res = await get_laboratory_subjects(sa_conn, lab, limit=10)
        assert len(res) == 2
        assert res[0]["label"] == "AI"
        assert res[0]["count"] == 3
        assert res[1]["label"] == "Biology"
        assert res[1]["count"] == 1

    async def test_excludes_peer_review_memoir_ongoing_thesis(self, sa_conn):
        lab = await _create_structure(sa_conn, "L1")
        await _setup_perimeter(sa_conn, [lab])

        # Publi peer_review : doit être exclue.
        excl_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
                    "VALUES ('X', 'x', 2024, CAST('peer_review' AS doc_type)) RETURNING id"
                )
            )
        ).one()
        excluded_pub = excl_row.id
        await sa_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, structure_ids, in_perimeter, roles) "
                "VALUES (:p, :sids, TRUE, ARRAY['author']::text[])"
            ),
            {"p": excluded_pub, "sids": [lab]},
        )
        sub_row = (
            await sa_conn.execute(
                text("INSERT INTO subjects (label, ontologies) VALUES ('X', :o) RETURNING id"),
                {"o": json.dumps({})},
            )
        ).one()
        sid = sub_row.id
        await sa_conn.execute(
            text(
                "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                "VALUES (:p, :s, 'hal')"
            ),
            {"p": excluded_pub, "s": sid},
        )

        res = await get_laboratory_subjects(sa_conn, lab, limit=10)
        assert res == []
