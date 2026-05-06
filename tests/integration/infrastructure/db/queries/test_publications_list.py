"""Tests d'intégration pour `infrastructure.db.queries.publications.list`."""

import json

from sqlalchemy import text

from infrastructure.db.queries.publications.list import ListFilters, list_publications


async def _create_pub(conn, title="T"):
    row = (
        await conn.execute(
            text(
                "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
                "VALUES (:t, lower(:t), 2024, 'article'::doc_type) RETURNING id"
            ),
            {"t": title},
        )
    ).one()
    return row.id


async def _create_lab(conn):
    row = (
        await conn.execute(
            text(
                "INSERT INTO structures (code, name, structure_type) "
                "VALUES ('LAB', 'LAB', 'labo'::structure_type) RETURNING id"
            )
        )
    ).one()
    return row.id


async def _attach(conn, pub_id, lab_id):
    """Authorship reliant la publi à un labo (via structure_ids).
    Évite source_authorships : `lab_ids` filter ne s'appuie que sur
    authorships, pas de besoin d'enregistrement source côté."""
    await conn.execute(
        text(
            "INSERT INTO authorships (publication_id, structure_ids, in_perimeter, roles) "
            "VALUES (:pid, :sids, TRUE, ARRAY['author']::text[])"
        ),
        {"pid": pub_id, "sids": [lab_id]},
    )


async def _create_subject(conn, label):
    row = (
        await conn.execute(
            text("INSERT INTO subjects (label, ontologies) VALUES (:l, :o) RETURNING id"),
            {"l": label, "o": json.dumps({})},
        )
    ).one()
    return row.id


async def _link_subject(conn, pub_id, sid):
    await conn.execute(
        text(
            "INSERT INTO publication_subjects (publication_id, subject_id, source) "
            "VALUES (:pid, :sid, 'hal')"
        ),
        {"pid": pub_id, "sid": sid},
    )


