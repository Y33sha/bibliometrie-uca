"""external_ids.hal_id : scalaire → tableau (+ index GIN)

Phase 3 du chantier complétude des identifiants : une œuvre peut référencer
plusieurs dépôts HAL (chapitres, versions, doublons légitimes), tous captés
désormais dans `external_ids.hal_id` sous forme de **liste**. Cette migration
bascule la forme JSONB existante (scalaire `"hal-x"` → `["hal-x"]`) et remplace
l'index btree fonctionnel par un index GIN supportant le test d'appartenance
(`external_ids->'hal_id' @> to_jsonb('hal-x')`).

⚠️ Flag-day : le code lecteur attend un tableau (`jsonb_array_elements_text` /
`@>`). Appliquer cette migration **avant** de relancer le pipeline.

Revision ID: a9d3f1c7e5b2
Revises: f4a7c2e9d6b1
Create Date: 2026-06-09 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a9d3f1c7e5b2"
down_revision: str | Sequence[str] | None = "f4a7c2e9d6b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Scalaire → tableau 1-élément (idempotent : ne touche que les `string`).
    op.execute(
        """
        UPDATE source_publications
        SET external_ids = jsonb_set(external_ids, '{hal_id}', jsonb_build_array(external_ids->'hal_id'))
        WHERE external_ids ? 'hal_id'
          AND jsonb_typeof(external_ids->'hal_id') = 'string'
        """
    )
    # Index btree fonctionnel (sur ->>'hal_id') → GIN (membership sur le tableau).
    op.execute("DROP INDEX IF EXISTS idx_source_pubs_hal_id")
    op.execute(
        "CREATE INDEX idx_source_pubs_hal_id "
        "ON public.source_publications USING gin ((external_ids->'hal_id'))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_source_pubs_hal_id")
    op.execute(
        "CREATE INDEX idx_source_pubs_hal_id "
        "ON public.source_publications ((external_ids->>'hal_id')) "
        "WHERE (external_ids->>'hal_id') IS NOT NULL"
    )
    # Tableau → scalaire (premier élément). Perd les hal-ids secondaires.
    op.execute(
        """
        UPDATE source_publications
        SET external_ids = jsonb_set(external_ids, '{hal_id}', external_ids->'hal_id'->0)
        WHERE external_ids ? 'hal_id'
          AND jsonb_typeof(external_ids->'hal_id') = 'array'
        """
    )
