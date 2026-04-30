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

    async def test_title_match_ranks_before_subject_only_match(self, async_db):
        """Les publis dont le titre matche remontent avant celles qui ne
        matchent que via un sujet — quitte à casser l'ordre par défaut."""
        lab = await _create_lab(async_db)
        # Titre contient "quantum"
        title_match = await _create_pub(async_db, "Quantum entanglement basics")
        # Titre ne contient pas "quantum", mais sujet associé oui
        subject_match = await _create_pub(async_db, "Foo bar baz")
        await _attach(async_db, title_match, lab)
        await _attach(async_db, subject_match, lab)
        sid = await _create_subject(async_db, "Quantum mechanics")
        await _link_subject(async_db, subject_match, sid)

        res = await list_publications(
            async_db,
            filters=ListFilters(search="quantum", lab_ids=[lab]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p["id"] for p in res["publications"]]
        assert ids.index(title_match) < ids.index(subject_match)

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


class TestHalStatusMultipleHalEntries:
    """Régression : une publi avec plusieurs entrées HAL (cas réel ~764 en
    base) ne doit pas tomber dans le filtre `hors_collection` dès qu'au moins
    une de ses entrées HAL contient la collection du labo. Et le champ
    `hal_collections` renvoyé doit fusionner les collections des entrées."""

    @staticmethod
    async def _make_lab_with_collection(db, collection: str) -> int:
        await db.execute(
            "INSERT INTO structures (code, name, structure_type, hal_collection) "
            "VALUES ('LAB', 'LAB', 'labo'::structure_type, %s) RETURNING id",
            (collection,),
        )
        row = await db.fetchone()
        return row["id"]

    @staticmethod
    async def _add_hal_source(db, pub_id: int, source_id: str, collections: list[str]) -> None:
        await db.execute(
            "INSERT INTO source_publications (publication_id, source, source_id, title, hal_collections) "
            "VALUES (%s, 'hal', %s, 'T', %s)",
            (pub_id, source_id, collections),
        )

    async def test_pub_in_collection_via_one_hal_entry_is_not_hors_collection(self, async_db):
        """Publi avec 2 dépôts HAL : l'un dans la collection du labo, l'autre
        non. Doit être exclue du filtre `hors_collection`."""
        lab = await self._make_lab_with_collection(async_db, "CMH")
        pub = await _create_pub(async_db, "Two HAL deposits")
        await _attach(async_db, pub, lab)
        await self._add_hal_source(async_db, pub, "hal-CMH", ["CMH", "AO-DROIT"])
        await self._add_hal_source(async_db, pub, "hal-PAU", ["UPPA-DROIT", "SHS"])
        await async_db.execute(
            "UPDATE publications SET oa_status = 'gold'::oa_type WHERE id = %s",
            (pub,),
        )

        res = await list_publications(
            async_db,
            filters=ListFilters(lab_ids=[lab], hal_status_values=["hors_collection"]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert pub not in [p["id"] for p in res["publications"]]

    async def test_hal_collections_unions_all_hal_entries(self, async_db):
        """`hal_collections` renvoyé par l'API = union des collections des
        entrées HAL (pas une entrée arbitraire prise au hasard)."""
        lab = await self._make_lab_with_collection(async_db, "CMH")
        pub = await _create_pub(async_db, "Two HAL deposits")
        await _attach(async_db, pub, lab)
        await self._add_hal_source(async_db, pub, "hal-CMH", ["CMH", "AO-DROIT"])
        await self._add_hal_source(async_db, pub, "hal-PAU", ["UPPA-DROIT"])

        res = await list_publications(
            async_db,
            filters=ListFilters(lab_ids=[lab]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        match = next(p for p in res["publications"] if p["id"] == pub)
        assert set(match["hal_collections"]) == {"CMH", "AO-DROIT", "UPPA-DROIT"}

    async def test_pub_only_outside_collection_is_hors_collection(self, async_db):
        """Cas symétrique : si aucune entrée HAL n'est dans la collection,
        la publi tombe bien dans `hors_collection`."""
        lab = await self._make_lab_with_collection(async_db, "CMH")
        pub = await _create_pub(async_db, "Outside only")
        await _attach(async_db, pub, lab)
        await self._add_hal_source(async_db, pub, "hal-PAU", ["UPPA-DROIT"])

        res = await list_publications(
            async_db,
            filters=ListFilters(lab_ids=[lab], hal_status_values=["hors_collection"]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert pub in [p["id"] for p in res["publications"]]
