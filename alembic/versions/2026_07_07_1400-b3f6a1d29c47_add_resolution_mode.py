"""resolution_mode : par quel canal le person_id d'une signature a été posé

Enregistre, sur chaque `source_authorships` résolue automatiquement, le canal qui a posé
son `person_id` — `identifier` (identifiant fort), `name` (forme de nom) ou `cross_source`
(même publication × position auteur qu'une signature déjà résolue). NULL quand la signature
est orpheline. C'est la partition qui porte les réinitialisations ordre-indépendantes de la
phase personnes : le canal identifiant re-nulle les `identifier` affectées par un transfert
de valeur, le canal nominal re-orpheline les `name` à forme devenue ambiguë, les
`cross_source` sont recalculées en bloc. Les signatures épinglées par l'admin
(`confirmed_authorships`) portent leur `person_id` hors de ce mode : l'autorité y est
l'épinglage, pas le canal.

Revision ID: b3f6a1d29c47
Revises: a1c4e7b09f52
Create Date: 2026-07-07 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b3f6a1d29c47"
down_revision: str | Sequence[str] | None = "a1c4e7b09f52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
CREATE TYPE public.resolution_mode AS ENUM (
    'identifier',
    'name',
    'cross_source'
);

ALTER TABLE public.source_authorships
    ADD COLUMN resolution_mode public.resolution_mode;
"""

_DOWNGRADE = """
ALTER TABLE public.source_authorships DROP COLUMN IF EXISTS resolution_mode;
DROP TYPE IF EXISTS public.resolution_mode;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
