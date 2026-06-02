"""Tests d'intégration pour `infrastructure.queries.publications.list`."""

import json

from sqlalchemy import text

from application.ports.api.publications_queries import ListFilters
from infrastructure.queries.publications.list import list_publications
from tests.integration.helpers.structures import add_authorship_structure


def _create_pub(conn, title="T"):
    row = conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES (:t, lower(:t), 2024, 'article'::doc_type) RETURNING id"
        ),
        {"t": title},
    ).one()
    return row.id


def _create_lab(conn):
    row = conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES ('LAB', 'LAB', 'labo'::structure_type) RETURNING id"
        )
    ).one()
    return row.id


def _attach(conn, pub_id, lab_id):
    """Authorship reliant la publi à un labo via la matview authorship_structures
    (semée par la chaîne source minimale)."""
    aid = conn.execute(
        text(
            "INSERT INTO authorships (publication_id, in_perimeter, roles) "
            "VALUES (:pid, TRUE, ARRAY['author']::text[]) RETURNING id"
        ),
        {"pid": pub_id},
    ).scalar_one()
    add_authorship_structure(conn, aid, lab_id)


def _create_subject(conn, label):
    row = conn.execute(
        text("INSERT INTO subjects (label, ontologies) VALUES (:l, :o) RETURNING id"),
        {"l": label, "o": json.dumps({})},
    ).one()
    return row.id


def _link_subject(conn, pub_id, sid):
    conn.execute(
        text(
            "INSERT INTO publication_subjects (publication_id, subject_id, source) "
            "VALUES (:pid, :sid, 'hal')"
        ),
        {"pid": pub_id, "sid": sid},
    )


