"""Modes d'entrée de `staging` nommés par l'identifiant cherché

Les recherches de la phase `fetch_missing` écrivent `fetch_missing_hal_id` pour une recherche par hal-id, `fetch_missing_nnt` pour une recherche par NNT, quelle que soit la source interrogée.

Les lignes existantes sont reprises. `fetch_missing_theses` devient `fetch_missing_nnt`. `fetch_missing_hal` devient `fetch_missing_nnt` pour une thèse dont l'enregistrement source HAL a un NNT, `fetch_missing_hal_id` pour les autres.

Revision ID: c3d9a7e1f5b2
Revises: b7f3e9a2c4d6
Create Date: 2026-10-27 23:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3d9a7e1f5b2"
down_revision: str | Sequence[str] | None = "b7f3e9a2c4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMON = (
    "'bulk'::text, 'fetch_missing_doi'::text, 'manual_export'::text, 'person_identifier'::text"
)
_BEFORE = f"{_COMMON}, 'fetch_missing_hal'::text, 'fetch_missing_theses'::text"
_AFTER = f"{_COMMON}, 'fetch_missing_hal_id'::text, 'fetch_missing_nnt'::text"


def _constraint(modes: str) -> str:
    return (
        "ALTER TABLE sources.staging ADD CONSTRAINT staging_entry_mode_check"
        f" CHECK (entry_mode = ANY (ARRAY[{modes}]))"
    )


def upgrade() -> None:
    op.execute("ALTER TABLE sources.staging DROP CONSTRAINT staging_entry_mode_check")
    op.execute(
        "UPDATE sources.staging SET entry_mode = 'fetch_missing_nnt' "
        "WHERE entry_mode = 'fetch_missing_theses'"
    )
    op.execute("""
        UPDATE sources.staging s SET entry_mode = 'fetch_missing_nnt'
        WHERE s.entry_mode = 'fetch_missing_hal'
          AND EXISTS (
              SELECT 1 FROM sources.source_records sr
              WHERE sr.staging_id = s.id AND sr.external_ids ->> 'nnt' IS NOT NULL
          )
    """)
    op.execute(
        "UPDATE sources.staging SET entry_mode = 'fetch_missing_hal_id' "
        "WHERE entry_mode = 'fetch_missing_hal'"
    )
    op.execute(_constraint(_AFTER))


def downgrade() -> None:
    op.execute("ALTER TABLE sources.staging DROP CONSTRAINT staging_entry_mode_check")
    op.execute(
        "UPDATE sources.staging SET entry_mode = 'fetch_missing_theses' "
        "WHERE entry_mode = 'fetch_missing_nnt' AND source = 'theses'"
    )
    op.execute(
        "UPDATE sources.staging SET entry_mode = 'fetch_missing_hal' "
        "WHERE entry_mode IN ('fetch_missing_hal_id', 'fetch_missing_nnt') AND source = 'hal'"
    )
    op.execute(
        "UPDATE sources.staging SET entry_mode = 'bulk' WHERE entry_mode = 'fetch_missing_hal_id'"
    )
    op.execute(_constraint(_BEFORE))
