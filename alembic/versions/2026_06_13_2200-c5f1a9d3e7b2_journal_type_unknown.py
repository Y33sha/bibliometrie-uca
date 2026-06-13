"""journal_type : valeur 'unknown' + défaut 'unknown'

Le sub-step enrich_journals_from_openalex était gaté sur `apc_amount IS NULL`
(jamais rempli — OpenAlex APC quasi vide) → réinterrogeait ~tout le catalogue à
chaque full run pour rien. Le `journal_type` étant stable par revue, on gate
désormais sur `journal_type = 'unknown' AND openalex_id IS NOT NULL` : un journal
nouvellement créé naît `unknown` (= « inconnu » côté UI), est typé une fois, puis
n'est plus interrogé. Pas de backfill des `journal` existants (chantier qualité
rétrospectif distinct).

Revision ID: c5f1a9d3e7b2
Revises: e3f7b2d9c5a8
Create Date: 2026-06-13 22:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5f1a9d3e7b2"
down_revision: str | Sequence[str] | None = "e3f7b2d9c5a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE doit être commité avant d'être utilisable (SET DEFAULT 'unknown').
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE journal_type ADD VALUE IF NOT EXISTS 'unknown'")
    op.execute("ALTER TABLE journals ALTER COLUMN journal_type SET DEFAULT 'unknown'")


def downgrade() -> None:
    # PostgreSQL ne sait pas retirer une valeur d'enum ; on remet juste le défaut.
    op.execute("ALTER TABLE journals ALTER COLUMN journal_type SET DEFAULT 'journal'")
