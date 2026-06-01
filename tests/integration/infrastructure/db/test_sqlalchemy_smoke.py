"""POC SQLAlchemy Core — phase 0 du chantier sqlalchemy-core-adoption.

Vérifie que la chaîne MetaData → query SA Core → driver psycopg3
fonctionne sur la DB test, et que la MetaData déclarée dans
`infrastructure/db/tables.py` reste cohérente avec le schéma réel.

Tests à conserver tant que la MetaData ne couvre pas TOUTES les
tables : ils servent de filet contre le drift (colonne ajoutée en
migration mais oubliée dans tables.py, ou vice-versa).
"""

from sqlalchemy import Connection, inspect, select, update

from infrastructure.db.tables import config, metadata, perimeters, structures

# ── Smoke : round-trip SQLAlchemy Core sur la table config ────────


class TestSqlalchemyCoreSmoke:
    def test_select_returns_rows(self, sa_sync_conn: Connection):
        # Insère une clé via SQLAlchemy. SA (re)sérialise automatiquement
        # la valeur Python en JSONB (la colonne est typée JSONB).
        sa_sync_conn.execute(
            config.insert().values(key="poc_smoke", value="hello", description="poc")
        )
        result = sa_sync_conn.execute(
            select(config.c.key, config.c.value).where(config.c.key == "poc_smoke")
        )
        row = result.one()
        assert row.key == "poc_smoke"
        assert row.value == "hello"

    def test_update_with_returning(self, sa_sync_conn: Connection):
        sa_sync_conn.execute(
            config.insert().values(key="poc_update", value="old", description="poc")
        )
        stmt = (
            update(config)
            .where(config.c.key == "poc_update")
            .values(value={"a": 1, "b": 2})
            .returning(config.c.key, config.c.value)
        )
        result = sa_sync_conn.execute(stmt)
        row = result.one()
        assert row.key == "poc_update"
        assert row.value == {"a": 1, "b": 2}

    def test_insert_perimeter_with_array_column(self, sa_sync_conn: Connection):
        """Vérifie qu'un ARRAY(Integer) PostgreSQL est manipulable côté SA."""
        result = sa_sync_conn.execute(
            perimeters.insert()
            .values(code="poc_perim", name="POC", structure_ids=[1, 2, 3])
            .returning(perimeters.c.id, perimeters.c.structure_ids)
        )
        row = result.one()
        assert row.structure_ids == [1, 2, 3]

    def test_insert_structure_with_jsonb(self, sa_sync_conn: Connection):
        """Vérifie qu'un JSONB est sérialisé correctement par SA."""
        result = sa_sync_conn.execute(
            structures.insert()
            .values(
                code="POC_STRUCT",
                name="Poc",
                structure_type="universite",
                api_ids={"ror": "0000abc"},
            )
            .returning(structures.c.id, structures.c.api_ids)
        )
        row = result.one()
        assert row.api_ids == {"ror": "0000abc"}


# ── Cohérence MetaData ↔ schéma DB ─────────────────────────────────


class TestMetaDataConsistency:
    """Détecte un drift entre `infrastructure/db/tables.py` et la DB réelle.

    Échoue si une table déclarée dans MetaData n'existe pas en DB ou si
    elle expose des colonnes que la MetaData ignore (ou inversement).
    """

    def test_all_metadata_tables_exist_in_db(self, sa_sync_conn: Connection):
        insp = inspect(sa_sync_conn)
        db_relations = set(insp.get_table_names()) | set(insp.get_materialized_view_names())
        for table in metadata.tables.values():
            assert table.name in db_relations, (
                f"Table/matview `{table.name}` déclarée dans MetaData absente de la DB"
            )

    def test_all_metadata_columns_exist_in_db(self, sa_sync_conn: Connection):
        insp = inspect(sa_sync_conn)
        for table in metadata.tables.values():
            db_cols = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                assert col.name in db_cols, (
                    f"Colonne `{table.name}.{col.name}` déclarée dans MetaData absente de la DB"
                )

    def test_no_db_columns_unknown_to_metadata(self, sa_sync_conn: Connection):
        """Pour chaque table couverte par MetaData, la DB ne doit pas exposer
        de colonne inconnue de la MetaData (sinon le code SA ne la verra pas
        et passera silencieusement à côté)."""
        insp = inspect(sa_sync_conn)
        for table in metadata.tables.values():
            db_cols = {c["name"] for c in insp.get_columns(table.name)}
            md_cols = {c.name for c in table.columns}
            extra = db_cols - md_cols
            assert not extra, (
                f"Table `{table.name}` : colonnes en DB mais absentes de MetaData : {sorted(extra)}"
            )
