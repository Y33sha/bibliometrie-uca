"""Tests d'intégration pour `infrastructure.db.queries.publications.list`."""

from infrastructure.db.queries.publications.list import ListFilters, list_publications


async def _create_pub(db, title="T"):
    await db.execute(
        "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
        "VALUES (%s, lower(%s), 2024, 'article'::doc_type) RETURNING id",
        (title, title),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_lab(db):
    await db.execute(
        "INSERT INTO structures (code, name, structure_type) "
        "VALUES ('LAB', 'LAB', 'labo'::structure_type) RETURNING id"
    )
    row = await db.fetchone()
    return row["id"]


async def _attach(db, pub_id, lab_id):
    """Authorship reliant la publi à un labo (via structure_ids).
    Évite source_authorships : `lab_ids` filter ne s'appuie que sur
    authorships, pas de besoin d'enregistrement source côté."""
    await db.execute(
        "INSERT INTO authorships (publication_id, structure_ids, in_perimeter, roles) "
        "VALUES (%s, %s, TRUE, ARRAY['author']::text[])",
        (pub_id, [lab_id]),
    )


async def _create_subject(db, label):
    from psycopg.types.json import Json

    await db.execute(
        "INSERT INTO subjects (label, ontologies) VALUES (%s, %s) RETURNING id",
        (label, Json({})),
    )
    row = await db.fetchone()
    return row["id"]


async def _link_subject(db, pub_id, sid):
    await db.execute(
        "INSERT INTO publication_subjects (publication_id, subject_id, source) "
        "VALUES (%s, %s, 'hal')",
        (pub_id, sid),
    )


class TestSearch:
    async def test_search_matches_title(self, async_db):
        lab = await _create_lab(async_db)
        match = await _create_pub(async_db, "Quantum entanglement basics")
        other = await _create_pub(async_db, "Foo bar baz")
        await _attach(async_db, match, lab)
        await _attach(async_db, other, lab)

        res = await list_publications(
            async_db,
            filters=ListFilters(search="quantum", lab_ids=[lab]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p["id"] for p in res["publications"]]
        assert match in ids and other not in ids

    async def test_search_matches_subject_label(self, async_db):
        """Une publi dont le titre ne contient pas le terme mais qui est
        annotée par un sujet matchant doit remonter dans les résultats."""
        lab = await _create_lab(async_db)
        pub = await _create_pub(async_db, "Foo bar baz")
        unrelated = await _create_pub(async_db, "Hello world")
        await _attach(async_db, pub, lab)
        await _attach(async_db, unrelated, lab)

        sid = await _create_subject(async_db, "Quantum mechanics")
        await _link_subject(async_db, pub, sid)

        res = await list_publications(
            async_db,
            filters=ListFilters(search="quantum", lab_ids=[lab]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p["id"] for p in res["publications"]]
        assert pub in ids and unrelated not in ids

    async def test_search_unaccented_matches_accented_label(self, async_db):
        """Les accents ne doivent pas bloquer le match (ILIKE + unaccent)."""
        lab = await _create_lab(async_db)
        pub = await _create_pub(async_db, "Foo")
        await _attach(async_db, pub, lab)
        sid = await _create_subject(async_db, "Économétrie")
        await _link_subject(async_db, pub, sid)

        res = await list_publications(
            async_db,
            filters=ListFilters(search="econometrie", lab_ids=[lab]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p["id"] for p in res["publications"]]
        assert pub in ids
