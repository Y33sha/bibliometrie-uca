"""Redirections retirées pour les entités absorbées encore présentes

Revision ID: d2a6f9c3e815
Revises: c4d8e2f7a913
Create Date: 2026-10-21 10:00:00.000000

Une redirection de `merge_redirects` mène d'une entité supprimée par une fusion à l'entité conservée. La dissolution des publications a enregistré des redirections pour des publications restées en place, qui gardaient des enregistrements sources : une nouvelle dissolution de ces publications heurte la clé primaire. La migration supprime les redirections dont l'entité absorbée existe encore.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2a6f9c3e815"
down_revision: str | Sequence[str] | None = "c4d8e2f7a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = {
    "person": "persons.persons",
    "journal": "publishing.journals",
    "publisher": "publishing.publishers",
    "monograph": "publishing.monographs",
    "publication": "publications.publications",
}


def upgrade() -> None:
    for entity, table in _TABLES.items():
        op.execute(f"""
            DELETE FROM public.merge_redirects m
            USING {table} x
            WHERE m.entity = '{entity}' AND x.id = m.absorbed_id
        """)


def downgrade() -> None:
    """Les redirections supprimées étaient fausses : rien à restaurer."""
