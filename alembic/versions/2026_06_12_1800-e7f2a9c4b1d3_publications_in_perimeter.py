"""publications.in_perimeter materialise (perf des listes UCA)

Depuis que les publications hors perimetre sont promues dans `publications`, les
requetes de liste scopees au perimetre filtraient via un EXISTS sur `authorships`
qui scannait toute la table (1,17 Go de heap, ~3x plus de lignes que d'in-perimetre).
On materialise le statut perimetre en colonne, maintenue en fin de phase
`authorships` (rollup de `authorships.in_perimeter`) et a l'action de rejet de
personne. Le filtre `publication_in_perimeter` lit desormais la colonne.

in_perimeter = au moins un authorship in-perimetre d'une personne non rejetee.

Revision ID: e7f2a9c4b1d3
Revises: c8f3a6b1e4d7
Create Date: 2026-06-12 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7f2a9c4b1d3"
down_revision: str | Sequence[str] | None = "c8f3a6b1e4d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE publications ADD COLUMN in_perimeter boolean NOT NULL DEFAULT false")
    op.execute("""
        UPDATE publications p SET in_perimeter = TRUE
        WHERE EXISTS (
            SELECT 1 FROM authorships a
            JOIN persons pe ON pe.id = a.person_id AND pe.rejected = FALSE
            WHERE a.publication_id = p.id AND a.in_perimeter = TRUE
        )
    """)
    # Tri par defaut des listes (pub_year DESC) restreint au perimetre.
    op.execute(
        "CREATE INDEX idx_publications_in_perimeter_year "
        "ON publications (pub_year DESC) WHERE in_perimeter"
    )
    # Sous-requetes correlees pub_count par editeur/revue (jointure via journal_id).
    op.execute(
        "CREATE INDEX idx_publications_in_perimeter_journal "
        "ON publications (journal_id) WHERE in_perimeter"
    )
    op.execute("ANALYZE publications")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_publications_in_perimeter_journal")
    op.execute("DROP INDEX IF EXISTS idx_publications_in_perimeter_year")
    op.execute("ALTER TABLE publications DROP COLUMN IF EXISTS in_perimeter")
