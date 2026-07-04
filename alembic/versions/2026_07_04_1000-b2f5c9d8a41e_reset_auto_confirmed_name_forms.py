"""Remet à pending les formes de nom auto-confirmées (dérivées du nom canonique)

Le modèle retire la confirmation automatique des formes `source='persons'` :
`status='confirmed'` ne doit plus signifier que « validé par un humain ». Le stock
déjà auto-confirmé (`status='confirmed'` avec `'persons' ∈ sources`) est remis à
`pending` — ces formes n'ont jamais reçu de validation humaine, leur `confirmed`
venait de l'auto-règle. Leur appartenance au nom canonique reste lisible dans
`sources`. Après cette remise à plat, `status='confirmed'` désigne sans ambiguïté
une confirmation admin.

Revision ID: b2f5c9d8a41e
Revises: f1a7c8b2e4d6
Create Date: 2026-07-04 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2f5c9d8a41e"
down_revision: str | Sequence[str] | None = "f1a7c8b2e4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE person_name_forms
        SET status = 'pending'
        WHERE status = 'confirmed' AND 'persons' = ANY(sources)
    """)


def downgrade() -> None:
    # Restaure l'auto-confirmation des formes dérivées du nom canonique.
    op.execute("""
        UPDATE person_name_forms
        SET status = 'confirmed'
        WHERE status = 'pending' AND 'persons' = ANY(sources)
    """)
