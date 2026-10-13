"""Redirections des identifiants absorbés par une fusion

`merge_redirects` associe l'identifiant d'une entité absorbée à celui de l'entité conservée. Une page publique ouverte sur l'identifiant absorbé mène ainsi à l'entité conservée.

Revision ID: e3b7d1f5a926
Revises: d6a9c3e1f284
Create Date: 2026-10-13 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3b7d1f5a926"
down_revision: str | Sequence[str] | None = "d6a9c3e1f284"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE public.merged_entity AS ENUM
            ('person', 'journal', 'publisher', 'monograph', 'publication');
        CREATE TABLE public.merge_redirects (
            entity public.merged_entity NOT NULL,
            absorbed_id integer NOT NULL,
            kept_id integer NOT NULL,
            merged_at timestamp with time zone DEFAULT now() NOT NULL,
            PRIMARY KEY (entity, absorbed_id)
        );
        CREATE INDEX idx_merge_redirects_kept ON public.merge_redirects (entity, kept_id);
        COMMENT ON TABLE public.merge_redirects IS
            'Identifiant d''une entité absorbée par une fusion, et identifiant de l''entité conservée. Une redirection en chaîne mène directement à la dernière entité conservée.';
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE public.merge_redirects;
        DROP TYPE public.merged_entity;
    """)
