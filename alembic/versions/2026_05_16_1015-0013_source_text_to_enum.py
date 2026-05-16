"""source : text → enum source_type sur staging, source_publications, source_authorships

Cohérence enum/text. Avant cette migration, `publication_subjects.source`
utilisait déjà l'enum `source_type` mais les 3 autres tables stockaient
la source comme `text`. Tout passe en enum, sauf `person_identifiers.source`
qui reste `text` (sémantique différente : provenance d'un identifiant —
contient aussi `'manual'`, `'auto'`).

Vérifié avant migration : `SELECT DISTINCT source` retourne uniquement
les 6 valeurs de l'enum (hal, openalex, wos, scanr, theses, crossref)
sur les 3 tables ciblées.

Opération : `ALTER COLUMN TYPE` avec USING — réécrit la table
(ACCESS EXCLUSIVE LOCK + rewrite). Lent sur grosses tables.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-16 10:15:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES = ("staging", "source_publications", "source_authorships")


# `idx_sa_nonhal_outscope` est un index partiel WHERE source <> 'hal'::text :
# le cast bloque le changement de type (pas d'opérateur source_type <> text).
# DROP avant l'ALTER, RECREATE après avec le bon littéral (enum).
_NONHAL_IDX_DROP = "DROP INDEX IF EXISTS public.idx_sa_nonhal_outscope"
_NONHAL_IDX_CREATE_ENUM = (
    "CREATE INDEX idx_sa_nonhal_outscope "
    "ON public.source_authorships (source_publication_id, author_position) "
    "WHERE source <> 'hal' AND in_perimeter = false"
)
_NONHAL_IDX_CREATE_TEXT = (
    "CREATE INDEX idx_sa_nonhal_outscope "
    "ON public.source_authorships (source_publication_id, author_position) "
    "WHERE source <> 'hal'::text AND in_perimeter = false"
)


def upgrade() -> None:
    op.execute(_NONHAL_IDX_DROP)
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE public.{table} "
            f"ALTER COLUMN source TYPE public.source_type "
            f"USING source::public.source_type"
        )
    op.execute(_NONHAL_IDX_CREATE_ENUM)


def downgrade() -> None:
    op.execute(_NONHAL_IDX_DROP)
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ALTER COLUMN source TYPE text USING source::text")
    op.execute(_NONHAL_IDX_CREATE_TEXT)
