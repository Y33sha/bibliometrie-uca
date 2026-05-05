"""Tests d'intégration pour `infrastructure.db.queries.publications.detail` (§2.12 : async)."""

import json

from infrastructure.db.queries.publications.detail import (
    all_years,
    get_publication_detail,
    get_publication_subjects,
)


async def _create_pub(db, title="T", pub_year=2024, doc_type="article", doi=None):
    await db.execute(
        """
        INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
        VALUES (%s, lower(%s), %s, %s::doc_type, %s) RETURNING id
        """,
        (title, title, pub_year, doc_type, doi),
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


async def _create_sp(db, source="hal", source_id="sp1"):
    await db.execute(
        "INSERT INTO source_persons (source, source_id, full_name) VALUES (%s, %s, 'X') RETURNING id",
        (source, source_id),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_person(db):
    await db.execute(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
        "VALUES ('X', 'Y', 'x', 'y') RETURNING id"
    )
    row = await db.fetchone()
    return row["id"]


class TestAllYears:
    async def test_returns_distinct_years_desc(self, async_db):
        await _create_pub(async_db, pub_year=2020)
        await _create_pub(async_db, pub_year=2024)
        await _create_pub(async_db, pub_year=2024)

        years = await all_years(async_db)
        assert 2024 in years
        assert 2020 in years
        # Tri décroissant
        assert years == sorted(years, reverse=True)


class TestGetPublicationDetail:
    async def test_returns_none_for_missing(self, async_db):
        assert await get_publication_detail(async_db, 999_999) is None

    async def test_returns_full_detail(self, async_db):
        pid = await _create_person(async_db)
        pub = await _create_pub(async_db, title="Test Pub", doi="10.1/abc")
        sd = await _create_sd(async_db, pub, source="hal", source_id="hal-1")
        sp = await _create_sp(async_db, source="hal", source_id="sp-hal")
        await async_db.execute(
            "INSERT INTO authorships (publication_id, person_id) VALUES (%s, %s) RETURNING id",
            (pub, pid),
        )
        row = await async_db.fetchone()
        auth_id = row["id"]
        await async_db.execute(
            """
            INSERT INTO source_authorships
                (source, source_publication_id, source_person_id, author_position, person_id, authorship_id)
            VALUES ('hal', %s, %s, 0, %s, %s)
            """,
            (sd, sp, pid, auth_id),
        )

        detail = await get_publication_detail(async_db, pub)
        assert detail is not None
        assert detail["publication"]["id"] == pub
        assert detail["publication"]["doi"] == "10.1/abc"
        assert any(s["source"] == "hal" for s in detail["sources"])
        assert len(detail["authorships"]) == 1
        assert detail["authorships"][0]["source_hal"] is True

    async def test_thesis_meta_populated_for_thesis(self, async_db):
        pub = await _create_pub(async_db, title="Thèse", doc_type="thesis")
        await async_db.execute(
            "UPDATE publications SET meta = %s::jsonb WHERE id = %s",
            (json.dumps({"date_soutenance": "2023-05-10"}), pub),
        )
        # source_publications theses avec meta
        await async_db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, publication_id, meta)
            VALUES ('theses', 't-1', 'Thèse', %s, %s::jsonb)
            """,
            (pub, json.dumps({"discipline": "Informatique"})),
        )

        detail = await get_publication_detail(async_db, pub)
        assert detail["thesis_meta"] is not None
        assert detail["thesis_meta"]["discipline"] == "Informatique"
        assert detail["thesis_meta"]["date_soutenance"] == "2023-05-10"

    async def test_thesis_meta_none_for_article(self, async_db):
        pub = await _create_pub(async_db, doc_type="article")
        detail = await get_publication_detail(async_db, pub)
        assert detail["thesis_meta"] is None

    async def test_multiple_source_publications_same_source(self, async_db):
        """Plusieurs `source_publications` d'une même source pour une publi
        canonique (ex: deux Work IDs OpenAlex partageant un DOI) :

        - `detail["sources"]` renvoie tous les rows, tri DESC par created_at.
        - `detail["openalex_authorships"]` ne renvoie que les auteurs de la
          row la plus récente (= rendu unique côté UI).
        """
        pub = await _create_pub(async_db, title="Multi-OA")
        # Row OpenAlex la plus ancienne, avec 1 auteur "Alice"
        sd_old = await _create_sd(async_db, pub, source="openalex", source_id="W1-OLD")
        await async_db.execute(
            "UPDATE source_publications SET created_at = '2026-01-01'::timestamptz WHERE id = %s",
            (sd_old,),
        )
        await async_db.execute(
            """
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, raw_author_name)
            VALUES ('openalex', %s, 0, 'Alice')
            """,
            (sd_old,),
        )
        # Row OpenAlex la plus récente, avec 1 auteur "Bob"
        sd_new = await _create_sd(async_db, pub, source="openalex", source_id="W2-NEW")
        await async_db.execute(
            "UPDATE source_publications SET created_at = '2026-05-01'::timestamptz WHERE id = %s",
            (sd_new,),
        )
        await async_db.execute(
            """
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, raw_author_name)
            VALUES ('openalex', %s, 0, 'Bob')
            """,
            (sd_new,),
        )

        detail = await get_publication_detail(async_db, pub)
        # Header : les 2 source_publications sont remontées, plus récente en 1er.
        oa_sources = [s for s in detail["sources"] if s["source"] == "openalex"]
        assert [s["source_id"] for s in oa_sources] == ["W2-NEW", "W1-OLD"]
        # Comparaison sources : seul l'auteur de la plus récente est exposé.
        assert [a["full_name"] for a in detail["openalex_authorships"]] == ["Bob"]

    async def test_aggregates_structures(self, async_db):
        await async_db.execute(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES ('LAB-X', 'Labo X', 'labo') RETURNING id"
        )
        row = await async_db.fetchone()
        lab_id = row["id"]

        pid = await _create_person(async_db)
        pub = await _create_pub(async_db)
        await async_db.execute(
            """
            INSERT INTO authorships (publication_id, person_id, structure_ids)
            VALUES (%s, %s, %s) RETURNING id
            """,
            (pub, pid, [lab_id]),
        )

        detail = await get_publication_detail(async_db, pub)
        assert str(lab_id) in detail["structures"]
        assert detail["structures"][str(lab_id)]["acronym"] is None
        assert detail["structures"][str(lab_id)]["name"] == "Labo X"


class TestGetPublicationSubjects:
    async def test_empty(self, async_db):
        pub = await _create_pub(async_db)
        assert await get_publication_subjects(async_db, pub) == []

    async def test_dedup_aggregates_sources(self, async_db):
        pub = await _create_pub(async_db)
        # Un même libellé annoté par deux sources : 1 row, sources = ['hal', 'openalex'].
        await async_db.execute("INSERT INTO subjects (label) VALUES ('AI') RETURNING id")
        sid = (await async_db.fetchone())["id"]
        for src in ("hal", "openalex"):
            await async_db.execute(
                "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                "VALUES (%s, %s, %s)",
                (pub, sid, src),
            )

        subjects = await get_publication_subjects(async_db, pub)
        assert len(subjects) == 1
        assert subjects[0]["label"] == "AI"
        assert subjects[0]["sources"] == ["hal", "openalex"]

    async def test_orders_concepts_before_free(self, async_db):
        pub = await _create_pub(async_db)
        # Concept (avec ontologies) avant libre (ontologies vides).
        import json

        await async_db.execute(
            "INSERT INTO subjects (label, ontologies) VALUES ('Sciences EEA', %s::jsonb) RETURNING id",
            (json.dumps({"hal_domain": {"codes": ["info.eea"]}}),),
        )
        c_id = (await async_db.fetchone())["id"]
        await async_db.execute("INSERT INTO subjects (label) VALUES ('physics') RETURNING id")
        f_id = (await async_db.fetchone())["id"]
        await async_db.execute(
            "INSERT INTO publication_subjects (publication_id, subject_id, source) VALUES (%s, %s, 'hal')",
            (pub, c_id),
        )
        await async_db.execute(
            "INSERT INTO publication_subjects (publication_id, subject_id, source) VALUES (%s, %s, 'openalex')",
            (pub, f_id),
        )

        subjects = await get_publication_subjects(async_db, pub)
        # Concept (ontologies non vides) en premier, libre ensuite.
        assert subjects[0]["ontologies"] != {}
        assert subjects[1]["ontologies"] == {}

    async def test_included_in_publication_detail(self, async_db):
        pub = await _create_pub(async_db)
        await async_db.execute("INSERT INTO subjects (label) VALUES ('genomics') RETURNING id")
        sid = (await async_db.fetchone())["id"]
        await async_db.execute(
            "INSERT INTO publication_subjects (publication_id, subject_id, source) VALUES (%s, %s, 'wos')",
            (pub, sid),
        )

        detail = await get_publication_detail(async_db, pub)
        assert "subjects" in detail
        assert len(detail["subjects"]) == 1
        assert detail["subjects"][0]["label"] == "genomics"
        assert detail["subjects"][0]["sources"] == ["wos"]
