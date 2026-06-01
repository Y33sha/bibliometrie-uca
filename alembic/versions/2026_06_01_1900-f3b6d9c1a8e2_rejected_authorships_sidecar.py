"""authorships : sidecar `rejected_authorships` + drop `excluded` / `source_manual`

Extrait le rejet canonique (`authorships.excluded`) dans un store univoque
`rejected_authorships(publication_id, person_id)`, lu par les sites de
création d'`authorships` (anti-join) pour skipper les paires rejetées — le
rejet survit ainsi à tout rebuild, contrairement à la colonne (purgée en
mode `full`) et au détachement source (réversible par re-matching).

Dans la foulée, drop `authorships.source_manual` (vestigial : 0 ligne TRUE
en prod, aucune query).

Backfill du sidecar depuis les exclusions existantes (0 en prod, idempotent).

Revision ID: f3b6d9c1a8e2
Revises: e1f4b8c2a6d9
Create Date: 2026-06-01 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3b6d9c1a8e2"
down_revision: str | Sequence[str] | None = "e1f4b8c2a6d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE rejected_authorships (
            publication_id integer NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
            person_id      integer NOT NULL REFERENCES persons(id)      ON DELETE CASCADE,
            created_at     timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (publication_id, person_id)
        )
    """)
    op.execute("""
        INSERT INTO rejected_authorships (publication_id, person_id)
        SELECT publication_id, person_id FROM authorships
        WHERE excluded AND person_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    op.execute("ALTER TABLE authorships DROP COLUMN excluded")
    op.execute("ALTER TABLE authorships DROP COLUMN source_manual")


def downgrade() -> None:
    op.execute("ALTER TABLE authorships ADD COLUMN source_manual boolean DEFAULT false")
    op.execute("ALTER TABLE authorships ADD COLUMN excluded boolean DEFAULT false")
    # Best-effort : re-marque les paires encore présentes. Les rows supprimées
    # au moment du rejet (modèle skip-at-build) ne sont pas ressuscitées.
    op.execute("""
        UPDATE authorships a SET excluded = TRUE
        FROM rejected_authorships rj
        WHERE rj.publication_id = a.publication_id AND rj.person_id = a.person_id
    """)
    op.execute("DROP TABLE rejected_authorships")
