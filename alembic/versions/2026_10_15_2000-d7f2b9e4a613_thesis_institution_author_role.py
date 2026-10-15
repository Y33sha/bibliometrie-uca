"""Indice de la thèse soutenue dans l'établissement ; structures d'une publication par ses auteurs

- Le type `perimeter_evidence` gagne la valeur `thesis_institution`, indice propre au document.
- `publication_structures` ne retient que les authorships qui ont le rôle d'auteur : direction de thèse, jury, édition ou traduction ne rattachent pas une publication à une structure.

Revision ID: d7f2b9e4a613
Revises: c8e2a4f6d391
Create Date: 2026-10-15 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7f2b9e4a613"
down_revision: str | Sequence[str] | None = "c8e2a4f6d391"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _publication_structures(author_only: bool) -> str:
    condition = "WHERE a.roles && ARRAY['author']::text[]" if author_only else ""
    return f"""
        DROP MATERIALIZED VIEW publications.publication_structures;
        CREATE MATERIALIZED VIEW publications.publication_structures AS
        SELECT DISTINCT a.publication_id, aus.structure_id
        FROM publications.authorships a
        JOIN publications.authorship_structures aus ON aus.authorship_id = a.id
        {condition}
        WITH DATA;
        CREATE UNIQUE INDEX publication_structures_pub_struct
            ON publications.publication_structures (publication_id, structure_id);
        CREATE INDEX idx_publication_structures_structure
            ON publications.publication_structures (structure_id);
    """


def upgrade() -> None:
    op.execute("ALTER TYPE public.perimeter_evidence ADD VALUE IF NOT EXISTS 'thesis_institution'")
    op.execute(_publication_structures(author_only=True))


def downgrade() -> None:
    op.execute(_publication_structures(author_only=False))
    # PostgreSQL ne retire pas une valeur d'enum : `thesis_institution` reste dans `perimeter_evidence`.
