"""staging.entry_mode : provenance d'entrée d'une ligne (bulk vs cross-import)

Trace comment chaque ligne staging est entrée : 'bulk' (extraction native d'une
source), 'cross_import_doi' (récupérée par DOI depuis une autre source) ou
'cross_import_hal' (récupérée par hal-id/NNT). Permet d'auditer la couverture du
cross-import et la qualité native de chaque source avant que le cross-import ne
lisse les volumes.

Backfill : crossref/datacite sont à 100 % du cross-import (jamais extraits en bulk)
→ posés 'cross_import_doi'. Le reste prend le défaut 'bulk' ; un réimport complet
(staging vidé puis extract → bulk, cross_imports → cross_import) repose des valeurs
exactes pour hal/openalex/wos/scanr.

Revision ID: c4e9a2f1b7d3
Revises: b8d2f4a1c6e9
Create Date: 2026-06-24 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e9a2f1b7d3"
down_revision: str | Sequence[str] | None = "b8d2f4a1c6e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE staging ADD COLUMN entry_mode text NOT NULL DEFAULT 'bulk'")
    op.execute(
        "ALTER TABLE staging ADD CONSTRAINT staging_entry_mode_check "
        "CHECK (entry_mode IN ('bulk', 'cross_import_doi', 'cross_import_hal'))"
    )
    # `source::text` (et non le littéral enum) : évite « unsafe new enum value usage »
    # quand la valeur 'datacite' a été ajoutée dans une migration de la même transaction.
    op.execute(
        "UPDATE staging SET entry_mode = 'cross_import_doi' "
        "WHERE source::text IN ('crossref', 'datacite')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE staging DROP CONSTRAINT staging_entry_mode_check")
    op.execute("ALTER TABLE staging DROP COLUMN entry_mode")
