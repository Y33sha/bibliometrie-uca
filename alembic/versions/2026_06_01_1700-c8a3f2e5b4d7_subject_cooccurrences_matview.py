"""subject_cooccurrences : table → matérialisée

`subject_cooccurrences` est entièrement dérivée de `publication_subjects`
(paires de sujets co-présents sur une publication, count >= 2). Le rebuild
impératif `TRUNCATE + INSERT` de la phase `cooccurrences` est remplacé par
un `REFRESH MATERIALIZED VIEW`. Le seuil `min_count = 2` est figé dans la
définition de la vue.

Index :
- `subject_cooccurrences_pkey` unique (subject_a_id, subject_b_id) — laisse
  ouverte l'option `REFRESH CONCURRENTLY` plus tard.
- `subject_cooccurrences_b_idx` (subject_b_id) — pour le `UNION ALL` côté
  `get_subject_neighbors`.
- `subject_cooccurrences_count_idx` (count DESC).

Les FK CASCADE vers `subjects` ne sont pas portées par la matview ; les
queries de lecture font un JOIN inner avec `subjects` qui filtre les rows
orphelines (en attendant le prochain refresh).

Revision ID: c8a3f2e5b4d7
Revises: b2d4e7a1c8f3
Create Date: 2026-06-01 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8a3f2e5b4d7"
down_revision: str | Sequence[str] | None = "b2d4e7a1c8f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_MATVIEW_SELECT = """
SELECT
    ps1.subject_id AS subject_a_id,
    ps2.subject_id AS subject_b_id,
    COUNT(DISTINCT ps1.publication_id)::integer AS count
FROM publication_subjects ps1
JOIN publication_subjects ps2
  ON ps1.publication_id = ps2.publication_id
 AND ps1.subject_id < ps2.subject_id
WHERE NOT ps1.rejected AND NOT ps2.rejected
GROUP BY ps1.subject_id, ps2.subject_id
HAVING COUNT(DISTINCT ps1.publication_id) >= 2
"""


def upgrade() -> None:
    op.execute("DROP TABLE subject_cooccurrences CASCADE")
    op.execute(f"CREATE MATERIALIZED VIEW subject_cooccurrences AS {_MATVIEW_SELECT} WITH DATA")
    op.execute(
        "CREATE UNIQUE INDEX subject_cooccurrences_pkey "
        "ON subject_cooccurrences (subject_a_id, subject_b_id)"
    )
    op.execute("CREATE INDEX subject_cooccurrences_b_idx ON subject_cooccurrences (subject_b_id)")
    op.execute("CREATE INDEX subject_cooccurrences_count_idx ON subject_cooccurrences (count DESC)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW subject_cooccurrences")
    op.execute(
        """
        CREATE TABLE subject_cooccurrences (
            subject_a_id integer NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            subject_b_id integer NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            count integer NOT NULL,
            PRIMARY KEY (subject_a_id, subject_b_id),
            CONSTRAINT subject_cooccurrences_ordered CHECK (subject_a_id < subject_b_id)
        )
        """
    )
    op.execute("CREATE INDEX subject_cooccurrences_b_idx ON subject_cooccurrences (subject_b_id)")
    op.execute("CREATE INDEX subject_cooccurrences_count_idx ON subject_cooccurrences (count DESC)")
    op.execute(
        f"INSERT INTO subject_cooccurrences (subject_a_id, subject_b_id, count) {_MATVIEW_SELECT}"
    )
