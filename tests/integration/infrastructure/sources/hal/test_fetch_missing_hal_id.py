"""Tests d'intégration pour `infrastructure.sources.hal.fetch_missing_hal_id`."""

import json

from infrastructure.sources.hal.fetch_missing_hal_id import find_hal_ids_from_scanr


class TestFindHalIdsFromScanr:
    """Récupère les hal_ids référencés par ScanR mais absents de staging HAL.

    Régression : le bloc "staging ScanR non normalisé" matérialisait toutes les
    raw_data ScanR en mémoire Python (~1 Go × overhead psycopg → OOM kill sur
    ~80k lignes). L'extraction est désormais faite en SQL via
    `jsonb_array_elements`.
    """

    def _insert_scanr_staging(self, db, scanr_id, external_ids):
        db.execute(
            "INSERT INTO staging (source, source_id, raw_data) VALUES ('scanr', %s, %s)",
            (scanr_id, json.dumps({"externalIds": external_ids})),
        )

    def _insert_hal_staging(self, db, hal_id):
        db.execute(
            "INSERT INTO staging (source, source_id, raw_data) VALUES ('hal', %s, '{}'::jsonb)",
            (hal_id,),
        )

    def test_returns_hal_id_when_scanr_staging_has_external_id(self, db):
        self._insert_scanr_staging(db, "scanr-1", [{"type": "hal", "id": "hal-aaa"}])
        result = find_hal_ids_from_scanr(db)
        assert result == [{"source": "scanr", "hal_id": "hal-aaa", "scanr_id": "scanr-1"}]

    def test_skips_hal_id_already_in_staging_hal(self, db):
        self._insert_scanr_staging(db, "scanr-1", [{"type": "hal", "id": "hal-bbb"}])
        self._insert_hal_staging(db, "hal-bbb")
        assert find_hal_ids_from_scanr(db) == []

    def test_skips_non_hal_external_id_types(self, db):
        self._insert_scanr_staging(
            db,
            "scanr-1",
            [{"type": "doi", "id": "10.1/x"}, {"type": "pubmed", "id": "999"}],
        )
        assert find_hal_ids_from_scanr(db) == []

    def test_picks_hal_among_mixed_external_ids(self, db):
        self._insert_scanr_staging(
            db,
            "scanr-1",
            [
                {"type": "doi", "id": "10.1/x"},
                {"type": "hal", "id": "hal-ccc"},
                {"type": "pubmed", "id": "999"},
            ],
        )
        result = find_hal_ids_from_scanr(db)
        assert result == [{"source": "scanr", "hal_id": "hal-ccc", "scanr_id": "scanr-1"}]

    def test_handles_missing_external_ids_field(self, db):
        db.execute(
            "INSERT INTO staging (source, source_id, raw_data) VALUES ('scanr', 'scanr-1', '{}'::jsonb)"
        )
        assert find_hal_ids_from_scanr(db) == []

    def test_dedup_when_multiple_scanr_docs_reference_same_hal_id(self, db):
        self._insert_scanr_staging(db, "scanr-1", [{"type": "hal", "id": "hal-ddd"}])
        self._insert_scanr_staging(db, "scanr-2", [{"type": "hal", "id": "hal-ddd"}])
        result = find_hal_ids_from_scanr(db)
        hal_ids = [r["hal_id"] for r in result]
        assert hal_ids.count("hal-ddd") == 1

    def test_picks_up_normalized_source_publications(self, db):
        # source_publications.scanr → external_ids->>'hal' (sans staging ScanR brut)
        db.execute(
            "INSERT INTO staging (source, source_id, raw_data) VALUES ('scanr', 'scanr-norm', '{}'::jsonb) RETURNING id"
        )
        staging_id = db.fetchone()["id"]
        db.execute(
            """
            INSERT INTO source_publications (source, source_id, staging_id, title, external_ids)
            VALUES ('scanr', 'scanr-norm', %s, 'titre test', %s)
            """,
            (staging_id, json.dumps({"hal": "hal-eee"})),
        )
        result = find_hal_ids_from_scanr(db)
        assert {"source": "scanr", "hal_id": "hal-eee", "scanr_id": "scanr-norm"} in result

    def test_ignores_other_sources(self, db):
        # raw_data ressemble à du ScanR (externalIds[type=hal]) mais source != 'scanr'
        db.execute(
            "INSERT INTO staging (source, source_id, raw_data) VALUES ('openalex', 'oa-1', %s)",
            (json.dumps({"externalIds": [{"type": "hal", "id": "hal-fff"}]}),),
        )
        assert find_hal_ids_from_scanr(db) == []
