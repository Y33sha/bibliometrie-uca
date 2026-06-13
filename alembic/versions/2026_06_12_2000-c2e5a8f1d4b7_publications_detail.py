"""publications_detail : sort les colonnes grasses detail-only de publications

`publications` portait inline abstract / topics / biblio / keywords (~280 Mo sur
649 Mo de heap, ~3,5 Ko/ligne). Ces colonnes ne sont lues que par la page detail
d'une publication ; les listes et les ~11 facettes, elles, scannent tout
l'ensemble in-perimeter a chaque requete. Lignes larges = beaucoup de pages 8 Ko
a lire, repete par facette (et meme parallelisees, les scans se disputent l'I/O).

On les sort dans `publications_detail` (1:1, FK ON DELETE CASCADE). `publications`
devient assez etroite pour tenir en cache → les scans de listes/facettes
deviennent CPU/memoire-bound. `meta` reste (dates de these lues/triees par la liste).

L'ecriture canonique passe par `publication_repository.save` (upsert detail) ;
`create` n'ecrivait pas ces colonnes. Lecture : `find_by_id` (domaine) et la page
detail joignent `publications_detail`.

Revision ID: c2e5a8f1d4b7
Revises: a1f3c8e2d5b9
Create Date: 2026-06-12 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2e5a8f1d4b7"
down_revision: str | Sequence[str] | None = "a1f3c8e2d5b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE publications_detail (
            publication_id integer PRIMARY KEY REFERENCES publications(id) ON DELETE CASCADE,
            abstract text,
            keywords text[],
            topics jsonb,
            biblio jsonb
        )
    """)
    op.execute("""
        INSERT INTO publications_detail (publication_id, abstract, keywords, topics, biblio)
        SELECT id, abstract, keywords, topics, biblio
        FROM publications
        WHERE abstract IS NOT NULL OR keywords IS NOT NULL
           OR topics IS NOT NULL OR biblio IS NOT NULL
    """)
    op.execute("ALTER TABLE publications DROP COLUMN abstract")
    op.execute("ALTER TABLE publications DROP COLUMN keywords")
    op.execute("ALTER TABLE publications DROP COLUMN topics")
    op.execute("ALTER TABLE publications DROP COLUMN biblio")
    op.execute("ANALYZE publications")


def downgrade() -> None:
    op.execute("ALTER TABLE publications ADD COLUMN abstract text")
    op.execute("ALTER TABLE publications ADD COLUMN keywords text[]")
    op.execute("ALTER TABLE publications ADD COLUMN topics jsonb")
    op.execute("ALTER TABLE publications ADD COLUMN biblio jsonb")
    op.execute("""
        UPDATE publications p SET
            abstract = d.abstract, keywords = d.keywords,
            topics = d.topics, biblio = d.biblio
        FROM publications_detail d WHERE d.publication_id = p.id
    """)
    op.execute("DROP TABLE publications_detail")
