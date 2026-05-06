"""Tests d'intégration pour `infrastructure.db.queries.publications.detail` (async)."""

import json

from sqlalchemy import text

from infrastructure.db.queries.publications.detail import (
    all_years,
    get_publication_detail,
    get_publication_subjects,
)


async def _create_pub(conn, title="T", pub_year=2024, doc_type="article", doi=None):
    row = (
        await conn.execute(
            text("""
                INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
                VALUES (:t, lower(:t), :y, CAST(:dt AS doc_type), :doi) RETURNING id
            """),
            {"t": title, "y": pub_year, "dt": doc_type, "doi": doi},
        )
    ).one()
    return row.id


async def _create_sd(conn, pub_id, source="hal", source_id="h1"):
    row = (
        await conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, publication_id) "
                "VALUES (:src, :sid, 'X', :pid) RETURNING id"
            ),
            {"src": source, "sid": source_id, "pid": pub_id},
        )
    ).one()
    return row.id


async def _create_sp(conn, source="hal", source_id="sp1"):
    row = (
        await conn.execute(
            text(
                "INSERT INTO source_persons (source, source_id, full_name) "
                "VALUES (:src, :sid, 'X') RETURNING id"
            ),
            {"src": source, "sid": source_id},
        )
    ).one()
    return row.id


async def _create_person(conn):
    row = (
        await conn.execute(
            text(
                "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
                "VALUES ('X', 'Y', 'x', 'y') RETURNING id"
            )
        )
    ).one()
    return row.id


class TestAllYears:
    async def test_returns_distinct_years_desc(self, sa_conn):
        await _create_pub(sa_conn, pub_year=2020)
        await _create_pub(sa_conn, pub_year=2024)
        await _create_pub(sa_conn, pub_year=2024)

        years = await all_years(sa_conn)
        assert 2024 in years
        assert 2020 in years
        # Tri décroissant
        assert years == sorted(years, reverse=True)


class TestGetPublicationDetail:
    async def test_returns_none_for_missing(self, sa_conn):
        assert await get_publication_detail(sa_conn, 999_999) is None

    async def test_returns_full_detail(self, sa_conn):
        pid = await _create_person(sa_conn)
        pub = await _create_pub(sa_conn, title="Test Pub", doi="10.1/abc")
        sd = await _create_sd(sa_conn, pub, source="hal", source_id="hal-1")
        sp = await _create_sp(sa_conn, source="hal", source_id="sp-hal")
        auth_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO authorships (publication_id, person_id) "
                    "VALUES (:pub, :pid) RETURNING id"
                ),
                {"pub": pub, "pid": pid},
            )
        ).one()
        auth_id = auth_row.id
        await sa_conn.execute(
            text("""
                INSERT INTO source_authorships
                    (source, source_publication_id, source_person_id, author_position,
                     person_id, authorship_id)
                VALUES ('hal', :sd, :sp, 0, :pid, :auth)
            """),
            {"sd": sd, "sp": sp, "pid": pid, "auth": auth_id},
        )

        detail = await get_publication_detail(sa_conn, pub)
        assert detail is not None
        assert detail["publication"]["id"] == pub
        assert detail["publication"]["doi"] == "10.1/abc"
        assert any(s["source"] == "hal" for s in detail["sources"])
        assert len(detail["authorships"]) == 1
        assert detail["authorships"][0]["source_hal"] is True

    async def test_thesis_meta_populated_for_thesis(self, sa_conn):
        pub = await _create_pub(sa_conn, title="Thèse", doc_type="thesis")
        await sa_conn.execute(
            text("UPDATE publications SET meta = CAST(:m AS jsonb) WHERE id = :id"),
            {"m": json.dumps({"date_soutenance": "2023-05-10"}), "id": pub},
        )
        # source_publications theses avec meta
        await sa_conn.execute(
            text("""
                INSERT INTO source_publications (source, source_id, title, publication_id, meta)
                VALUES ('theses', 't-1', 'Thèse', :pub, CAST(:m AS jsonb))
            """),
            {"pub": pub, "m": json.dumps({"discipline": "Informatique"})},
        )

        detail = await get_publication_detail(sa_conn, pub)
        assert detail["thesis_meta"] is not None
        assert detail["thesis_meta"]["discipline"] == "Informatique"
        assert detail["thesis_meta"]["date_soutenance"] == "2023-05-10"

    async def test_thesis_meta_none_for_article(self, sa_conn):
        pub = await _create_pub(sa_conn, doc_type="article")
        detail = await get_publication_detail(sa_conn, pub)
        assert detail["thesis_meta"] is None

    async def test_multiple_source_publications_same_source(self, sa_conn):
        """Plusieurs `source_publications` d'une même source pour une publi
        canonique (ex: deux Work IDs OpenAlex partageant un DOI) :

        - `detail["sources"]` renvoie tous les rows, tri DESC par created_at.
        - `detail["openalex_authorships"]` ne renvoie que les auteurs de la
          row la plus récente (= rendu unique côté UI).
        """
        pub = await _create_pub(sa_conn, title="Multi-OA")
        # Row OpenAlex la plus ancienne, avec 1 auteur "Alice"
        sd_old = await _create_sd(sa_conn, pub, source="openalex", source_id="W1-OLD")
        await sa_conn.execute(
            text(
                "UPDATE source_publications SET created_at = '2026-01-01'::timestamptz "
                "WHERE id = :id"
            ),
            {"id": sd_old},
        )
        await sa_conn.execute(
            text("""
                INSERT INTO source_authorships
                    (source, source_publication_id, author_position, raw_author_name)
                VALUES ('openalex', :sd, 0, 'Alice')
            """),
            {"sd": sd_old},
        )
        # Row OpenAlex la plus récente, avec 1 auteur "Bob"
        sd_new = await _create_sd(sa_conn, pub, source="openalex", source_id="W2-NEW")
        await sa_conn.execute(
            text(
                "UPDATE source_publications SET created_at = '2026-05-01'::timestamptz "
                "WHERE id = :id"
            ),
            {"id": sd_new},
        )
        await sa_conn.execute(
            text("""
                INSERT INTO source_authorships
                    (source, source_publication_id, author_position, raw_author_name)
                VALUES ('openalex', :sd, 0, 'Bob')
            """),
            {"sd": sd_new},
        )

        detail = await get_publication_detail(sa_conn, pub)
        # Header : les 2 source_publications sont remontées, plus récente en 1er.
        oa_sources = [s for s in detail["sources"] if s["source"] == "openalex"]
        assert [s["source_id"] for s in oa_sources] == ["W2-NEW", "W1-OLD"]
        # Comparaison sources : seul l'auteur de la plus récente est exposé.
        assert [a["full_name"] for a in detail["openalex_authorships"]] == ["Bob"]

    async def test_aggregates_structures(self, sa_conn):
        lab_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO structures (code, name, structure_type) "
                    "VALUES ('LAB-X', 'Labo X', 'labo') RETURNING id"
                )
            )
        ).one()
        lab_id = lab_row.id

        pid = await _create_person(sa_conn)
        pub = await _create_pub(sa_conn)
        await sa_conn.execute(
            text("""
                INSERT INTO authorships (publication_id, person_id, structure_ids)
                VALUES (:pub, :pid, :sids) RETURNING id
            """),
            {"pub": pub, "pid": pid, "sids": [lab_id]},
        )

        detail = await get_publication_detail(sa_conn, pub)
        assert str(lab_id) in detail["structures"]
        assert detail["structures"][str(lab_id)]["acronym"] is None
        assert detail["structures"][str(lab_id)]["name"] == "Labo X"


