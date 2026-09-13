"""Suppression de la table distinct_publications

La table portait les paires de publications déclarées distinctes depuis la page d'administration du dédoublonnage. Le pipeline ne la lisait pas, et la réconciliation, qui regroupe les notices sources à chaque passage, ne tenait aucun compte de ces déclarations.

Revision ID: a7d3e51c9b84
Revises: f1c4d82a6b39
Create Date: 2026-09-13 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7d3e51c9b84"
down_revision: str | Sequence[str] | None = "f1c4d82a6b39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
DROP TABLE public.distinct_publications;
"""

_DOWNGRADE = """
CREATE TABLE public.distinct_publications (
    id serial PRIMARY KEY,
    pub_id_a integer NOT NULL REFERENCES public.publications(id) ON DELETE CASCADE,
    pub_id_b integer NOT NULL REFERENCES public.publications(id) ON DELETE CASCADE,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT distinct_pubs_ordered CHECK (pub_id_a < pub_id_b),
    CONSTRAINT distinct_publications_pub_id_a_pub_id_b_key UNIQUE (pub_id_a, pub_id_b)
);

CREATE INDEX idx_distinct_pubs_a ON public.distinct_publications USING btree (pub_id_a);
CREATE INDEX idx_distinct_pubs_b ON public.distinct_publications USING btree (pub_id_b);
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
