"""journal_type : ajouter la valeur d'enum 'ebook_platform'

Distingue les plateformes eBooks (point d'accès — type OpenAlex Sources `ebook platform`) des séries d'ouvrages cohérentes (`book_series`).
Le mapping `domain.journals.journal.map_openalex_source_type` route désormais OA `ebook platform` → `ebook_platform`, alimenté par la phase enrich et par le script `interfaces/cli/oneshot/backfill_journal_types_from_openalex.py`.

Revision ID: f4a7b2c8e1d3
Revises: e3f1c5a8b6d2
Create Date: 2026-05-26 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4a7b2c8e1d3"
down_revision: str | Sequence[str] | None = "e3f1c5a8b6d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE public.journal_type ADD VALUE IF NOT EXISTS 'ebook_platform'")


def downgrade() -> None:
    # Postgres ne permet pas `ALTER TYPE ... DROP VALUE` directement ; pour
    # rollback il faudrait recréer l'enum sans la valeur et basculer la
    # colonne via cast (cf. migration 0020 sur structure_type). Cas peu
    # probable ici — non implémenté.
    raise NotImplementedError("Postgres ne supporte pas le DROP VALUE sur enum")
