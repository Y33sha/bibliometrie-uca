"""source_authorships : partial index on (source_publication_id) WHERE in_perimeter = TRUE

Revision ID: f177a34202c2
Revises: 8102106c4910
Create Date: 2026-05-20 09:39:51.747788

Index partiel symétrique à `idx_sa_nonhal_outscope` (qui couvre
`in_perimeter = FALSE`). Cible les ~100k authorships in_perimeter sur
11M lignes — index minuscule (~quelques MB).

Consommateurs :
- `hal_affiliation_conflicts` (NOT EXISTS sur SP WoS/OA in_perimeter).
- `fetch_unlinked_authorships` (pipeline persons, filtre
  `WHERE in_perimeter = TRUE`).
- Toute requête de statistique restreinte au périmètre UCA.

Avant index : EXPLAIN ANALYZE de `hal_affiliation_conflicts` à ~12s
(Parallel Seq Scan sur 11M source_authorships pour filtrer in_perimeter).
Après index + récriture agrégée : ~3.4s.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f177a34202c2"
down_revision: str | Sequence[str] | None = "8102106c4910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS : tolère l'index déjà créé hors-bande (typiquement
    # via `CREATE INDEX CONCURRENTLY` lors d'un test de perf en prod
    # antérieur à cette migration).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sa_in_perimeter "
        "ON source_authorships (source_publication_id) "
        "WHERE in_perimeter = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sa_in_perimeter")
