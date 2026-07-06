"""Ajoute la valeur 'authenticated' à l'enum identifier_status

Statut attestant qu'un chercheur a lui-même authentifié son ORCID en se connectant
à son compte. Seul un ORCID peut le porter. Posé exclusivement par l'import dédié des
ORCID authentifiés ; sa protection (immuabilité, écriture réservée) est portée par la
migration du trigger `protect_authenticated_identifier`.

Revision ID: d1a4f7c2e9b8
Revises: c5e2a71f9b04
Create Date: 2026-07-06 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d1a4f7c2e9b8"
down_revision: str | Sequence[str] | None = "c5e2a71f9b04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE identifier_status ADD VALUE IF NOT EXISTS 'authenticated'")


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade recrée le type sans
    # 'authenticated' : les lignes qui le portent sont d'abord ramenées à 'confirmed'
    # (statut fort le plus proche).
    op.execute("UPDATE person_identifiers SET status = 'confirmed' WHERE status = 'authenticated'")
    op.execute("ALTER TYPE identifier_status RENAME TO identifier_status_old")
    op.execute("CREATE TYPE identifier_status AS ENUM ('pending', 'confirmed', 'rejected')")
    op.execute(
        "ALTER TABLE person_identifiers ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE identifier_status "
        "USING status::text::identifier_status, "
        "ALTER COLUMN status SET DEFAULT 'pending'"
    )
    op.execute("DROP TYPE identifier_status_old")
