"""Files d'attente du recalcul des pays : schéma queues, source_contribution_countries_queue et address_countries_queue

Revision ID: 4b6efac6c4e1
Revises: b8d2f4a6c931
Create Date: 2026-10-23 10:00:00.000000

Chaque file reçoit les identifiants marqués par la colonne `countries_dirty` de sa table, puis la colonne et son index partiel sont supprimés.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4b6efac6c4e1"
down_revision: str | Sequence[str] | None = "b8d2f4a6c931"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEARCH_PATH_BEFORE = "sources, publications, persons, publishing, structures, ref, ops, public"
_SEARCH_PATH_AFTER = (
    "sources, publications, persons, publishing, structures, ref, ops, queues, public"
)

# File, schéma et table traitée, index partiel du marqueur.
_QUEUES = (
    (
        "source_contribution_countries_queue",
        "sources",
        "source_contributions",
        "idx_source_contributions_countries_dirty",
    ),
    ("address_countries_queue", "structures", "addresses", "idx_addresses_countries_dirty"),
)


def _set_search_path(value: str) -> None:
    op.execute(
        f"DO $$ BEGIN EXECUTE format('ALTER DATABASE %I SET search_path = {value}', "
        "current_database()); END $$"
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA queues")
    _set_search_path(_SEARCH_PATH_AFTER)
    for queue, schema, table, index in _QUEUES:
        op.execute(f"""
            CREATE TABLE queues.{queue} (
                id integer PRIMARY KEY REFERENCES {schema}.{table} (id) ON DELETE CASCADE,
                seq bigint GENERATED ALWAYS AS IDENTITY
            )
        """)
        op.execute(
            f"INSERT INTO queues.{queue} (id) SELECT id FROM {schema}.{table} WHERE countries_dirty"
        )
        op.execute(f"DROP INDEX {schema}.{index}")
        op.execute(f"ALTER TABLE {schema}.{table} DROP COLUMN countries_dirty")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE sources.source_contributions ADD COLUMN countries_dirty boolean DEFAULT false NOT NULL;
        ALTER TABLE structures.addresses ADD COLUMN countries_dirty boolean DEFAULT false NOT NULL;
        UPDATE sources.source_contributions SET countries_dirty = true
        WHERE id IN (SELECT id FROM queues.source_contribution_countries_queue);
        UPDATE structures.addresses SET countries_dirty = true
        WHERE id IN (SELECT id FROM queues.address_countries_queue);
        ALTER TABLE sources.source_contributions ALTER COLUMN countries_dirty SET DEFAULT true;
        CREATE INDEX idx_source_contributions_countries_dirty
            ON sources.source_contributions USING btree (source_record_id) WHERE countries_dirty;
        CREATE INDEX idx_addresses_countries_dirty
            ON structures.addresses USING btree (id) WHERE countries_dirty;
        DROP TABLE queues.source_contribution_countries_queue, queues.address_countries_queue;
        DROP SCHEMA queues;
    """)
    _set_search_path(_SEARCH_PATH_BEFORE)