class TestSearch:
    def test_search_matches_title(self, sa_sync_conn):
        lab = _create_lab(sa_sync_conn)
        match = _create_pub(sa_sync_conn, "Quantum entanglement basics")
        other = _create_pub(sa_sync_conn, "Foo bar baz")
        _attach(sa_sync_conn, match, lab)
        _attach(sa_sync_conn, other, lab)

        res = list_publications(
            sa_sync_conn,
            filters=ListFilters(search="quantum", lab_ids=[lab]),
            apc_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p["id"] for p in res["publications"]]
        assert match in ids and other not in ids

    def test_search_matches_subject_label(self, sa_sync_conn):
        """Une publi dont le titre ne contient pas le terme mais qui est
        annotée par un sujet matchant doit remonter dans les résultats."""
        lab = _create_lab(sa_sync_conn)
        pub = _create_pub(sa_sync_conn, "Foo bar baz")
        unrelated = _create_pub(sa_sync_conn, "Hello world")
        _attach(sa_sync_conn, pub, lab)
        _attach(sa_sync_conn, unrelated, lab)

        sid = _create_subject(sa_sync_conn, "Quantum mechanics")
        _link_subject(sa_sync_conn, pub, sid)

        res = list_publications(
            sa_sync_conn,
            filters=ListFilters(search="quantum", lab_ids=[lab]),
            apc_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p["id"] for p in res["publications"]]
        assert pub in ids and unrelated not in ids

    def test_title_match_ranks_before_subject_only_match(self, sa_sync_conn):
        """Les publis dont le titre matche remontent avant celles qui ne
        matchent que via un sujet — quitte à casser l'ordre par défaut."""
        lab = _create_lab(sa_sync_conn)
        # Titre contient "quantum"
        title_match = _create_pub(sa_sync_conn, "Quantum entanglement basics")
        # Titre ne contient pas "quantum", mais sujet associé oui
        subject_match = _create_pub(sa_sync_conn, "Foo bar baz")
        _attach(sa_sync_conn, title_match, lab)
        _attach(sa_sync_conn, subject_match, lab)
        sid = _create_subject(sa_sync_conn, "Quantum mechanics")
        _link_subject(sa_sync_conn, subject_match, sid)

        res = list_publications(
            sa_sync_conn,
            filters=ListFilters(search="quantum", lab_ids=[lab]),
            apc_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p["id"] for p in res["publications"]]
        assert ids.index(title_match) < ids.index(subject_match)

    def test_search_unaccented_matches_accented_label(self, sa_sync_conn):
        """Les accents ne doivent pas bloquer le match (ILIKE + unaccent)."""
        lab = _create_lab(sa_sync_conn)
        pub = _create_pub(sa_sync_conn, "Foo")
        _attach(sa_sync_conn, pub, lab)
        sid = _create_subject(sa_sync_conn, "Économétrie")
        _link_subject(sa_sync_conn, pub, sid)

        res = list_publications(
            sa_sync_conn,
            filters=ListFilters(search="econometrie", lab_ids=[lab]),
            apc_structure_ids=[],
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
    def _make_lab_with_collection(conn, collection: str) -> int:
        row = conn.execute(
            text(
                "INSERT INTO structures (code, name, structure_type, hal_collection) "
                "VALUES ('LAB', 'LAB', 'labo'::structure_type, :col) RETURNING id"
            ),
            {"col": collection},
        ).one()
        return row.id

    @staticmethod
    def _add_hal_source(conn, pub_id: int, source_id: str, collections: list[str]) -> None:
        conn.execute(
            text(
                "INSERT INTO source_publications "
                "(publication_id, source, source_id, title, hal_collections) "
                "VALUES (:pid, 'hal', :sid, 'T', :cols)"
            ),
            {"pid": pub_id, "sid": source_id, "cols": collections},
        )

    def test_pub_in_collection_via_one_hal_entry_is_not_hors_collection(self, sa_sync_conn):
        """Publi avec 2 dépôts HAL : l'un dans la collection du labo, l'autre
        non. Doit être exclue du filtre `hors_collection`."""
        lab = self._make_lab_with_collection(sa_sync_conn, "CMH")
        pub = _create_pub(sa_sync_conn, "Two HAL deposits")
        _attach(sa_sync_conn, pub, lab)
        self._add_hal_source(sa_sync_conn, pub, "hal-CMH", ["CMH", "AO-DROIT"])
        self._add_hal_source(sa_sync_conn, pub, "hal-PAU", ["UPPA-DROIT", "SHS"])
        sa_sync_conn.execute(
            text("UPDATE publications SET oa_status = 'gold'::oa_type WHERE id = :id"),
            {"id": pub},
        )

        res = list_publications(
            sa_sync_conn,
            filters=ListFilters(lab_ids=[lab], hal_status_values=["hors_collection"]),
            apc_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert pub not in [p["id"] for p in res["publications"]]

    def test_hal_collections_unions_all_hal_entries(self, sa_sync_conn):
        """`hal_collections` renvoyé par l'API = union des collections des
        entrées HAL (pas une entrée arbitraire prise au hasard)."""
        lab = self._make_lab_with_collection(sa_sync_conn, "CMH")
        pub = _create_pub(sa_sync_conn, "Two HAL deposits")
        _attach(sa_sync_conn, pub, lab)
        self._add_hal_source(sa_sync_conn, pub, "hal-CMH", ["CMH", "AO-DROIT"])
        self._add_hal_source(sa_sync_conn, pub, "hal-PAU", ["UPPA-DROIT"])

        res = list_publications(
            sa_sync_conn,
            filters=ListFilters(lab_ids=[lab]),
            apc_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        match = next(p for p in res["publications"] if p["id"] == pub)
        assert set(match["hal_collections"]) == {"CMH", "AO-DROIT", "UPPA-DROIT"}

    def test_pub_only_outside_collection_is_hors_collection(self, sa_sync_conn):
        """Cas symétrique : si aucune entrée HAL n'est dans la collection,
        la publi tombe bien dans `hors_collection`."""
        lab = self._make_lab_with_collection(sa_sync_conn, "CMH")
        pub = _create_pub(sa_sync_conn, "Outside only")
        _attach(sa_sync_conn, pub, lab)
        self._add_hal_source(sa_sync_conn, pub, "hal-PAU", ["UPPA-DROIT"])

        res = list_publications(
            sa_sync_conn,
            filters=ListFilters(lab_ids=[lab], hal_status_values=["hors_collection"]),
            apc_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert pub in [p["id"] for p in res["publications"]]