class TestSearch:
    async def test_search_matches_title(self, sa_conn):
        lab = await _create_lab(sa_conn)
        match = await _create_pub(sa_conn, "Quantum entanglement basics")
        other = await _create_pub(sa_conn, "Foo bar baz")
        await _attach(sa_conn, match, lab)
        await _attach(sa_conn, other, lab)

        res = await list_publications(
            sa_conn,
            filters=ListFilters(search="quantum", lab_ids=[lab]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p["id"] for p in res["publications"]]
        assert match in ids and other not in ids

    async def test_search_matches_subject_label(self, sa_conn):
        """Une publi dont le titre ne contient pas le terme mais qui est
        annotée par un sujet matchant doit remonter dans les résultats."""
        lab = await _create_lab(sa_conn)
        pub = await _create_pub(sa_conn, "Foo bar baz")
        unrelated = await _create_pub(sa_conn, "Hello world")
        await _attach(sa_conn, pub, lab)
        await _attach(sa_conn, unrelated, lab)

        sid = await _create_subject(sa_conn, "Quantum mechanics")
        await _link_subject(sa_conn, pub, sid)

        res = await list_publications(
            sa_conn,
            filters=ListFilters(search="quantum", lab_ids=[lab]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p["id"] for p in res["publications"]]
        assert pub in ids and unrelated not in ids

    async def test_title_match_ranks_before_subject_only_match(self, sa_conn):
        """Les publis dont le titre matche remontent avant celles qui ne
        matchent que via un sujet — quitte à casser l'ordre par défaut."""
        lab = await _create_lab(sa_conn)
        # Titre contient "quantum"
        title_match = await _create_pub(sa_conn, "Quantum entanglement basics")
        # Titre ne contient pas "quantum", mais sujet associé oui
        subject_match = await _create_pub(sa_conn, "Foo bar baz")
        await _attach(sa_conn, title_match, lab)
        await _attach(sa_conn, subject_match, lab)
        sid = await _create_subject(sa_conn, "Quantum mechanics")
        await _link_subject(sa_conn, subject_match, sid)

        res = await list_publications(
            sa_conn,
            filters=ListFilters(search="quantum", lab_ids=[lab]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p["id"] for p in res["publications"]]
        assert ids.index(title_match) < ids.index(subject_match)

    async def test_search_unaccented_matches_accented_label(self, sa_conn):
        """Les accents ne doivent pas bloquer le match (ILIKE + unaccent)."""
        lab = await _create_lab(sa_conn)
        pub = await _create_pub(sa_conn, "Foo")
        await _attach(sa_conn, pub, lab)
        sid = await _create_subject(sa_conn, "Économétrie")
        await _link_subject(sa_conn, pub, sid)

        res = await list_publications(
            sa_conn,
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
    async def _make_lab_with_collection(conn, collection: str) -> int:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO structures (code, name, structure_type, hal_collection) "
                    "VALUES ('LAB', 'LAB', 'labo'::structure_type, :col) RETURNING id"
                ),
                {"col": collection},
            )
        ).one()
        return row.id

    @staticmethod
    async def _add_hal_source(conn, pub_id: int, source_id: str, collections: list[str]) -> None:
        await conn.execute(
            text(
                "INSERT INTO source_publications "
                "(publication_id, source, source_id, title, hal_collections) "
                "VALUES (:pid, 'hal', :sid, 'T', :cols)"
            ),
            {"pid": pub_id, "sid": source_id, "cols": collections},
        )

    async def test_pub_in_collection_via_one_hal_entry_is_not_hors_collection(self, sa_conn):
        """Publi avec 2 dépôts HAL : l'un dans la collection du labo, l'autre
        non. Doit être exclue du filtre `hors_collection`."""
        lab = await self._make_lab_with_collection(sa_conn, "CMH")
        pub = await _create_pub(sa_conn, "Two HAL deposits")
        await _attach(sa_conn, pub, lab)
        await self._add_hal_source(sa_conn, pub, "hal-CMH", ["CMH", "AO-DROIT"])
        await self._add_hal_source(sa_conn, pub, "hal-PAU", ["UPPA-DROIT", "SHS"])
        await sa_conn.execute(
            text("UPDATE publications SET oa_status = 'gold'::oa_type WHERE id = :id"),
            {"id": pub},
        )

        res = await list_publications(
            sa_conn,
            filters=ListFilters(lab_ids=[lab], hal_status_values=["hors_collection"]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert pub not in [p["id"] for p in res["publications"]]

    async def test_hal_collections_unions_all_hal_entries(self, sa_conn):
        """`hal_collections` renvoyé par l'API = union des collections des
        entrées HAL (pas une entrée arbitraire prise au hasard)."""
        lab = await self._make_lab_with_collection(sa_conn, "CMH")
        pub = await _create_pub(sa_conn, "Two HAL deposits")
        await _attach(sa_conn, pub, lab)
        await self._add_hal_source(sa_conn, pub, "hal-CMH", ["CMH", "AO-DROIT"])
        await self._add_hal_source(sa_conn, pub, "hal-PAU", ["UPPA-DROIT"])

        res = await list_publications(
            sa_conn,
            filters=ListFilters(lab_ids=[lab]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        match = next(p for p in res["publications"] if p["id"] == pub)
        assert set(match["hal_collections"]) == {"CMH", "AO-DROIT", "UPPA-DROIT"}

    async def test_pub_only_outside_collection_is_hors_collection(self, sa_conn):
        """Cas symétrique : si aucune entrée HAL n'est dans la collection,
        la publi tombe bien dans `hors_collection`."""
        lab = await self._make_lab_with_collection(sa_conn, "CMH")
        pub = await _create_pub(sa_conn, "Outside only")
        await _attach(sa_conn, pub, lab)
        await self._add_hal_source(sa_conn, pub, "hal-PAU", ["UPPA-DROIT"])

        res = await list_publications(
            sa_conn,
            filters=ListFilters(lab_ids=[lab], hal_status_values=["hors_collection"]),
            root_structure_id=0,
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert pub in [p["id"] for p in res["publications"]]
