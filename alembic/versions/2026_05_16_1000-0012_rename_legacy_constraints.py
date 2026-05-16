"""rename legacy constraints : `source_documents` → `source_publications`, `name_forms` → `structure_name_forms`, `addresses.raw_text_normalized` → `addresses.normalized_text`

Nettoyage des noms de contraintes hérités d'anciens noms de tables/colonnes
(survivants des squashes Alembic précédents). Toutes les contraintes
restent fonctionnellement pertinentes — seul le nom change. Aucune
modification de schéma ni de données : metadata-only.

14 renames :
- 9 NOT NULL (table source_publications × 4, structure_name_forms × 3,
  source_authorships × 1, addresses × 1)
- 1 PRIMARY KEY (structure_name_forms)
- 4 FK (structure_name_forms × 1, source_publications × 3)

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-16 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, old_name, new_name)
_RENAMES: list[tuple[str, str, str]] = [
    # addresses
    (
        "addresses",
        "addresses_raw_text_normalized_not_null",
        "addresses_normalized_text_not_null",
    ),
    # source_authorships
    (
        "source_authorships",
        "source_authorships_source_document_id_not_null",
        "source_authorships_source_publication_id_not_null",
    ),
    # source_publications : NOT NULL
    (
        "source_publications",
        "source_documents_id_not_null",
        "source_publications_id_not_null",
    ),
    (
        "source_publications",
        "source_documents_source_not_null",
        "source_publications_source_not_null",
    ),
    (
        "source_publications",
        "source_documents_source_id_not_null",
        "source_publications_source_id_not_null",
    ),
    (
        "source_publications",
        "source_documents_title_not_null",
        "source_publications_title_not_null",
    ),
    # source_publications : FK
    (
        "source_publications",
        "source_documents_journal_id_fkey",
        "source_publications_journal_id_fkey",
    ),
    (
        "source_publications",
        "source_documents_publication_id_fkey",
        "source_publications_publication_id_fkey",
    ),
    (
        "source_publications",
        "source_documents_staging_id_fkey",
        "source_publications_staging_id_fkey",
    ),
    # structure_name_forms : NOT NULL
    (
        "structure_name_forms",
        "name_forms_id_not_null",
        "structure_name_forms_id_not_null",
    ),
    (
        "structure_name_forms",
        "name_forms_structure_id_not_null",
        "structure_name_forms_structure_id_not_null",
    ),
    (
        "structure_name_forms",
        "name_forms_form_text_not_null",
        "structure_name_forms_form_text_not_null",
    ),
    # structure_name_forms : PK
    (
        "structure_name_forms",
        "name_forms_pkey",
        "structure_name_forms_pkey",
    ),
    # structure_name_forms : FK
    (
        "structure_name_forms",
        "name_forms_structure_id_fkey",
        "structure_name_forms_structure_id_fkey",
    ),
]


def upgrade() -> None:
    for table, old_name, new_name in _RENAMES:
        op.execute(f'ALTER TABLE public.{table} RENAME CONSTRAINT "{old_name}" TO "{new_name}"')


def downgrade() -> None:
    for table, old_name, new_name in _RENAMES:
        op.execute(f'ALTER TABLE public.{table} RENAME CONSTRAINT "{new_name}" TO "{old_name}"')
