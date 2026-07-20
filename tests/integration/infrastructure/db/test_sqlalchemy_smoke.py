"""Chaîne MetaData → SQLAlchemy Core → psycopg3, et accord de la MetaData avec les migrations.

Les tests de round-trip vérifient que les types Postgres non triviaux (JSONB, ARRAY) traversent la chaîne. `TestMetaDataMatchesMigrations` est le filet contre le drift entre `infrastructure/db/tables.py` et le schéma qu'écrivent les migrations.
"""

from alembic.config import Config
from sqlalchemy import Connection, select, update

from alembic import command
from infrastructure.db.tables import config, perimeters, structures

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
            .values(code="poc_perim", name="POC", root_structure_ids=[1, 2, 3])
            .returning(perimeters.c.id, perimeters.c.root_structure_ids)
        )
        row = result.one()
        assert row.root_structure_ids == [1, 2, 3]

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


# ── Cohérence MetaData ↔ migrations ────────────────────────────────


class TestMetaDataMatchesMigrations:
    def test_alembic_check_reports_no_drift(self, alembic_config: Config):
        """Les migrations produisent le schéma que `infrastructure/db/tables.py` déclare.

        La base de test est montée par `alembic upgrade head` : la confronter à la MetaData compare le schéma aux migrations qui l'écrivent, seule source de vérité. `alembic check` couvre les tables et colonnes des deux côtés, leurs types, leur nullabilité et leurs commentaires ; index, clés étrangères et vues matérialisées restent hors comparaison (`include_object` dans `alembic/env.py`).

        L'échec porte le diff des opérations qu'un autogenerate produirait.
        """
        command.check(alembic_config)