class TestGetPublicationSubjects:
    async def test_empty(self, sa_conn):
        pub = await _create_pub(sa_conn)
        assert await get_publication_subjects(sa_conn, pub) == []

    async def test_dedup_aggregates_sources(self, sa_conn):
        pub = await _create_pub(sa_conn)
        # Un même libellé annoté par deux sources : 1 row, sources = ['hal', 'openalex'].
        sub_row = (
            await sa_conn.execute(text("INSERT INTO subjects (label) VALUES ('AI') RETURNING id"))
        ).one()
        sid = sub_row.id
        for src in ("hal", "openalex"):
            await sa_conn.execute(
                text(
                    "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                    "VALUES (:p, :s, :src)"
                ),
                {"p": pub, "s": sid, "src": src},
            )

        subjects = await get_publication_subjects(sa_conn, pub)
        assert len(subjects) == 1
        assert subjects[0]["label"] == "AI"
        assert subjects[0]["sources"] == ["hal", "openalex"]

    async def test_orders_concepts_before_free(self, sa_conn):
        pub = await _create_pub(sa_conn)
        # Concept (avec ontologies) avant libre (ontologies vides).
        c_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO subjects (label, ontologies) "
                    "VALUES ('Sciences EEA', CAST(:o AS jsonb)) RETURNING id"
                ),
                {"o": json.dumps({"hal_domain": {"codes": ["info.eea"]}})},
            )
        ).one()
        c_id = c_row.id
        f_row = (
            await sa_conn.execute(
                text("INSERT INTO subjects (label) VALUES ('physics') RETURNING id")
            )
        ).one()
        f_id = f_row.id
        await sa_conn.execute(
            text(
                "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                "VALUES (:p, :s, 'hal')"
            ),
            {"p": pub, "s": c_id},
        )
        await sa_conn.execute(
            text(
                "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                "VALUES (:p, :s, 'openalex')"
            ),
            {"p": pub, "s": f_id},
        )

        subjects = await get_publication_subjects(sa_conn, pub)
        # Concept (ontologies non vides) en premier, libre ensuite.
        assert subjects[0]["ontologies"] != {}
        assert subjects[1]["ontologies"] == {}

    async def test_included_in_publication_detail(self, sa_conn):
        pub = await _create_pub(sa_conn)
        sub_row = (
            await sa_conn.execute(
                text("INSERT INTO subjects (label) VALUES ('genomics') RETURNING id")
            )
        ).one()
        sid = sub_row.id
        await sa_conn.execute(
            text(
                "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                "VALUES (:p, :s, 'wos')"
            ),
            {"p": pub, "s": sid},
        )

        detail = await get_publication_detail(sa_conn, pub)
        assert "subjects" in detail
        assert len(detail["subjects"]) == 1
        assert detail["subjects"][0]["label"] == "genomics"
        assert detail["subjects"][0]["sources"] == ["wos"]
