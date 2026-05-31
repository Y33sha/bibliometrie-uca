"""staging.not_found_at + table doi_lookups (backoff cross-import)

Sépare les deux sémantiques de `not_found` aujourd'hui amalgamées dans
`staging.not_found` :

- Miss **natif** (un id natif ne résout pas : hal-id 404, DOI 404 chez
  Crossref) : toujours définitif. Reste dans `staging`, porté par la
  nouvelle colonne `not_found_at` (`IS NOT NULL` = ancien `not_found = TRUE`).
- Miss **cross-import** (un DOI cherché sur HAL/OpenAlex/WoS/ScanR est
  absent) : temporaire (la source peut indexer plus tard). Sort de
  `staging` vers la table dédiée `doi_lookups`, avec backoff `next_retry`.

Les rows `not_found = TRUE` existantes sont toutes des miss natifs
définitifs (seuls Crossref `fetch_missing_doi` et HAL `fetch_missing_hal_id`
écrivaient `not_found`) : backfill direct vers `not_found_at`.

Revision ID: d4e8a1f6c3b7
Revises: b3c5d8a2f7e9
Create Date: 2026-05-31 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4e8a1f6c3b7"
down_revision: str | Sequence[str] | None = "b3c5d8a2f7e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. staging : not_found BOOL → not_found_at TIMESTAMPTZ
    op.execute("ALTER TABLE staging DROP CONSTRAINT staging_not_found_implies_processed")
    # Index partiel `WHERE not_found = true` : dépend de la colonne, à retirer
    # avant le DROP COLUMN. Aucun équivalent recréé (pas de consommateur).
    op.execute("DROP INDEX IF EXISTS idx_staging_not_found")
    op.execute("ALTER TABLE staging ADD COLUMN not_found_at timestamptz")
    op.execute("UPDATE staging SET not_found_at = imported_at WHERE not_found = TRUE")
    op.execute("ALTER TABLE staging DROP COLUMN not_found")
    op.execute(
        """
        ALTER TABLE staging ADD CONSTRAINT staging_not_found_at_implies_processed
            CHECK (not_found_at IS NULL OR processed)
        """
    )

    # 2. Table de backoff des miss cross-import (clé (source, doi), pas un staging)
    op.execute(
        """
        CREATE TABLE doi_lookups (
            source        source_type NOT NULL,
            doi           text        NOT NULL,
            not_found_at  timestamptz NOT NULL,
            next_retry    timestamptz NOT NULL,
            PRIMARY KEY (source, doi)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE doi_lookups")
    op.execute("ALTER TABLE staging DROP CONSTRAINT staging_not_found_at_implies_processed")
    op.execute("ALTER TABLE staging ADD COLUMN not_found boolean DEFAULT false")
    op.execute("UPDATE staging SET not_found = TRUE WHERE not_found_at IS NOT NULL")
    op.execute("ALTER TABLE staging DROP COLUMN not_found_at")
    op.execute(
        """
        ALTER TABLE staging ADD CONSTRAINT staging_not_found_implies_processed
            CHECK ((NOT not_found) OR processed)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_staging_not_found ON staging (source, source_id)
            WHERE not_found = true
        """
    )
